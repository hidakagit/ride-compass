"""`domain/leg_costs.py`——レグごとのコスト配列の合成を、配列を直接与えて確かめる。

時刻ビンの本数・代表ビン・除外区間のinf化・所要時間の下地・動的材料の扱い・時刻で変わる軸の入り方・
材料値の読み出し。

ここでは見ないもの:

- 合成した配列を探索と区間の表示がどう読むか（周回・目的地・経由地の経路と区間の値）
  → `test_route_generation_behavior.py`（公開の入口`RouteGenerator`から、小さな道路網で確かめる）。
- 走行モデル（`domain/cycling_speed.py`）・評価軸（`domain/evaluation.py`）・風（`domain/wind.py`）
  → それぞれの持ち主のテストが持つ。

**合成器が呼ぶ相手（走行モデル・停止の待ち・動的材料と動的軸の評価・軸の合成）は本物を通す。** 期待値は
本物の値そのものではなく、入力を1つだけ変えたときの関係（向かい風が強いほど遅い・待ちの件数ぶん長い）で書く。
軸の集合は、風の材料を読む架空の軸を1本だけ宣言する（`wind_axis`）。材料idと路面の値は合成器が読む宣言から取る。
このファイルが組み立てて渡し、読むデータ型（`StaticEdgeScoreMatrix`等）は本物で作る——代役にしても
何も切り離せず、本物が変わったときに黙ってずれるだけになる。
"""

import math
from datetime import datetime, timedelta

import numpy as np
import pytest

from app.domain import leg_costs
from app.domain.attributes import CategoricalColumn
from app.domain.axis_definitions import AxisDefinition, BreakpointLinearShape, MaterialTerm
from app.domain.evaluation import StaticEdgeScoreMatrix
from app.domain.road import SURFACE_ESTIMATES
from app.domain.route import Coordinates
from app.domain.tuning import TUNING_VALUES
from app.domain.wind import WindForecastSeries, WindLattice
from tests.axis_system_fixture import replaced_axis_definitions


def coords(latitude, longitude):
    return Coordinates(latitude=latitude, longitude=longitude)


def wind_series(hours=24, speed_ms=3.0, direction_deg=5.0):
    """時別の風の予報（2026-09-22 0時から）。`speed_ms`は全時刻で同じ値か、時刻ごとの並び。

    格子点は1つだけで、どの区間もその格子点の風を引く（格子の外の地点は端の格子点へ寄る）。"""
    start = datetime(2026, 9, 22, 0, 0)
    return WindForecastSeries(
        times=[start + timedelta(hours=h) for h in range(hours)],
        speed_ms=np.broadcast_to(np.asarray(speed_ms, dtype=float), (1, hours)).copy(),
        direction_deg=np.full((1, hours), direction_deg),
        lattice=WindLattice(south=0.0, west=0.0, lat_step=1.0, lon_step=1.0, rows=1, cols=1),
    )


# --------------------------------------------------------------------------------------
# 代表ビンの選び方
# --------------------------------------------------------------------------------------


def test_representative_bin_is_the_bin_containing_the_middle_of_the_leg():
    """表示と、時刻ラベルを持てない探索が読むビン。中間地点がどのビンに入るかで決まる。

    組み合わせは`_bin_count`が作れるものに限る（見込み3時間なら3本、5時間なら上限の4本）。
    """
    assert leg_costs._representative_bin(4, 5.0) == 2
    assert leg_costs._representative_bin(3, 3.0) == 1


def test_representative_bin_is_zero_when_the_leg_is_a_single_bin():
    """風の系列が無いレグは1本のスナップショット。見込み時間があっても代表は唯一のビン。"""
    assert leg_costs._representative_bin(1, 5.0) == 0


def test_representative_bin_clamps_to_the_last_bin():
    """ビンは上限4本で頭打ちになる。12時間のレグの中間は6本目に当たるが、存在しない。"""
    assert leg_costs._representative_bin(4, 12.0) == 3


# --------------------------------------------------------------------------------------
# 材料値の読み出し
# --------------------------------------------------------------------------------------


def test_material_value_at_distinguishes_absent_from_missing_from_present():
    leg = leg_costs.LegCostArrays(
        cost_lazy=np.zeros(2), difficulty_array=np.zeros(2),
        axis_arrays={}, weight_sums=np.zeros(2), weights={},
        axis_raw_arrays={}, material_arrays={"mat_a": np.array([1.5, np.nan])},
        categorical_material_arrays={}, travel_seconds_full=np.zeros(2),
        travel_seconds_lazy=np.zeros(2), cost_bins_lazy=np.zeros((1, 2)),
        travel_bins_lazy=np.zeros((1, 2)), bin_seconds=np.inf,
    )

    assert leg_costs.material_value_at(leg, "mat_a", 0) == 1.5
    assert leg_costs.material_value_at(leg, "mat_a", 1) is None
    assert leg_costs.material_value_at(leg, "mat_absent", 0) is None


# --------------------------------------------------------------------------------------
# レグごとのコスト配列の合成（LegCostComposer）
# --------------------------------------------------------------------------------------


AXIS_STATIC = "axis_static"
AXIS_WIND = "axis_wind"
#: 停止要因の種別と、その件数の材料（合成器が読む宣言から取る）。
STOP_KIND = next(iter(leg_costs.POI_COUNT_KINDS))
STOP_MATERIAL = leg_costs.stop_count_material_ids()[0]
PAVED, ROUGH = SURFACE_ESTIMATES[0], SURFACE_ESTIMATES[2]


@pytest.fixture
def wind_axis():
    """風の抵抗比（動的材料）を読む軸`axis_wind`だけを宣言する。0で得点0、2で100。"""
    wind_material = next(iter(leg_costs.REQUEST_DYNAMIC_MATERIAL_IDS))
    axis = AxisDefinition(
        axis_id=AXIS_WIND, label="風", default_weight=0.0,
        shape=BreakpointLinearShape(terms=[MaterialTerm(material=wind_material)], breakpoints=[(0.0, 0.0), (2.0, 100.0)]),
    )
    with replaced_axis_definitions({AXIS_WIND: axis}):
        yield


def make_score_matrix(count=3, **overrides):
    defaults = dict(
        distance_m=np.full(count, 1000.0),
        bearing_deg=np.zeros(count),
        gradient_percent=np.zeros(count),
        mid_lat=np.zeros(count),
        mid_lon=np.zeros(count),
        hard_filter_flags={},
        axis_ids=[AXIS_STATIC, AXIS_WIND],
        axis_scores=np.column_stack([np.full(count, 1.0), np.full(count, np.nan)]),
        raw_axis_ids=[AXIS_STATIC],
        axis_raw_values=np.arange(count, dtype=float).reshape(count, 1),
        material_ids=[STOP_MATERIAL],
        material_values=np.full((count, 1), 2.0),
        categorical_material_ids=[leg_costs.ROLLING_RESISTANCE_MATERIAL_ID],
        categorical_material_columns=[CategoricalColumn.encode([PAVED.key] * count)],
    )
    defaults.update(overrides)
    return StaticEdgeScoreMatrix(**defaults)


def make_composer(score_matrix=None, *, weights=None, excluded=None, lazy_row_index=None,
                  wind_series=None, penalty=1.0, speed_kmh=20.0, **kwargs):
    score_matrix = score_matrix if score_matrix is not None else make_score_matrix()
    count = len(score_matrix.distance_m)
    return leg_costs.LegCostComposer(
        score_matrix,
        {AXIS_STATIC: 1.0, AXIS_WIND: 2.0} if weights is None else weights,
        penalty,
        np.zeros(count, dtype=bool) if excluded is None else np.asarray(excluded, dtype=bool),
        None,
        wind_series,
        datetime(2026, 9, 22, 8, 0),
        speed_kmh,
        np.arange(count, dtype=np.int64) if lazy_row_index is None else np.asarray(lazy_row_index, dtype=np.int64),
        **kwargs,
    )


def rising_wind():
    """h時に向かい風0.25×h m/s（風向0。区間の方位は0なので正面から）。出発の8時は2m/sで、1時間ごとに強まる。"""
    return wind_series(speed_ms=np.arange(24.0) * 0.25, direction_deg=0.0)


def test_composer_is_time_varying_only_when_an_hourly_wind_series_exists(wind_axis):
    assert make_composer().time_varying is False
    assert make_composer(wind_series=wind_series()).time_varying is True


def test_to_full_row_order_marks_edges_absent_from_the_search_graph(wind_axis):
    """並行Edgeの採られなかった方は探索に載らない。別Edgeの値で埋めると通過時刻がずれる。"""
    composer = make_composer(make_score_matrix(count=3), lazy_row_index=[2, 0])

    restored = composer.to_full_row_order(np.array([10.0, 20.0]))

    assert restored[2] == 10.0
    assert restored[0] == 20.0
    assert math.isnan(restored[1])


def test_bin_count_is_one_without_a_duration_or_without_wind(wind_axis):
    with_wind = make_composer(wind_series=wind_series())
    assert with_wind._bin_count(None) == 1
    assert make_composer()._bin_count(5.0) == 1


def test_bin_count_covers_the_duration_up_to_the_ceiling(wind_axis):
    """ビン1本ごとにbbox全体の合成が1回走るため、長いレグでも上限で頭打ちにする。"""
    composer = make_composer(wind_series=wind_series())

    assert composer._bin_count(0.1) == 1
    assert composer._bin_count(leg_costs.TIME_BIN_HOURS * 2 + 0.01) == 3
    assert composer._bin_count(leg_costs.TIME_BIN_HOURS * 100) == leg_costs.MAX_TIME_BINS


def test_compose_without_wind_series_makes_one_snapshot_shared_by_every_leg(wind_axis):
    """風の系列が無ければ時刻で変えようがない。レグごとに合成し直す理由が無い。"""
    composer = make_composer()

    outbound = composer.compose("outbound", coords(35.0, 139.0), 0.0, +1, duration_hours=3.0)
    inbound = composer.compose("inbound", coords(35.0, 139.0), 3.0, -1, duration_hours=3.0)

    assert inbound is outbound
    assert outbound.cost_bins_lazy.shape[0] == 1
    assert outbound.bin_seconds == np.inf
    assert outbound.bin_start_hours == ()


def test_compose_splits_a_long_leg_into_hourly_bins_each_at_its_own_time(wind_axis):
    """ビンはそれぞれの開始時刻の風で合成する。向かい風が1時間ごとに強まるので、後のビンほど遅い。"""
    composer = make_composer(wind_series=rising_wind())

    leg = composer.compose("outbound", coords(35.0, 139.0), 0.0, +1, duration_hours=3.0)

    assert leg.cost_bins_lazy.shape == (3, 3)
    assert leg.travel_bins_lazy.shape == (3, 3)
    assert leg.bin_seconds == leg_costs.TIME_BIN_HOURS * 3600.0
    assert leg.bin_start_hours == (0.0, 1.0, 2.0)
    assert (np.diff(leg.travel_bins_lazy, axis=0) > 0).all()


def test_compose_of_an_inbound_leg_counts_time_from_the_start_of_that_leg(wind_axis):
    """`direction=-1`の`offset_hours`はレグの終了時刻。開始時刻へ直さないと風が2時間ずれる。"""
    composer = make_composer(wind_series=wind_series())

    leg = composer.compose("inbound", coords(35.0, 139.0), 5.0, -1, duration_hours=2.0)

    assert leg.bin_start_hours == (3.0, 4.0)


def test_compose_representative_arrays_come_from_the_middle_bin(wind_axis):
    """表示と、時刻ラベルを持てない探索が読む値。端のビンだと実際に走る時刻と合わない。"""
    composer = make_composer(wind_series=rising_wind())

    leg = composer.compose("outbound", coords(35.0, 139.0), 0.0, +1, duration_hours=3.0)

    assert leg.cost_lazy.tolist() == leg.cost_bins_lazy[1].tolist()
    assert leg.cost_lazy.tolist() != leg.cost_bins_lazy[0].tolist()
    assert leg.cost_lazy.tolist() != leg.cost_bins_lazy[2].tolist()


def test_compose_reuses_a_leg_composed_for_the_same_start_and_bins(wind_axis):
    composer = make_composer(wind_series=wind_series())

    first = composer.compose("outbound", coords(35.0, 139.0), 1.0, +1, duration_hours=2.0)
    again = composer.compose("leg1", coords(36.0, 140.0), 1.0, +1, duration_hours=2.0)

    assert again is first


def test_compose_takes_a_bin_from_a_single_bin_leg_of_the_same_time(wind_axis):
    """周回の往路は、見込み時間なしで先に合成した1本と同じ時刻から始まる。"""
    composer = make_composer(wind_series=rising_wind())

    single = composer.compose("outbound", coords(35.0, 139.0), 0.0, +1)
    binned = composer.compose("outbound", coords(35.0, 139.0), 0.0, +1, duration_hours=2.0)

    assert binned.cost_bins_lazy[0].tolist() == single.cost_lazy.tolist()
    assert binned.cost_bins_lazy[1].tolist() != single.cost_lazy.tolist()


def test_compose_with_measured_passage_hours_is_a_single_bin(wind_axis):
    """後ろ向き木は時刻ラベルを持てない。前向き木の実到達時間を区間ごとに渡し、区間ごとにその時刻の風で合成する。"""
    composer = make_composer(wind_series=rising_wind())
    passage = np.array([0.0, 1.0, 2.0])

    leg = composer.compose("inbound", coords(35.0, 139.0), 4.0, -1, passage_hours=passage)

    assert leg.cost_bins_lazy.shape[0] == 1
    assert leg.bin_seconds == np.inf
    assert leg.passage_hours.tolist() == [0.0, 1.0, 2.0]
    # 同じ長さの区間で、後に通る区間ほど向かい風が強い
    assert (np.diff(leg.travel_seconds_full) > 0).all()


def test_compose_keeps_composing_by_time_even_without_an_anchor(wind_axis):
    """風は軸である前に走行モデルの入力。系列があれば基準点の有無に関わらず時刻で引く。"""
    composer = make_composer(wind_series=wind_series())

    leg = composer.compose("outbound", None, 0.0, +1, duration_hours=3.0)

    assert leg.cost_bins_lazy.shape[0] == 3


def test_composed_costs_are_infinite_where_the_zeroth_filter_excludes(wind_axis):
    """探索から見た通行可否はコスト配列だけが表す。有限のまま残すと除外区間を通る。"""
    composer = make_composer(make_score_matrix(count=3), excluded=[False, True, False])

    leg = composer.compose("outbound", coords(35.0, 139.0), 0.0, +1)

    assert np.isinf(leg.cost_lazy[1])
    assert np.isinf(leg.travel_seconds_full[1])
    assert np.isfinite(leg.cost_lazy[0])


def test_composed_materials_drop_dynamic_ones_with_no_data_at_all(wind_axis):
    """全行NaNの動的材料をキーごと持つと、表示が「値0」と「データ無し」を取り違える。風が無ければ風の材料は無い。"""
    calm = make_composer().compose("outbound", coords(35.0, 139.0), 0.0, +1)
    windy = make_composer(wind_series=wind_series()).compose("outbound", coords(35.0, 139.0), 0.0, +1)

    for material_id in leg_costs.REQUEST_DYNAMIC_MATERIAL_IDS:
        assert material_id not in calm.material_arrays
        assert material_id in windy.material_arrays
    assert STOP_MATERIAL in calm.material_arrays


def test_travel_time_adds_the_stop_waits_of_the_materials_that_exist(wind_axis):
    """停止要因の材料が引けないと、全区間の待ちが無言で0秒になる。欠損は0件として扱う（NaNを伝播させない）。"""
    matrix = make_score_matrix(material_values=np.array([[2.0], [np.nan], [0.0]]))

    leg = make_composer(matrix).compose("outbound", coords(35.0, 139.0), 0.0, +1)

    with_stops, missing, without_stops = leg.travel_seconds_full.tolist()
    # 1kmの区間に2件ぶんの待ち
    assert with_stops - without_stops == pytest.approx(2 * leg_costs.stop_seconds(STOP_KIND))
    assert missing == without_stops


def test_travel_time_reads_rolling_resistance_from_the_material_arrays(wind_axis, monkeypatch):
    """転がり抵抗の材料が引けないと、路面の違いが速度に反映されないまま所要時間が出る。"""
    monkeypatch.setitem(TUNING_VALUES, PAVED.rolling_resistance, 0.004)
    monkeypatch.setitem(TUNING_VALUES, ROUGH.rolling_resistance, 0.012)
    matrix = make_score_matrix(count=2, categorical_material_columns=[CategoricalColumn.encode([PAVED.key, ROUGH.key])])

    leg = make_composer(matrix).compose("outbound", coords(35.0, 139.0), 0.0, +1)

    paved, rough = leg.travel_seconds_full.tolist()
    assert rough > paved


def hourly_wind_composer(wind_weight):
    """時刻ごとに向かい風が強まる世界（`rising_wind`）。区間は1km・2kmで、時刻で変わらない軸の得点は40・80。"""
    matrix = make_score_matrix(
        count=2,
        distance_m=np.array([1000.0, 2000.0]),
        axis_scores=np.column_stack([np.array([40.0, 80.0]), np.full(2, np.nan)]),
        axis_raw_values=np.zeros((2, 1)),
    )
    return make_composer(
        matrix, weights={AXIS_STATIC: 1.0, AXIS_WIND: wind_weight}, penalty=0.5, wind_series=rising_wind(),
    )


def test_each_bin_costs_its_own_travel_time_times_the_fixed_penalty(wind_axis):
    """時刻で変わる軸の重みが0なら、割増の倍率は時刻に依らない。風は走行時間を通してだけビンごとに効く。"""
    composer = hourly_wind_composer(wind_weight=0.0)

    leg = composer.compose("outbound", coords(35.0, 139.0), 0.0, +1, duration_hours=2.0)

    assert (leg.travel_bins_lazy[1] > leg.travel_bins_lazy[0]).all()
    # 倍率は 1 + 0.5 × 得点/100
    assert leg.cost_bins_lazy.ravel().tolist() == pytest.approx((leg.travel_bins_lazy * [1.2, 1.4]).ravel().tolist())
    assert leg.difficulty_array.tolist() == [40.0, 80.0]


def test_a_weighted_time_varying_axis_enters_each_bin_at_its_own_time(wind_axis):
    """時刻で変わる軸に重みがあれば、各ビンの合成にそのビンの時刻の値が入る。"""
    composer = hourly_wind_composer(wind_weight=1.0)

    leg = composer.compose("outbound", coords(35.0, 139.0), 0.0, +1, duration_hours=2.0)

    # 向かい風が強い後のビンほど風の軸の得点が高く、割増の倍率が大きい
    multiplier = leg.cost_bins_lazy / leg.travel_bins_lazy
    assert (multiplier[1] > multiplier[0]).all()
    # 経路上の行を時刻で合成し直した難易度は、時刻で変わらない軸と、その時刻の風の軸の重み付き平均
    rows = composer.values_at_rows(np.array([1]), np.array([1.0]))
    assert rows.difficulty_array[0] == pytest.approx((80.0 + rows.axis_arrays[AXIS_WIND][0]) / 2, abs=0.05)
    assert rows.axis_arrays[AXIS_WIND][0] > composer.values_at_rows(np.array([1]), np.array([0.0])).axis_arrays[AXIS_WIND][0]
