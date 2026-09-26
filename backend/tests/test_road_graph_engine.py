"""`services/road_graph_engine.py`——探索エンジンの中の、配列だけで確かめられる計算。

対象は、エンジンが自分で決める計算のうち、入力を配列や値で直接与えられるもの。

- レグごとのコスト配列の合成（`_LegCostComposer`: 時刻ビンの本数・代表ビン・除外区間のinf化・
  所要時間の下地・動的材料の扱い）
- 表示値の部品（ジオメトリの連結・標高の集約と逆回りの代数変換・候補の難易度の比較）
- 探索の部品（起点・終点の状態の引き方・繋ぎ目の候補・同点グループの試行順・bbox）

ここでは見ないもの:

- 道路網から経路を作る一連の振る舞い（スナップ・周回・目的地・経由地・候補の選び方・区間の表示）
  → `test_route_generation_behavior.py`（公開の入口`RouteGenerator`から、小さな道路網で確かめる）。
  エンジンの途中状態（`_RoadGraphContext`等）を手で組むテストはここに置かない——道路網の持ち方や
  組み立てを作り替えるたびに足場ごと書き直すことになり、振る舞いは何も守らない。
- 探索カーネル（`domain/routing.py`）・評価軸（`domain/evaluation.py`）・走行モデル
  （`domain/cycling_speed.py`）・風（`domain/wind.py`）・0次フィルタ（`domain/hard_filters.py`）
  → それぞれの持ち主のテストが持つ。

**合成器が呼ぶ相手のうち、走行モデルと動的軸の評価は架空の実装へ差し替える**（`composer_world`）。
軸の合成と風の分解は本物を通す——コストが「所要時間×割増の倍率」になることは、合成の本物の性質だから。
実在の軸id・材料idには依らない（`axis_a`・`mat_a`のような性質だけの名前を使う）。
ただしこのファイルが組み立てて渡し、読むデータ型（`StaticEdgeScoreMatrix`・探索構造・
`RouteCandidate`等）は本物で作る——代役にしても何も切り離せず、本物が変わったときに黙ってずれるだけになる。
"""

import math
from datetime import datetime, timedelta

import numpy as np
import pytest

from app.domain.attributes import ElevationAttribute
from app.domain.evaluation import StaticEdgeScoreMatrix
from app.domain.graph import LeanEdge
from app.domain.route import Coordinates, RouteCandidate, RouteSegmentDetail
from app.domain.routing import (
    CsrGraphStructure,
    NodeJunction,
    SearchGraphStatics,
    TurnExpandedStructure,
    TurnExpandedTree,
)
from app.domain.wind import WindForecastSeries
from app.services import road_graph_engine as engine


# --------------------------------------------------------------------------------------
# 架空の世界（本物の型を、そのテストが読む値だけ埋めて作る）
# --------------------------------------------------------------------------------------


def coords(latitude, longitude):
    return Coordinates(latitude=latitude, longitude=longitude)


def lean_edge(edge_id, from_node_id="n0", to_node_id="n1", *, distance_m=100.0, geometry=None):
    """探索用グラフの区間と同じく、`geometry`を省くと空のプレースホルダになる。DBの区間の番号は
    ここを通るテストが読まないため、どの区間にも同じ値を入れる。"""
    return LeanEdge(
        edge_id=edge_id, from_node_id=from_node_id, to_node_id=to_node_id,
        geometry=[] if geometry is None else geometry, distance_m=distance_m,
        osm_way_id=1, segment_index=0, forward=True,
    )


def elevation(edge_id, **fields):
    return ElevationAttribute(edge_id=edge_id, **fields)


def turn_tree(state_count, *, node_cost, node_length_m, node_seconds, node_best_state):
    """一対全木。エンジンが読むのはNode側だけで、状態側を辿る経路の復元は各テストが差し替えるため、
    状態側はどの状態にも届いていない値（inf・NaN・-1）で埋める。"""
    predecessor = np.full(state_count, -1, dtype=np.int64)
    return TurnExpandedTree(
        state_cost=np.full(state_count, np.inf), predecessor=predecessor,
        state_length_m=np.full(state_count, np.nan), state_seconds=np.full(state_count, np.nan),
        node_cost=np.asarray(node_cost, dtype=float), node_best_state=np.asarray(node_best_state, dtype=np.int64),
        node_length_m=np.asarray(node_length_m, dtype=float), node_seconds=np.asarray(node_seconds, dtype=float),
        predecessor_list=predecessor.tolist(),
    )


def wind_series(hours=24, speed_ms=3.0, direction_deg=5.0):
    """時別の風の予報（2026-09-22 0時から）。`speed_ms`は全時刻で同じ値か、時刻ごとの並び。"""
    start = datetime(2026, 9, 22, 0, 0)
    return WindForecastSeries(
        times=[start + timedelta(hours=h) for h in range(hours)],
        speed_ms=np.broadcast_to(np.asarray(speed_ms, dtype=float), (hours,)).copy(),
        direction_deg=np.full(hours, direction_deg),
    )


def segment_detail(difficulty, distance_km):
    return RouteSegmentDetail(
        start_latitude=35.0, start_longitude=139.0, end_latitude=35.0, end_longitude=139.0,
        cumulative_distance_km=0.0, distance_km=distance_km, difficulty=difficulty,
    )


def route_candidate(name, segments=()):
    """`name`は候補を見分けるためだけのid。"""
    return RouteCandidate(id=name, direction_label=name, distance_km=1.0, geometry={}, segments=list(segments))


# --------------------------------------------------------------------------------------
# 代表ビンの選び方
# --------------------------------------------------------------------------------------


def test_representative_bin_is_the_bin_containing_the_middle_of_the_leg():
    """表示と、時刻ラベルを持てない探索が読むビン。中間地点がどのビンに入るかで決まる。

    組み合わせは`_bin_count`が作れるものに限る（見込み3時間なら3本、5時間なら上限の4本）。
    """
    assert engine._representative_bin(4, 5.0) == 2
    assert engine._representative_bin(3, 3.0) == 1


def test_representative_bin_is_zero_when_the_leg_is_a_single_bin():
    """風の系列が無いレグは1本のスナップショット。見込み時間があっても代表は唯一のビン。"""
    assert engine._representative_bin(1, 5.0) == 0


def test_representative_bin_clamps_to_the_last_bin():
    """ビンは上限4本で頭打ちになる。12時間のレグの中間は6本目に当たるが、存在しない。"""
    assert engine._representative_bin(4, 12.0) == 3


# --------------------------------------------------------------------------------------
# ジオメトリの連結と境界点
# --------------------------------------------------------------------------------------


def test_concat_edge_geometries_drops_the_shared_boundary_point():
    """隣接Edgeの境界点を二重に持たせない（線が同じ点で折り返して見える）。"""
    edges = [
        lean_edge("e1", geometry=[[35.0, 139.0], [35.1, 139.1]]),
        lean_edge("e2", geometry=[[35.1, 139.1], [35.2, 139.2]]),
    ]
    geometry, offsets = engine._concat_edge_geometries(edges)

    assert geometry["type"] == "LineString"
    assert geometry["coordinates"] == [[139.0, 35.0], [139.1, 35.1], [139.2, 35.2]]
    assert len(offsets) == len(edges) + 1


def test_concat_edge_geometries_offsets_slice_back_to_each_edge():
    """境界の位置は座標列からは復元できない。offsetsが各Edgeの形状を切り出せること。"""
    edges = [
        lean_edge("e1", geometry=[[35.0, 139.0], [35.1, 139.1], [35.2, 139.2]]),
        lean_edge("e2", geometry=[[35.2, 139.2], [35.3, 139.3]]),
    ]
    geometry, offsets = engine._concat_edge_geometries(edges)
    coordinates = geometry["coordinates"]

    assert coordinates[offsets[0]:offsets[1] + 1] == [[139.0, 35.0], [139.1, 35.1], [139.2, 35.2]]
    assert coordinates[offsets[1]:offsets[2] + 1] == [[139.2, 35.2], [139.3, 35.3]]


def test_concat_edge_geometries_keeps_both_points_when_edges_do_not_touch():
    edges = [
        lean_edge("e1", geometry=[[35.0, 139.0]]),
        lean_edge("e2", geometry=[[36.0, 140.0]]),
    ]
    geometry, _ = engine._concat_edge_geometries(edges)
    assert geometry["coordinates"] == [[139.0, 35.0], [140.0, 36.0]]


def test_concat_edge_geometries_of_no_edges_is_an_empty_line():
    geometry, offsets = engine._concat_edge_geometries([])
    assert geometry["coordinates"] == []
    assert offsets == [0]


# --------------------------------------------------------------------------------------
# 標高の集約と逆走時の代数変換
# --------------------------------------------------------------------------------------


def test_aggregate_elevation_collects_only_present_values(monkeypatch):
    """欠損は集計の母集団から外す（0として数えると獲得標高が実態より小さく出る）。"""
    seen = {}
    monkeypatch.setattr(engine, "sum_or_none", lambda values: seen.setdefault("sum", list(values)))
    monkeypatch.setattr(engine, "min_or_none", lambda values: seen.setdefault("min", list(values)))
    monkeypatch.setattr(engine, "max_or_none", lambda values: seen.setdefault("max", list(values)))

    edges = [lean_edge("e1"), lean_edge("e2"), lean_edge("e3"), lean_edge("e4")]
    attributes = {
        "e1": elevation("e1", start_elevation_m=10.0, end_elevation_m=20.0, elevation_gain_m=10.0),
        "e2": elevation("e2", start_elevation_m=None, end_elevation_m=5.0, elevation_gain_m=None),
        "e4": elevation("e4", start_elevation_m=30.0, end_elevation_m=None, elevation_gain_m=2.0),
    }

    result = engine._aggregate_elevation(edges, attributes)

    assert seen["sum"] == [10.0, 2.0]
    assert seen["min"] == [10.0, 20.0, 5.0, 30.0]
    assert set(result) == {"elevation_gain_m", "min_elevation_m", "max_elevation_m"}


def test_reverse_elevation_attribute_swaps_climb_and_descent():
    forward = elevation(
        "fwd", start_elevation_m=10.0, end_elevation_m=50.0,
        elevation_gain_m=40.0, elevation_loss_m=0.0,
        average_grade=4.0, max_grade=9.0, min_grade=-1.0,
    )
    reverse = engine._reverse_elevation_attribute(forward, "rev")

    assert reverse.edge_id == "rev"
    assert (reverse.start_elevation_m, reverse.end_elevation_m) == (50.0, 10.0)
    assert (reverse.elevation_gain_m, reverse.elevation_loss_m) == (0.0, 40.0)
    assert reverse.average_grade == -4.0
    assert reverse.max_grade == 1.0
    assert reverse.min_grade == -9.0


def test_reverse_elevation_attribute_keeps_missing_grades_missing():
    forward = elevation("fwd", average_grade=None, max_grade=None, min_grade=None)
    reverse = engine._reverse_elevation_attribute(forward, "rev")
    assert reverse.average_grade is None
    assert reverse.max_grade is None
    assert reverse.min_grade is None


def test_reverse_elevation_by_edge_pairs_the_path_in_reverse_order():
    """逆方向Edgeの並びは順方向の逆。対応がずれると別の坂の値が付く。"""
    forward_edges = [lean_edge("f1"), lean_edge("f2")]
    reverse_edges = [lean_edge("r2"), lean_edge("r1")]
    attributes = {"f2": elevation("f2", start_elevation_m=1.0, end_elevation_m=9.0)}

    result = engine._reverse_elevation_by_edge(forward_edges, reverse_edges, attributes)

    assert set(result) == {"r2"}
    assert result["r2"].start_elevation_m == 9.0


# --------------------------------------------------------------------------------------
# レグ番号の振り直しと、順方向／逆回りの採否
# --------------------------------------------------------------------------------------


def test_reverse_leg_assignment_renumbers_as_well_as_reverses():
    """並びだけ反転すると、走り始めを帰着時刻の風で評価することになる。"""
    assert engine._reverse_leg_assignment([0, 0, 0, 1, 1]) == [0, 0, 1, 1, 1]
    assert engine._reverse_leg_assignment([0, 1, 2]) == [0, 1, 2]
    assert engine._reverse_leg_assignment([]) == []


def test_pick_better_candidate_prefers_the_lower_difficulty(monkeypatch):
    monkeypatch.setattr(
        engine, "distance_weighted_difficulty", lambda pairs: pairs[0][0] if pairs else None
    )
    forward = route_candidate("forward", segments=[segment_detail(5.0, 1.0)])
    reverse = route_candidate("reverse", segments=[segment_detail(3.0, 1.0)])

    assert engine._pick_better_candidate(forward, reverse) is reverse
    assert engine._pick_better_candidate(reverse, forward) is reverse


def test_pick_better_candidate_falls_back_to_forward_when_reverse_cannot_be_scored(monkeypatch):
    """比較不能を「逆回りの方が良い」と読まない（安全側）。"""
    monkeypatch.setattr(
        engine, "distance_weighted_difficulty", lambda pairs: pairs[0][0] if pairs else None
    )
    forward = route_candidate("forward", segments=[segment_detail(5.0, 1.0)])
    reverse = route_candidate("reverse", segments=[])

    assert engine._pick_better_candidate(forward, reverse) is forward


def test_pick_better_candidate_takes_reverse_when_only_forward_is_unscorable(monkeypatch):
    monkeypatch.setattr(
        engine, "distance_weighted_difficulty", lambda pairs: pairs[0][0] if pairs else None
    )
    forward = route_candidate("forward", segments=[])
    reverse = route_candidate("reverse", segments=[segment_detail(7.0, 1.0)])

    assert engine._pick_better_candidate(forward, reverse) is reverse


def test_route_composite_difficulty_feeds_difficulty_and_distance_pairs(monkeypatch):
    captured = {}

    def record(pairs):
        captured["pairs"] = list(pairs)
        return 1.5

    monkeypatch.setattr(engine, "distance_weighted_difficulty", record)
    candidate = route_candidate("candidate", segments=[segment_detail(2.0, 0.5), segment_detail(None, 0.3)])

    assert engine._route_composite_difficulty(candidate) == 1.5
    assert captured["pairs"] == [(2.0, 0.5), (None, 0.3)]


def test_route_composite_difficulty_is_none_without_segments():
    assert engine._route_composite_difficulty(route_candidate("candidate")) is None


# --------------------------------------------------------------------------------------
# 材料値の読み出し
# --------------------------------------------------------------------------------------


def test_material_value_at_distinguishes_absent_from_missing_from_present():
    leg = engine.LegCostArrays(
        cost_lazy=np.zeros(2), difficulty_array=np.zeros(2),
        axis_arrays={}, weight_sums=np.zeros(2), weights={},
        axis_raw_arrays={}, material_arrays={"mat_a": np.array([1.5, np.nan])},
        categorical_material_arrays={}, travel_seconds_full=np.zeros(2),
        travel_seconds_lazy=np.zeros(2), cost_bins_lazy=np.zeros((1, 2)),
        travel_bins_lazy=np.zeros((1, 2)), bin_seconds=np.inf,
    )

    assert engine._material_value_at(leg, "mat_a", 0) == 1.5
    assert engine._material_value_at(leg, "mat_a", 1) is None
    assert engine._material_value_at(leg, "mat_absent", 0) is None


# --------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------
# CSR／遷移構造からの索引
# --------------------------------------------------------------------------------------


def test_origin_states_are_the_edges_leaving_the_node():
    """CSRのエントリ位置ではなく、そのエントリが指すEdge indexを返す。"""
    csr = CsrGraphStructure(
        node_count=3,
        indptr=np.array([0, 2, 3, 3], dtype=np.int32),
        indices=np.array([1, 2, 0], dtype=np.int32),
        entry_edge_index=np.array([2, 0, 1], dtype=np.int32),
    )
    states = engine._origin_states(SearchGraphStatics(csr=csr, edge_length_m=np.zeros(3)), 0)

    assert states.tolist() == [2, 0]
    assert states.dtype == np.int64


def test_destination_states_are_the_edges_entering_the_node():
    structure = TurnExpandedStructure(
        state_count=3, indptr=np.zeros(4, dtype=np.int64), target_state=np.array([], dtype=np.int64),
        turn_seconds=np.array([]), edge_from=np.array([0, 1, 2]), edge_to=np.array([1, 2, 1]),
    )
    assert engine._destination_states(structure, 1).tolist() == [0, 2]


# --------------------------------------------------------------------------------------
# 目的地そのものを経由Nodeとする候補
# --------------------------------------------------------------------------------------


def make_junction(count):
    return NodeJunction(
        cost=np.full(count, np.inf), length_m=np.zeros(count), seconds=np.zeros(count),
        forward_state=np.full(count, -1, dtype=np.int64),
        backward_state=np.full(count, -1, dtype=np.int64),
    )


def test_add_terminal_candidate_copies_every_field_from_the_forward_tree():
    """1つでも繋ぎ目側の値が残ると、difficultyの逆算が別経路のコストと秒で行われる。"""
    junction = make_junction(2)
    junction.cost[1] = 999.0
    junction.length_m[1] = 111.0
    junction.seconds[1] = 222.0
    junction.backward_state[1] = 42
    forward = turn_tree(
        4, node_cost=[0.0, 5.0], node_length_m=[0.0, 60.0], node_seconds=[0.0, 4.0], node_best_state=[-1, 3],
    )

    engine._add_terminal_candidate(junction, forward, 1)

    assert junction.cost[1] == 5.0
    assert junction.length_m[1] == 60.0
    assert junction.seconds[1] == 4.0
    assert junction.forward_state[1] == 3
    assert junction.backward_state[1] == -1


def test_add_terminal_candidate_does_nothing_when_the_forward_tree_never_arrived():
    junction = make_junction(2)
    forward = turn_tree(
        4, node_cost=[0.0, np.inf], node_length_m=[0.0, np.nan], node_seconds=[0.0, np.nan], node_best_state=[-1, -1],
    )

    engine._add_terminal_candidate(junction, forward, 1)

    assert not np.isfinite(junction.cost[1])
    assert junction.forward_state[1] == -1


# --------------------------------------------------------------------------------------
# 同点グループ内の試行順（方位の散らし）
# --------------------------------------------------------------------------------------


def test_order_by_bearing_spread_uses_ring_centre_closeness_before_anything_is_selected():
    order = engine._order_by_bearing_spread(
        [10, 11, 12], [], {10: 0.0, 11: 90.0, 12: 180.0}, {10: 500.0, 11: 10.0, 12: 100.0}
    )
    assert order == [11, 12, 10]


def test_order_by_bearing_spread_puts_the_most_distant_bearing_first():
    """同点候補が同じ方角に並ぶと、周回一覧が「似た向き」ばかりになる。"""
    order = engine._order_by_bearing_spread(
        [10, 11], [99], {10: 20.0, 11: 180.0, 99: 0.0}, {10: 0.0, 11: 0.0}
    )
    assert order == [11, 10]


def test_order_by_bearing_spread_measures_bearings_on_the_circle():
    """方位の差は360度を跨ぐ。単純な引き算だと350度と10度が「遠い」と誤判定される。"""
    order = engine._order_by_bearing_spread(
        [10, 11], [99], {10: 10.0, 11: 90.0, 99: 350.0}, {10: 0.0, 11: 0.0}
    )
    assert order == [11, 10]


def test_order_by_bearing_spread_breaks_ties_by_node_index():
    order = engine._order_by_bearing_spread(
        [12, 11], [99], {11: 90.0, 12: 90.0, 99: 0.0}, {11: 5.0, 12: 5.0}
    )
    assert order == [11, 12]


# --------------------------------------------------------------------------------------
# レグごとのコスト配列の合成（_LegCostComposer）
# --------------------------------------------------------------------------------------


AXIS_STATIC = "axis_static"
AXIS_WIND = "axis_wind"
MAT_CRR = "mat_crr"
MAT_STOP_A = "mat_stop_a"
MAT_STOP_B = "mat_stop_b"
MAT_DYN = "mat_dyn"
MAT_DYN_EMPTY = "mat_dyn_empty"


class ComposerWorld:
    """合成が呼ぶ相手（走行モデル・動的軸の評価）の代役。渡された値を記録する。"""

    def __init__(self):
        self.passages = []
        self.crr_inputs = []


@pytest.fixture
def composer_world(monkeypatch):
    world = ComposerWorld()

    def fake_evaluate(static_axis_scores, context):
        world.passages.append(None if context.passage_hours is None else np.asarray(context.passage_hours).copy())
        count = len(context.bearing_deg)
        marker = -1.0 if context.passage_hours is None else float(np.asarray(context.passage_hours)[0])
        resolved = dict(static_axis_scores)
        resolved[AXIS_WIND] = np.full(count, marker)
        resolved[MAT_DYN] = np.full(count, 7.0)
        resolved[MAT_DYN_EMPTY] = np.full(count, np.nan)
        return resolved

    def fake_crr(values, count):
        world.crr_inputs.append(values)
        return np.full(count, 0.005)

    class FakeSpeedModel:
        """10mにつき1秒、向かい風1m/sにつき1秒を足す走行モデル（値を手で追えるように）。"""

        def __init__(self, profile, grade, crr):
            pass

        def travel_seconds(self, distance_m, headwind_ms, crosswind_ms=None):
            return np.asarray(distance_m, dtype=float) / 10.0 + np.asarray(headwind_ms, dtype=float)

    monkeypatch.setattr(engine, "AXIS_DEFINITIONS", {})
    monkeypatch.setattr(engine, "dynamic_axis_topological_order", lambda definitions: [AXIS_WIND])
    monkeypatch.setattr(engine, "REQUEST_DYNAMIC_MATERIAL_IDS", (MAT_DYN, MAT_DYN_EMPTY))
    monkeypatch.setattr(engine, "evaluate_dynamic_axis_arrays", fake_evaluate)
    monkeypatch.setattr(engine, "crr_for_surface", fake_crr)
    monkeypatch.setattr(engine, "SegmentSpeedModel", FakeSpeedModel)
    monkeypatch.setattr(engine, "ROLLING_RESISTANCE_MATERIAL_ID", MAT_CRR)
    monkeypatch.setattr(engine, "POI_COUNT_KINDS", ("kind_a", "kind_b"))
    monkeypatch.setattr(engine, "stop_count_material_ids", lambda: [MAT_STOP_A, MAT_STOP_B])
    monkeypatch.setattr(engine, "stop_seconds", lambda kind: {"kind_a": 10.0, "kind_b": 2.0}[kind])
    monkeypatch.setattr(engine, "kmh_to_ms", lambda kmh: kmh / 3.6)
    return world


def make_score_matrix(count=3, **overrides):
    defaults = dict(
        distance_m=np.full(count, 1000.0),
        bearing_deg=np.zeros(count),
        gradient_percent=np.zeros(count),
        mid_lat=np.zeros(count),
        mid_lon=np.zeros(count),
        hard_filter_flags={},
        axis_ids=[AXIS_STATIC, AXIS_WIND],
        axis_scores=np.column_stack([np.full(count, 1.0), np.full(count, 0.0)]),
        raw_axis_ids=[AXIS_STATIC],
        axis_raw_values=np.arange(count, dtype=float).reshape(count, 1),
        material_ids=[MAT_STOP_A, MAT_CRR],
        material_values=np.column_stack([np.full(count, 2.0), np.full(count, 0.004)]),
        categorical_material_ids=["cat_a"],
        categorical_material_values=np.array([["paved"]] * count, dtype=object),
    )
    defaults.update(overrides)
    return StaticEdgeScoreMatrix(**defaults)


def make_composer(score_matrix=None, *, weights=None, excluded=None, lazy_row_index=None,
                  wind_series=None, penalty=1.0, speed_kmh=20.0, **kwargs):
    score_matrix = score_matrix if score_matrix is not None else make_score_matrix()
    count = len(score_matrix.distance_m)
    return engine._LegCostComposer(
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


def test_composer_is_time_varying_only_when_an_hourly_wind_series_exists(composer_world):
    assert make_composer().time_varying is False
    assert make_composer(wind_series=wind_series()).time_varying is True


def test_to_full_row_order_marks_edges_absent_from_the_search_graph(composer_world):
    """並行Edgeの採られなかった方は探索に載らない。別Edgeの値で埋めると通過時刻がずれる。"""
    composer = make_composer(make_score_matrix(count=3), lazy_row_index=[2, 0])

    restored = composer.to_full_row_order(np.array([10.0, 20.0]))

    assert restored[2] == 10.0
    assert restored[0] == 20.0
    assert math.isnan(restored[1])


def test_bin_count_is_one_without_a_duration_or_without_wind(composer_world):
    with_wind = make_composer(wind_series=wind_series())
    assert with_wind._bin_count(None) == 1
    assert make_composer()._bin_count(5.0) == 1


def test_bin_count_covers_the_duration_up_to_the_ceiling(composer_world):
    """ビン1本ごとにbbox全体の合成が1回走るため、長いレグでも上限で頭打ちにする。"""
    composer = make_composer(wind_series=wind_series())

    assert composer._bin_count(0.1) == 1
    assert composer._bin_count(engine.TIME_BIN_HOURS * 2 + 0.01) == 3
    assert composer._bin_count(engine.TIME_BIN_HOURS * 100) == engine.MAX_TIME_BINS


def test_compose_without_wind_series_makes_one_snapshot_shared_by_every_leg(composer_world):
    """風の系列が無ければ時刻で変えようがない。レグごとに合成し直す理由が無い。"""
    composer = make_composer()

    outbound = composer.compose("outbound", coords(35.0, 139.0), 0.0, +1, duration_hours=3.0)
    inbound = composer.compose("inbound", coords(35.0, 139.0), 3.0, -1, duration_hours=3.0)

    assert inbound is outbound
    assert outbound.cost_bins_lazy.shape[0] == 1
    assert outbound.bin_seconds == np.inf
    assert composer_world.passages == [None]


def test_compose_splits_a_long_leg_into_hourly_bins(composer_world):
    composer = make_composer(wind_series=wind_series())

    leg = composer.compose("outbound", coords(35.0, 139.0), 0.0, +1, duration_hours=3.0)

    assert leg.cost_bins_lazy.shape == (3, 3)
    assert leg.travel_bins_lazy.shape == (3, 3)
    assert leg.bin_seconds == engine.TIME_BIN_HOURS * 3600.0
    assert [float(p[0]) for p in composer_world.passages] == [0.0, 1.0, 2.0]


def test_compose_of_an_inbound_leg_counts_time_from_the_start_of_that_leg(composer_world):
    """`direction=-1`の`offset_hours`はレグの終了時刻。開始時刻へ直さないと風が2時間ずれる。"""
    composer = make_composer(wind_series=wind_series())

    composer.compose("inbound", coords(35.0, 139.0), 5.0, -1, duration_hours=2.0)

    assert [float(p[0]) for p in composer_world.passages] == [3.0, 4.0]


def test_compose_representative_arrays_come_from_the_middle_bin(composer_world):
    """表示と、時刻ラベルを持てない探索が読む値。端のビンだと実際に走る時刻と合わない。"""
    composer = make_composer(wind_series=wind_series())

    leg = composer.compose("outbound", coords(35.0, 139.0), 0.0, +1, duration_hours=3.0)

    assert leg.cost_lazy.tolist() == leg.cost_bins_lazy[1].tolist()


def test_compose_reuses_a_leg_composed_for_the_same_start_and_bins(composer_world):
    composer = make_composer(wind_series=wind_series())

    first = composer.compose("outbound", coords(35.0, 139.0), 1.0, +1, duration_hours=2.0)
    again = composer.compose("leg1", coords(36.0, 140.0), 1.0, +1, duration_hours=2.0)

    assert again is first
    assert len(composer_world.passages) == 2


def test_compose_takes_a_bin_from_a_single_bin_leg_of_the_same_time(composer_world):
    """周回の往路は、見込み時間なしで先に合成した1本と同じ時刻から始まる。ビン1本ぶんの合成は
    範囲の区間の全体を走るため、同じ時刻のビンを2度作らない。"""
    composer = make_composer(wind_series=wind_series())

    single = composer.compose("outbound", coords(35.0, 139.0), 0.0, +1)
    binned = composer.compose("outbound", coords(35.0, 139.0), 0.0, +1, duration_hours=2.0)

    assert [float(p[0]) for p in composer_world.passages] == [0.0, 1.0]
    assert binned.cost_bins_lazy[0].tolist() == single.cost_lazy.tolist()
    assert binned.cost_bins_lazy[1].tolist() != single.cost_lazy.tolist()


def test_compose_with_measured_passage_hours_is_a_single_bin(composer_world):
    """後ろ向き木は時刻ラベルを持てない。前向き木の実到達時間を区間ごとに渡す。"""
    composer = make_composer(wind_series=wind_series())
    passage = np.array([0.5, 1.5, 2.5])

    leg = composer.compose("inbound", coords(35.0, 139.0), 4.0, -1, passage_hours=passage)

    assert leg.cost_bins_lazy.shape[0] == 1
    assert leg.bin_seconds == np.inf
    assert composer_world.passages[-1].tolist() == [0.5, 1.5, 2.5]


def test_compose_keeps_composing_by_time_even_without_an_anchor(composer_world):
    """風は軸である前に走行モデルの入力。系列があれば基準点の有無に関わらず時刻で引く。"""
    composer = make_composer(wind_series=wind_series())

    leg = composer.compose("outbound", None, 0.0, +1, duration_hours=3.0)

    assert leg.cost_bins_lazy.shape[0] == 3


def test_composed_costs_are_infinite_where_the_zeroth_filter_excludes(composer_world):
    """探索から見た通行可否はコスト配列だけが表す。有限のまま残すと除外区間を通る。"""
    composer = make_composer(make_score_matrix(count=3), excluded=[False, True, False])

    leg = composer.compose("outbound", coords(35.0, 139.0), 0.0, +1)

    assert np.isinf(leg.cost_lazy[1])
    assert np.isinf(leg.travel_seconds_full[1])
    assert np.isfinite(leg.cost_lazy[0])


def test_composed_materials_drop_dynamic_ones_with_no_data_at_all(composer_world):
    """全行NaNの動的材料をキーごと持つと、表示が「値0」と「データ無し」を取り違える。"""
    composer = make_composer()

    leg = composer.compose("outbound", coords(35.0, 139.0), 0.0, +1)

    assert MAT_DYN in leg.material_arrays
    assert MAT_DYN_EMPTY not in leg.material_arrays
    assert MAT_STOP_A in leg.material_arrays


def test_travel_time_adds_the_stop_waits_of_the_materials_that_exist(composer_world):
    """停止要因の材料が引けないと、全区間の待ちが無言で0秒になる。"""
    matrix = make_score_matrix(
        count=2,
        distance_m=np.array([1000.0, 2000.0]),
        material_ids=[MAT_STOP_A, MAT_CRR],
        material_values=np.column_stack([np.array([2.0, np.nan]), np.array([0.004, 0.004])]),
        axis_raw_values=np.zeros((2, 1)),
        categorical_material_values=np.array([["paved"], ["paved"]], dtype=object),
    )
    composer = make_composer(matrix)

    leg = composer.compose("outbound", coords(35.0, 139.0), 0.0, +1)

    # 100秒の走行 + 2件/km × 1km × 10秒 = 120秒。欠損は0件として扱う（NaNを伝播させない）。
    assert leg.travel_seconds_full.tolist() == [120.0, 200.0]


def test_travel_time_reads_rolling_resistance_from_the_material_arrays(composer_world):
    """転がり抵抗の材料が引けないと、路面の違いが速度に反映されないまま所要時間が出る。"""
    composer = make_composer()
    composer.compose("outbound", coords(35.0, 139.0), 0.0, +1)

    assert composer_world.crr_inputs[-1].tolist() == [0.004, 0.004, 0.004]


def hourly_wind_composer(wind_weight):
    """時刻ごとに風が強まる世界。出発は8時で、h時の風は向かい風h m/s（方位0・風向0）。区間は1km・2kmで、
    停止の待ちは1kmあたり20秒、時刻で変わらない軸の得点は40・80。走行時間は10mにつき1秒＋向かい風1m/sにつき1秒。"""
    matrix = make_score_matrix(
        count=2,
        distance_m=np.array([1000.0, 2000.0]),
        axis_scores=np.column_stack([np.array([40.0, 80.0]), np.full(2, np.nan)]),
        axis_raw_values=np.zeros((2, 1)),
        material_values=np.column_stack([np.full(2, 2.0), np.full(2, 0.004)]),
        categorical_material_values=np.array([["paved"], ["paved"]], dtype=object),
    )
    return make_composer(
        matrix, weights={AXIS_STATIC: 1.0, AXIS_WIND: wind_weight}, penalty=0.5,
        wind_series=wind_series(speed_ms=np.arange(24.0), direction_deg=0.0),
    )


def test_each_bin_costs_its_own_travel_time_times_the_fixed_penalty(composer_world):
    """時刻で変わる軸の重みが0なら、割増の倍率は時刻に依らない。風は走行時間を通してだけビンごとに効く。"""
    composer = hourly_wind_composer(wind_weight=0.0)

    leg = composer.compose("outbound", coords(35.0, 139.0), 0.0, +1, duration_hours=2.0)

    # 8時: 100+8+20・200+8+40秒、9時: 向かい風が1m/s強い
    assert leg.travel_bins_lazy.tolist() == [[128.0, 248.0], [129.0, 249.0]]
    # 倍率は 1 + 0.5 × 得点/100
    assert leg.cost_bins_lazy.ravel().tolist() == pytest.approx([128.0 * 1.2, 248.0 * 1.4, 129.0 * 1.2, 249.0 * 1.4])
    assert leg.difficulty_array.tolist() == [40.0, 80.0]


def test_a_weighted_time_varying_axis_enters_each_bin_at_its_own_time(composer_world):
    """時刻で変わる軸に重みがあれば、各ビンの合成にそのビンの時刻の値が入る（時刻で変わらない側には入らない）。"""
    composer = hourly_wind_composer(wind_weight=1.0)

    leg = composer.compose("outbound", coords(35.0, 139.0), 0.0, +1, duration_hours=2.0)

    # 動的軸の代役はビンの開始時刻（出発からの経過）を得点にする: 合成は (40+0)/2・(80+0)/2、次のビンは (40+1)/2・(80+1)/2
    assert leg.cost_bins_lazy.ravel().tolist() == pytest.approx(
        [128.0 * 1.1, 248.0 * 1.2, 129.0 * 1.1025, 249.0 * 1.2025]
    )
    rows = composer.values_at_rows(np.array([1]), np.array([1.0]))
    assert rows.difficulty_array.tolist() == [40.5]
