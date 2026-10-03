"""`domain/leg_costs.py`——探索範囲の静的スコア行列・重み・0次フィルタ・風から、レグ（時刻・向き）ごとに区間の所要時間と
探索のコスト、区間の表示が読む値を合成する`LegCostComposer`。

入口は`LegCostComposer`（`compose`・`values_at_rows`・`winds_at`・`missing_travel_data_share`・`to_full_row_order`・
`lazy_row`・`wind_unavailable`）と、`LegCostArrays`/`RowValues`の`axis_contributions_at`、`material_value_at`。
静的スコア行列は架空の軸・材料で組み、風に依る軸だけは軸の宣言（本番はDBが正本）を架空の1本へ差し替える。

ここで見ないもの:
- 勾配・風・路面から速度を解く走行モデルそのもの → `test_cycling_speed.py`
- 軸の得点の重み付き平均と、データの無い区間の扱い → `test_difficulty.py`・`test_axis_definitions.py`
- 風を進行方向の成分へ分けることと、予報の格子点の引き当て → `test_wind.py`・`test_wind_grid.py`
- 合成した配列で探索し、経路の区間を組み立てること → `test_road_graph_engine.py`
"""

import logging
from datetime import datetime, timedelta

import numpy as np
import pytest

from app.domain import leg_costs
from app.domain.attributes import CategoricalColumn
from app.domain.evaluation import StaticEdgeScoreMatrix
from app.domain.leg_costs import LegCostComposer
from app.domain.weather import WeatherConditions
from app.domain.wind import WindForecastSeries, WindLattice
from tests.axis_system_fixture import axis_definition, replaced_axis_definitions

START = datetime(2026, 10, 3, 9, 0)
CRUISE_KMH = 20.0
SURFACE = leg_costs.ROLLING_RESISTANCE_MATERIAL_ID
WIND_DRAG = next(iter(leg_costs.REQUEST_DYNAMIC_MATERIAL_IDS))
STOP_DENSITY = dict(zip(leg_costs.POI_COUNT_KINDS, leg_costs.stop_count_material_ids(), strict=True))
WIND_AXIS = "axis_wind"
NORTH, SOUTH = 0.0, 180.0


@pytest.fixture
def wind_axis():
    """風の追加負荷（0で0点・1で100点）を読む公開軸。"""
    with replaced_axis_definitions({WIND_AXIS: axis_definition(WIND_AXIS, material=WIND_DRAG, is_published=True)}):
        yield


def _column(values, n: int) -> np.ndarray:
    return np.asarray(values if isinstance(values, (list, tuple, np.ndarray)) else [values] * n, dtype=float)


def _matrix(n: int, *, distance=1000.0, gradient=0.0, bearing=NORTH, surface="paved",
            axes: dict | None = None, raw_axes: dict | None = None, materials: dict | None = None,
            categories: dict | None = None) -> StaticEdgeScoreMatrix:
    """`n`区間の静的スコア行列。引数は全区間に同じ値か、区間ごとの並び。"""
    axes, raw_axes, materials = axes or {}, raw_axes or {}, materials or {}
    categories = {SURFACE: [surface] * n if isinstance(surface, str) else surface, **(categories or {})}

    def stacked(columns: dict) -> np.ndarray:
        return np.stack([_column(v, n) for v in columns.values()], axis=1) if columns else np.empty((n, 0))

    return StaticEdgeScoreMatrix(
        axis_ids=list(axes), axis_scores=stacked(axes),
        distance_m=_column(distance, n), bearing_deg=_column(bearing, n), hard_filter_flags={},
        gradient_percent=_column(gradient, n), mid_lat=np.full(n, 35.0), mid_lon=np.full(n, 139.0),
        raw_axis_ids=list(raw_axes), axis_raw_values=stacked(raw_axes),
        material_ids=list(materials), material_values=stacked(materials),
        categorical_material_ids=list(categories),
        categorical_material_columns=[CategoricalColumn.encode(v) for v in categories.values()],
    )


def _weather(speed_ms: float, from_deg: float = NORTH) -> WeatherConditions:
    return WeatherConditions(
        temperature_c=None, wind_speed_ms=speed_ms, wind_direction_deg=from_deg, wind_direction_label="北",
        precipitation_mm=None, observed_at=START.isoformat(), twilight=None, precipitation_max_mm=None,
        wind_speed_max_ms=None, temperature_range=None, today_periods=[],
    )


def _series(speeds_by_hour: list[float], from_deg: float = NORTH) -> WindForecastSeries:
    """格子点1つの、`START`から1時間刻みの予報。"""
    return WindForecastSeries(
        times=[START + timedelta(hours=h) for h in range(len(speeds_by_hour))],
        speed_ms=np.array([speeds_by_hour], dtype=float),
        direction_deg=np.full((1, len(speeds_by_hour)), from_deg),
        lattice=WindLattice(south=35.0, west=139.0, lat_step=0.05, lon_step=0.0625, rows=1, cols=1),
    )


def _composer(matrix: StaticEdgeScoreMatrix, *, weights=None, penalty=0.0, excluded=None, weather=None,
              series=None, lazy=None) -> LegCostComposer:
    n = len(matrix.distance_m)
    return LegCostComposer(
        matrix, weights or {}, penalty,
        np.zeros(n, dtype=bool) if excluded is None else np.asarray(excluded, dtype=bool),
        weather, series, START, CRUISE_KMH,
        np.arange(n) if lazy is None else np.asarray(lazy), detour_ratio=1.3,
    )


def _snapshot(matrix, **kwargs):
    return _composer(matrix, **kwargs).compose("leg", None, 0.0, +1)


# --- 所要時間 -------------------------------------------------------------


def test_a_flat_paved_segment_without_wind_or_stops_is_ridden_at_the_cruise_speed():
    leg = _snapshot(_matrix(1, distance=1000.0))

    assert leg.travel_seconds_full[0] == pytest.approx(1000.0 / (CRUISE_KMH / 3.6), rel=2e-3)


def test_the_gradient_in_percent_slows_the_rider_as_that_grade_and_a_missing_one_counts_as_flat():
    """勾配の材料は%で、走行モデルは割合で読む。20km/hの人は5%の登りで時速10km前後になり、平地の倍ほどかかる
    （500%として読めば押して歩く速度で4倍超、0.05%として読めば平地とほぼ同じ）。"""
    leg = _snapshot(_matrix(3, gradient=[5.0, np.nan, 0.0]))
    climb, missing, flat = leg.travel_seconds_full

    assert 1.5 * flat < climb < 3.0 * flat
    assert missing == flat


def test_a_rougher_surface_takes_longer():
    leg = _snapshot(_matrix(2, surface=["paved", "gravel"]))

    assert leg.travel_seconds_full[1] > leg.travel_seconds_full[0]


def test_each_stop_on_a_segment_adds_its_wait():
    """2回/kmの信号がある500mの区間は、信号1回ぶん待つ。密度の値が無い区間は待たない。"""
    leg = _snapshot(_matrix(3, distance=500.0, materials={STOP_DENSITY["signal"]: [2.0, 0.0, np.nan]}))

    assert leg.travel_seconds_full[0] - leg.travel_seconds_full[1] == pytest.approx(leg_costs.stop_seconds("signal"))
    assert leg.travel_seconds_full[2] == leg.travel_seconds_full[1]


def test_an_excluded_segment_cannot_be_passed():
    leg = _snapshot(_matrix(2, axes={"axis_a": 10.0}), weights={"axis_a": 1.0}, penalty=0.5, excluded=[True, False])

    assert np.isinf(leg.travel_seconds_full[0]) and np.isinf(leg.cost_lazy[0])
    assert np.isfinite(leg.cost_lazy[1])


def test_the_wind_at_departure_slows_a_segment_against_it_and_helps_one_with_it():
    calm = _snapshot(_matrix(1)).travel_seconds_full[0]

    leg = _snapshot(_matrix(2, bearing=[NORTH, SOUTH]), weather=_weather(5.0, from_deg=NORTH))

    assert leg.travel_seconds_full[0] > calm > leg.travel_seconds_full[1]


@pytest.mark.parametrize(
    ("weather", "series", "unavailable"),
    [(None, None, True), (_weather(0.0), None, False), (None, _series([0.0, 0.0]), False)],
)
def test_the_travel_time_is_marked_when_no_wind_was_available(weather, series, unavailable):
    assert _composer(_matrix(1), weather=weather, series=series).wind_unavailable is unavailable


# --- コストと表示の値 ---------------------------------------------------------


def test_without_weights_the_cost_is_the_travel_time():
    """好みの重みをすべて0にすると素の所要時間になり、最速の基準線と同じ物差しになる。"""
    leg = _snapshot(_matrix(2, axes={"axis_a": [100.0, 0.0]}), weights={"axis_a": 0.0}, penalty=0.7)

    assert leg.cost_lazy.tolist() == leg.travel_seconds_lazy.tolist()


@pytest.mark.parametrize(("wind_weight", "difficulty"), [(0.0, 65.0), (1.0, 52.0)])
def test_the_cost_is_the_travel_time_raised_by_the_weighted_difficulty(wind_axis, wind_weight, difficulty):
    """コスト＝所要時間×(1＋換算レート×difficulty/100)。風に依る軸に重みがあるときも無いときも同じ式で合成する。

    得点は区間ごとに軸a=20（重み1）・軸b=80（重み3）、風の軸は無風で0点。
    """
    matrix = _matrix(2, axes={"axis_a": 20.0, "axis_b": 80.0, WIND_AXIS: np.nan})
    weights = {"axis_a": 1.0, "axis_b": 3.0, WIND_AXIS: wind_weight}

    leg = _composer(matrix, weights=weights, penalty=0.5, series=_series([0.0, 0.0])).compose("leg", None, 0.0, +1)

    assert leg.difficulty_array.tolist() == [difficulty, difficulty]
    assert leg.cost_lazy == pytest.approx(leg.travel_seconds_lazy * (1 + 0.5 * difficulty / 100))


def test_the_contributions_of_the_axes_add_up_to_the_difficulty():
    leg = _snapshot(_matrix(1, axes={"axis_a": 20.0, "axis_b": 85.0}), weights={"axis_a": 1.0, "axis_b": 2.0})

    contributions = leg.axis_contributions_at(0)

    assert set(contributions) == {"axis_a", "axis_b"}
    assert sum(contributions.values()) == pytest.approx(leg.difficulty_array[0], abs=0.05)


def test_an_axis_that_reads_the_wind_scores_a_headwind_above_a_tailwind(wind_axis):
    matrix = _matrix(2, bearing=[NORTH, SOUTH], axes={WIND_AXIS: np.nan})

    leg = _snapshot(matrix, weights={WIND_AXIS: 1.0}, weather=_weather(5.0, from_deg=NORTH))

    assert leg.axis_arrays[WIND_AXIS][0] > leg.axis_arrays[WIND_AXIS][1]
    assert leg_costs.material_value_at(leg, WIND_DRAG, 0) > 0 > leg_costs.material_value_at(leg, WIND_DRAG, 1)


def test_without_any_wind_the_wind_has_no_value_on_a_segment(wind_axis):
    leg = _snapshot(_matrix(1, axes={WIND_AXIS: np.nan}), weights={WIND_AXIS: 1.0})

    assert WIND_DRAG not in leg.material_arrays
    assert leg_costs.material_value_at(leg, WIND_DRAG, 0) is None
    assert np.isnan(leg.axis_arrays[WIND_AXIS][0])


def test_the_values_shown_on_a_segment_are_the_columns_of_their_own_ids():
    leg = _snapshot(_matrix(
        2,
        raw_axes={"axis_a": [1.0, 2.0], "axis_b": [3.0, 4.0]},
        materials={"material_a": [5.0, np.nan], "material_b": [7.0, 8.0]},
        categories={"category_a": ["x", "y"]},
    ))

    assert leg.axis_raw_arrays["axis_b"].tolist() == [3.0, 4.0]
    assert leg.material_arrays["material_b"].tolist() == [7.0, 8.0]
    assert leg.categorical_material_arrays["category_a"].value_at(1) == "y"
    assert leg_costs.material_value_at(leg, "material_a", 0) == 5.0
    # 欠損と、合成に無い材料は値を持たない。
    assert leg_costs.material_value_at(leg, "material_a", 1) is None
    assert leg_costs.material_value_at(leg, "material_z", 0) is None


# --- 探索の行順 ---------------------------------------------------------------


def test_the_search_order_holds_only_the_segments_on_the_search_graph():
    """同じ2点を結ぶ区間が2本あると、探索のグラフには1本しか載らない（載らない区間は-1・NaN）。"""
    composer = _composer(_matrix(3, distance=[1000.0, 2000.0, 3000.0]), lazy=[2, 0])

    leg = composer.compose("leg", None, 0.0, +1)

    assert leg.travel_seconds_lazy.tolist() == leg.travel_seconds_full[[2, 0]].tolist()
    assert [composer.lazy_row(row) for row in range(3)] == [1, -1, 0]
    restored = composer.to_full_row_order(leg.travel_seconds_lazy)
    assert restored[[0, 2]].tolist() == leg.travel_seconds_full[[0, 2]].tolist()
    assert np.isnan(restored[1])


# --- 時刻ビン -----------------------------------------------------------------


def test_without_an_hourly_forecast_every_leg_shares_one_composition():
    composer = _composer(_matrix(1), weather=_weather(3.0))

    outbound = composer.compose("outbound", None, 0.0, +1, duration_hours=3.0)
    inbound = composer.compose("inbound", None, 2.0, -1, duration_hours=3.0)

    assert inbound is outbound
    assert (len(outbound.cost_bins_lazy), outbound.bin_seconds, outbound.bin_start_hours) == (1, np.inf, ())


@pytest.mark.parametrize(
    ("duration_hours", "bin_starts"),
    [
        (None, (1.0,)),  # 見込み時間が無ければ、レグ全体を開始時刻で1本
        (0.0, (1.0,)),
        (2.5, (1.0, 2.0, 3.0)),
        (10.0, tuple(1.0 + k for k in range(leg_costs.MAX_TIME_BINS))),  # 上限で打ち切る
    ],
)
def test_a_leg_is_cut_into_hourly_bins_over_its_expected_duration(duration_hours, bin_starts):
    leg = _composer(_matrix(1), series=_series([0.0] * 12)).compose("leg", None, 1.0, +1, duration_hours=duration_hours)

    assert leg.bin_start_hours == bin_starts
    assert len(leg.cost_bins_lazy) == len(leg.travel_bins_lazy) == len(bin_starts)
    assert leg.bin_seconds == (np.inf if len(bin_starts) == 1 else leg_costs.TIME_BIN_HOURS * 3600.0)


def test_a_leg_toward_the_anchor_ends_at_its_offset():
    leg = _composer(_matrix(1), series=_series([0.0] * 12)).compose("leg", None, 5.0, -1, duration_hours=2.0)

    assert leg.bin_start_hours == (3.0, 4.0)


def test_each_bin_uses_the_wind_forecast_for_its_hour():
    """風が1時間ごとに強まる予報で、北へ向かう区間は後のビンほど時間がかかる。"""
    leg = _composer(_matrix(1), series=_series([0.0, 4.0, 8.0])).compose("leg", None, 0.0, +1, duration_hours=3.0)

    first, second, third = leg.travel_bins_lazy[:, 0]
    assert first < second < third


@pytest.mark.parametrize(
    ("duration_hours", "representative"),
    [
        (1.5, 0),  # 2本のうち、中間の0.75時間が入るのは最初のビン
        (3.0, 1),
        (4.0, 2),  # 上限の4本で、中間の2時間が入る3本目
        (7.0, 3),  # 同じ4本でも、中間が上限より先なら最後のビン
    ],
)
def test_the_search_without_a_clock_and_the_display_read_the_bin_at_the_middle_of_the_leg(duration_hours, representative):
    composer = _composer(_matrix(1), series=_series([float(h) for h in range(12)]))

    leg = composer.compose("leg", None, 0.0, +1, duration_hours=duration_hours)

    assert leg.cost_lazy.tolist() == leg.cost_bins_lazy[representative].tolist()
    assert leg.travel_seconds_lazy.tolist() == leg.travel_bins_lazy[representative].tolist()


def test_legs_with_the_same_bins_but_a_different_middle_are_not_mixed_up():
    """同じ開始時刻・同じ本数でも、見込み時間が違えば代表のビンは変わる。"""
    composer = _composer(_matrix(1), series=_series([float(h) for h in range(12)]))

    shorter = composer.compose("a", None, 0.0, +1, duration_hours=4.0)
    longer = composer.compose("b", None, 0.0, +1, duration_hours=7.0)

    assert shorter.cost_lazy.tolist() == shorter.cost_bins_lazy[2].tolist()
    assert longer.cost_lazy.tolist() == longer.cost_bins_lazy[3].tolist()


def test_a_bin_already_composed_for_its_hour_is_composed_only_once(caplog):
    """周回の往路の先頭のビンは、見込み時間なしで先に合成した1本と同じ時刻から始まる。"""
    composer = _composer(_matrix(1), series=_series([0.0, 4.0, 8.0]))
    first = composer.compose("prepare", None, 0.0, +1)

    with caplog.at_level(logging.INFO, logger="ridecompass.graph"):
        again = composer.compose("prepare", None, 0.0, +1)
        binned = composer.compose("outbound", None, 0.0, +1, duration_hours=2.0)

    assert again is first
    assert binned.cost_bins_lazy[0].tolist() == first.cost_lazy.tolist()
    assert "mode=reused" in caplog.messages[0]
    assert "reused_bins=1" in caplog.messages[1]


def test_a_tree_without_a_clock_reads_the_wind_at_each_segment_s_own_passage():
    """目的地から遡る木は時刻ビンを使えず、区間ごとの通過時刻で1本に合成する。"""
    composer = _composer(_matrix(2), series=_series([0.0, 8.0]))
    passage = np.array([0.0, 1.0])

    leg = composer.compose("inbound", None, 3.0, -1, passage_hours=passage)

    assert leg.travel_seconds_full[1] > leg.travel_seconds_full[0]
    assert (len(leg.cost_bins_lazy), leg.bin_start_hours) == (1, ())
    assert leg.passage_hours is passage


@pytest.mark.parametrize("wind_weight", [0.0, 1.0])
def test_values_recomposed_for_the_rows_on_the_route_match_the_composition_used_by_the_search(wind_axis, wind_weight):
    """表示は経路上の行だけをその時刻で合成し直す。探索が使った合成と同じ値になる（探索コストと表示の一致）。"""
    matrix = _matrix(
        3, bearing=[NORTH, SOUTH, 90.0], axes={"axis_a": [10.0, 50.0, 90.0], WIND_AXIS: np.nan},
        materials={"material_a": [1.0, 2.0, 3.0]},
    )
    weights = {"axis_a": 1.0, WIND_AXIS: wind_weight}
    composer = _composer(matrix, weights=weights, penalty=0.5, series=_series([0.0, 6.0]))
    leg = composer.compose("leg", None, 0.0, +1, passage_hours=np.full(3, 1.0))

    values = composer.values_at_rows(np.array([2, 0]), np.array([1.0, 1.0]))

    assert values.difficulty_array.tolist() == leg.difficulty_array[[2, 0]].tolist()
    assert values.weight_sums.tolist() == leg.weight_sums[[2, 0]].tolist()
    assert {a: v.tolist() for a, v in values.axis_arrays.items()} == {
        a: v[[2, 0]].tolist() for a, v in leg.axis_arrays.items()}
    assert {m: v.tolist() for m, v in values.material_arrays.items()} == {
        m: v[[2, 0]].tolist() for m, v in leg.material_arrays.items()}
    assert values.axis_contributions_at(0) == leg.axis_contributions_at(2)


# --- 所要時間の欠け・区間の風 ---------------------------------------------------


def test_the_share_of_distance_timed_without_gradient_or_stop_data():
    composer = _composer(_matrix(
        3, distance=[1000.0, 3000.0, 6000.0], gradient=[np.nan, 0.0, 0.0],
        materials={STOP_DENSITY["signal"]: [0.0, np.nan, 0.0]},
    ))

    assert composer.missing_travel_data_share(np.array([0, 1, 2])) == 0.4
    assert composer.missing_travel_data_share(np.array([2])) == 0.0
    assert composer.missing_travel_data_share(np.array([], dtype=np.int64)) is None


def test_the_wind_of_a_segment_is_the_forecast_at_its_passage():
    composer = _composer(_matrix(3), series=_series([1.04, 2.0, 3.0], from_deg=90.0))

    winds = composer.winds_at([0, 1, 2], [0.2, 1.0, 9.0], [False, True, False])

    assert [(w.speed_ms, w.direction_deg, w.forecast_at) for w in winds] == [
        (1.0, 90.0, "2026-10-03T09:00"), (2.0, 90.0, "2026-10-03T10:00"), (3.0, 90.0, "2026-10-03T11:00")]
    # 時刻ビンの範囲の先・予報の期間の先は、最後に追った予報を延ばして使っている。
    assert [w.extended for w in winds] == [False, True, True]


def test_a_segment_without_a_passage_shows_the_wind_at_departure():
    composer = _composer(_matrix(2), weather=_weather(3.04, from_deg=271.06))

    winds = composer.winds_at([0, 1], [None, 0.5], [False, False])

    assert winds[0] == leg_costs.SegmentWind(speed_ms=3.0, direction_deg=271.1)
    # 時別の予報が無いと、通過時刻の風は引けない。
    assert winds[1] is None


def test_a_segment_has_no_wind_when_no_wind_was_available():
    assert _composer(_matrix(1)).winds_at([0], [None], [False]) == [None]
