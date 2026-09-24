"""`services/road_graph_engine.py`——Road Graph探索エンジンが単独で決めていること。

対象は、このファイルが自分で決める次のもの。

- レグごとのコスト配列の合成（時刻ビンの本数・代表ビン・キャッシュ鍵・除外Edgeのinf化）
- 探索用グラフ／統計／遷移構造のキャッシュ鍵と不整合時の作り直し
- 折返し点・経由Nodeの選定（リングの上下限・難易度の逆算・並べ替え・間引き）
- クライアントが送ってきたEdge列の検証と、レグ番号の割り当て
- 逆回り候補の導出（逆方向Edge・標高の代数変換・レグ番号の振り直し）
- 表示値の組み立て（区間ごとの軸スコア・材料値・到達予想時刻・ジオメトリの連結）

ここでは見ないもの:

- グラフ・探索カーネル（`domain/routing.py`）・評価軸（`domain/evaluation.py`）・
  走行モデル（`domain/cycling_speed.py`）・風（`domain/wind.py`）・
  0次フィルタ（`domain/hard_filters.py`）・キャッシュ層
  （`infrastructure/search_graph_cache.py`）・`GraphService`／`WeatherService`の中身
  → それぞれの持ち主のテストが持つ。

**境界の向こうは本物を使わない。** このファイルが実際に読む属性・呼ぶ関数だけを持つ
架空の型を与え、モジュールの名前空間ごと差し替える。実在のedge_id・軸id・材料idには
依らない（`axis_a`・`mat_a`のような性質だけの名前を使う）。
ただしRoad Graph（`LeanNode`・`LeanEdge`・`LeanRoadGraph`）と`Coordinates`は本物で作る——
公開シグネチャが要求する型で、代役にしても何も切り離せず、本物が変わったときに黙ってずれるだけになる。
"""

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.domain.graph import LeanEdge, LeanNode, LeanRoadGraph
from app.domain.route import Coordinates
from app.services import road_graph_engine as engine
from tests.bound_fake import bound


# --------------------------------------------------------------------------------------
# 架空の世界（このファイルが読む属性・呼ぶ関数だけを持つ）
# --------------------------------------------------------------------------------------


class Bag:
    """任意のキーワードをそのまま属性にする器（このファイルが組み立てて返す型の代役）。"""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def coords(latitude, longitude):
    return Coordinates(latitude=latitude, longitude=longitude)


def lean_node(node_id, latitude=0.0, longitude=0.0, **fields):
    return LeanNode(node_id=node_id, latitude=latitude, longitude=longitude, **fields)


def lean_edge(edge_id, from_node_id="n0", to_node_id="n1", *, distance_m=100.0, geometry=None, **fields):
    """探索用グラフの区間と同じく、`geometry`を省くと空のプレースホルダになる。"""
    return LeanEdge(
        edge_id=edge_id, from_node_id=from_node_id, to_node_id=to_node_id,
        geometry=[] if geometry is None else geometry, distance_m=distance_m, **fields,
    )


@dataclass
class FakeElevation:
    edge_id: str
    start_elevation_m: float | None = None
    end_elevation_m: float | None = None
    elevation_gain_m: float | None = None
    elevation_loss_m: float | None = None
    average_grade: float | None = None
    max_grade: float | None = None
    min_grade: float | None = None


@dataclass
class FakeLazyGraph:
    edge_ids: list
    index_to_node_id: list
    node_id_to_index: dict
    edge_index_by_node_pair: dict


@dataclass
class FakeCsr:
    indptr: np.ndarray
    entry_edge_index: np.ndarray
    node_count: int


@dataclass
class FakeStatics:
    csr: FakeCsr
    edge_length_m: np.ndarray


@dataclass
class FakeTurnStructure:
    indptr: np.ndarray
    target_state: np.ndarray
    turn_seconds: np.ndarray
    edge_from: np.ndarray
    edge_to: np.ndarray
    state_count: int


@dataclass
class FakeTree:
    node_cost: np.ndarray
    node_length_m: np.ndarray
    node_seconds: np.ndarray
    node_best_state: np.ndarray | None = None


@dataclass
class FakeJunction:
    cost: np.ndarray
    length_m: np.ndarray
    seconds: np.ndarray
    forward_state: np.ndarray
    backward_state: np.ndarray


class FakeScoreMatrix:
    """`GraphService`が返す静的スコア行列のうち、このファイルが読む列だけを持つ。"""

    def __init__(
        self,
        *,
        edge_ids,
        distance_m,
        gradient_percent=None,
        bearing_deg=None,
        axis_ids=(),
        axis_columns=None,
        raw_axis_ids=(),
        axis_raw_values=None,
        material_ids=(),
        material_values=None,
        categorical_material_ids=(),
        categorical_material_values=None,
        hard_filter_flags=None,
        mid_lat=None,
        mid_lon=None,
    ):
        count = len(edge_ids)
        self.edge_ids = list(edge_ids)
        self.distance_m = np.asarray(distance_m, dtype=float)
        self.gradient_percent = (
            np.zeros(count) if gradient_percent is None else np.asarray(gradient_percent, dtype=float)
        )
        self.bearing_deg = np.zeros(count) if bearing_deg is None else np.asarray(bearing_deg, dtype=float)
        self.axis_ids = list(axis_ids)
        self._axis_columns = dict(axis_columns or {})
        self.raw_axis_ids = list(raw_axis_ids)
        self.axis_raw_values = (
            np.zeros((count, len(self.raw_axis_ids)))
            if axis_raw_values is None
            else np.asarray(axis_raw_values, dtype=float)
        )
        self.material_ids = list(material_ids)
        self.material_values = (
            np.zeros((count, len(self.material_ids)))
            if material_values is None
            else np.asarray(material_values, dtype=float)
        )
        self.categorical_material_ids = list(categorical_material_ids)
        self.categorical_material_values = (
            np.empty((count, len(self.categorical_material_ids)), dtype=object)
            if categorical_material_values is None
            else np.asarray(categorical_material_values, dtype=object)
        )
        self.hard_filter_flags = hard_filter_flags
        self.mid_lat = np.zeros(count) if mid_lat is None else np.asarray(mid_lat, dtype=float)
        self.mid_lon = np.zeros(count) if mid_lon is None else np.asarray(mid_lon, dtype=float)

    def axis_arrays(self):
        return dict(self._axis_columns)


class FakeSearchGraphCache:
    """タイル集合を鍵にした各キャッシュ。保存されたかどうかを見るために呼び出しを数える。"""

    def __init__(self):
        self.lazy_graphs = {}
        self.routable = {}
        self.statics = {}
        self.turn_structures = {}
        self.detour_ratios = {}
        self.invalidated = []
        self.sets = []

    def get_lazy_graph(self, key):
        return self.lazy_graphs.get(key)

    def set_lazy_graph(self, key, value):
        self.sets.append(("lazy_graph", key))
        self.lazy_graphs[key] = value

    def get_routable_index(self, key):
        return self.routable.get(key)

    def set_routable_index(self, key, value):
        self.sets.append(("routable", key))
        self.routable[key] = value

    def get_search_statics(self, key):
        return self.statics.get(key)

    def set_search_statics(self, key, value):
        self.sets.append(("statics", key))
        self.statics[key] = value

    def get_turn_structure(self, key):
        return self.turn_structures.get(key)

    def set_turn_structure(self, key, value):
        self.sets.append(("turn_structure", key))
        self.turn_structures[key] = value

    def get_detour_ratio(self, key):
        return self.detour_ratios.get(key)

    def set_detour_ratio(self, key, value):
        self.sets.append(("detour_ratio", key))
        self.detour_ratios[key] = value

    def invalidate_tile_set(self, key):
        self.invalidated.append(key)


TILES = frozenset({(12, 1, 1)})


def make_graph(edge_specs, node_ids=None, nodes=None, highways=None):
    """`edge_specs`は`(edge_id, from, to, distance_m)`の並び。

    `nodes`（`LeanNode`の並び）を省くと、`node_ids`か端点の出現順に位置(0, 0)のNodeを作る。
    `highways`は`{edge_id: 道路種別}`で、省いた区間は種別なし。
    """
    highways = highways or {}
    edges = {}
    seen = []
    for spec in edge_specs:
        edge_id, from_node, to_node, distance_m = spec
        edges[edge_id] = lean_edge(
            edge_id, from_node, to_node, distance_m=distance_m, highway=highways.get(edge_id)
        )
        for node in (from_node, to_node):
            if node not in seen:
                seen.append(node)
    if nodes is None:
        nodes = [lean_node(node_id) for node_id in (list(node_ids) if node_ids is not None else seen)]
    return LeanRoadGraph(graph_version="test", nodes={node.node_id: node for node in nodes}, edges=edges)


def make_lazy_graph(graph, edge_ids=None, node_ids=None):
    edge_ids = list(edge_ids) if edge_ids is not None else list(graph.edges)
    node_ids = list(node_ids) if node_ids is not None else list(graph.nodes)
    node_id_to_index = {node_id: i for i, node_id in enumerate(node_ids)}
    pair_index = {}
    for index, edge_id in enumerate(edge_ids):
        edge = graph.edges[edge_id]
        pair_index[(node_id_to_index[edge.from_node_id], node_id_to_index[edge.to_node_id])] = index
    return FakeLazyGraph(
        edge_ids=edge_ids,
        index_to_node_id=node_ids,
        node_id_to_index=node_id_to_index,
        edge_index_by_node_pair=pair_index,
    )


@pytest.fixture
def cache(monkeypatch):
    fake = FakeSearchGraphCache()
    monkeypatch.setattr(engine, "search_graph_cache", fake)
    return fake


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
# bboxの組み立て
# --------------------------------------------------------------------------------------


def test_bbox_around_point_widens_longitude_with_latitude():
    """同じkmでも高緯度ほど経度は広く取る（経度1度の実距離が縮むため）。"""
    at_equator = engine._bbox_around_point(coords(0.0, 139.0), 10.0)
    at_high = engine._bbox_around_point(coords(60.0, 139.0), 10.0)

    equator_lon_margin = at_equator.max_longitude - 139.0
    equator_lat_margin = at_equator.max_latitude - 0.0
    assert equator_lon_margin == pytest.approx(equator_lat_margin)
    assert at_high.max_longitude - 139.0 > equator_lon_margin
    assert at_high.max_latitude - 60.0 == pytest.approx(equator_lat_margin)


def test_bbox_covering_points_uses_the_extremes_plus_margin():
    points = [coords(35.0, 139.0), coords(36.0, 140.0)]
    bbox = engine._bbox_covering_points(points, 2.0)

    assert bbox.min_latitude < 35.0
    assert bbox.max_latitude > 36.0
    assert bbox.min_longitude < 139.0
    assert bbox.max_longitude > 140.0
    assert bbox.max_latitude - 36.0 == pytest.approx(35.0 - bbox.min_latitude)


def test_bbox_covering_points_scales_longitude_by_the_mean_latitude():
    """経度マージンの基準は端ではなく平均緯度。端を使うと片側が足りなくなる。"""
    spread = engine._bbox_covering_points(
        [coords(0.0, 139.0), coords(60.0, 139.0)], 2.0
    )
    at_mean = engine._bbox_covering_points([coords(30.0, 139.0)], 2.0)

    assert spread.max_longitude - 139.0 == pytest.approx(at_mean.max_longitude - 139.0)


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
        "e1": FakeElevation("e1", start_elevation_m=10.0, end_elevation_m=20.0, elevation_gain_m=10.0),
        "e2": FakeElevation("e2", start_elevation_m=None, end_elevation_m=5.0, elevation_gain_m=None),
        "e4": FakeElevation("e4", start_elevation_m=30.0, end_elevation_m=None, elevation_gain_m=2.0),
    }

    result = engine._aggregate_elevation(edges, attributes)

    assert seen["sum"] == [10.0, 2.0]
    assert seen["min"] == [10.0, 20.0, 5.0, 30.0]
    assert set(result) == {"elevation_gain_m", "min_elevation_m", "max_elevation_m"}


def test_reverse_elevation_attribute_swaps_climb_and_descent():
    forward = FakeElevation(
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
    forward = FakeElevation("fwd", average_grade=None, max_grade=None, min_grade=None)
    reverse = engine._reverse_elevation_attribute(forward, "rev")
    assert reverse.average_grade is None
    assert reverse.max_grade is None
    assert reverse.min_grade is None


def test_reverse_elevation_by_edge_pairs_the_path_in_reverse_order():
    """逆方向Edgeの並びは順方向の逆。対応がずれると別の坂の値が付く。"""
    forward_edges = [lean_edge("f1"), lean_edge("f2")]
    reverse_edges = [lean_edge("r2"), lean_edge("r1")]
    attributes = {"f2": FakeElevation("f2", start_elevation_m=1.0, end_elevation_m=9.0)}

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
    forward = Bag(segments=[Bag(difficulty=5.0, distance_km=1.0)])
    reverse = Bag(segments=[Bag(difficulty=3.0, distance_km=1.0)])

    assert engine._pick_better_candidate(forward, reverse) is reverse
    assert engine._pick_better_candidate(reverse, forward) is reverse


def test_pick_better_candidate_falls_back_to_forward_when_reverse_cannot_be_scored(monkeypatch):
    """比較不能を「逆回りの方が良い」と読まない（安全側）。"""
    monkeypatch.setattr(
        engine, "distance_weighted_difficulty", lambda pairs: pairs[0][0] if pairs else None
    )
    forward = Bag(segments=[Bag(difficulty=5.0, distance_km=1.0)])
    reverse = Bag(segments=[])

    assert engine._pick_better_candidate(forward, reverse) is forward


def test_pick_better_candidate_takes_reverse_when_only_forward_is_unscorable(monkeypatch):
    monkeypatch.setattr(
        engine, "distance_weighted_difficulty", lambda pairs: pairs[0][0] if pairs else None
    )
    forward = Bag(segments=[])
    reverse = Bag(segments=[Bag(difficulty=7.0, distance_km=1.0)])

    assert engine._pick_better_candidate(forward, reverse) is reverse


def test_route_composite_difficulty_feeds_difficulty_and_distance_pairs(monkeypatch):
    captured = {}

    def record(pairs):
        captured["pairs"] = list(pairs)
        return 1.5

    monkeypatch.setattr(engine, "distance_weighted_difficulty", record)
    candidate = Bag(segments=[Bag(difficulty=2.0, distance_km=0.5), Bag(difficulty=None, distance_km=0.3)])

    assert engine._route_composite_difficulty(candidate) == 1.5
    assert captured["pairs"] == [(2.0, 0.5), (None, 0.3)]


def test_route_composite_difficulty_is_none_without_segments():
    assert engine._route_composite_difficulty(Bag(segments=[])) is None


# --------------------------------------------------------------------------------------
# 逆方向Edge列の構築
# --------------------------------------------------------------------------------------


def test_reverse_traced_edges_walks_the_path_backwards_through_the_opposite_edges():
    graph = make_graph([("a", "n1", "n2", 100.0), ("b", "n2", "n3", 200.0),
                        ("a_rev", "n2", "n1", 100.0), ("b_rev", "n3", "n2", 200.0)],
                       highways={"a_rev": "primary"})
    lazy = make_lazy_graph(graph)
    path = [
        lean_edge("a", "n1", "n2", distance_m=100.0,
                  geometry=[[35.0, 139.0], [35.1, 139.1]]),
        lean_edge("b", "n2", "n3", distance_m=200.0,
                  geometry=[[35.1, 139.1], [35.2, 139.2]]),
    ]

    reversed_edges = engine._reverse_traced_edges(path, lazy, graph)

    assert [edge.edge_id for edge in reversed_edges] == ["b_rev", "a_rev"]
    assert reversed_edges[0].geometry == [[35.2, 139.2], [35.1, 139.1]]
    # 進行方向に依存しない値は逆方向Edge自身から引く（順方向からの流用ではない）。
    assert reversed_edges[1].highway == "primary"


def test_reverse_traced_edges_is_none_when_any_segment_is_one_way():
    """一方通行が1つでもあれば物理的に逆走できない。"""
    graph = make_graph([("a", "n1", "n2", 100.0), ("a_rev", "n2", "n1", 100.0),
                        ("b", "n2", "n3", 200.0)])
    lazy = make_lazy_graph(graph)
    path = [graph.edges["a"], graph.edges["b"]]

    assert engine._reverse_traced_edges(path, lazy, graph) is None


# --------------------------------------------------------------------------------------
# 物理区間キー（進行方向を無視した重複判定の土台）
# --------------------------------------------------------------------------------------


def test_physical_segment_key_ignores_direction():
    """同じ道の順方向Edgeと逆方向Edgeが同じ鍵に落ちないと「逆回り」を弾けない。"""
    graph = make_graph([("fwd", "n1", "n2", 300.0), ("bwd", "n2", "n1", 300.0)])

    forward = engine._loop_edge_lengths_by_physical_segment(graph, ["fwd"])
    backward = engine._loop_edge_lengths_by_physical_segment(graph, ["bwd"])

    assert forward.keys() == backward.keys()
    assert list(forward.values()) == [300.0]


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
# 迂回率の実測と学習
# --------------------------------------------------------------------------------------


def make_context(**overrides):
    """`_RoadGraphContext`を、そのテストが読むフィールドだけ実体を入れて組む。"""
    defaults = dict(
        graph=make_graph([("e1", "n1", "n2", 100.0)]),
        materials=Bag(),
        accident_years_covered=1,
        weather=None,
        origin_node="n1",
        node_index=Bag(),
        lazy_graph=None,
        composer=None,
        legs=[],
        full_edge_row={},
        origin=coords(35.0, 139.0),
        node_lat=np.zeros(1),
        node_lon=np.zeros(1),
        night_active=False,
        statics=None,
        turn_structure=None,
        origin_index=0,
        tile_set=TILES,
    )
    defaults.update(overrides)
    return engine._RoadGraphContext(**defaults)


def test_median_detour_ratio_is_nan_without_targets():
    assert math.isnan(engine._median_detour_ratio(make_context(), np.array([], dtype=np.int64), np.array([])))


def test_median_detour_ratio_ignores_targets_at_zero_straight_distance(monkeypatch):
    """直線距離0のNodeは比が定義できない。0として混ぜると中央値が歪む。"""
    monkeypatch.setattr(
        engine, "haversine_distance_km_array", lambda lat, lon, origin: np.array([2.0, 0.0, 4.0])
    )
    context = make_context(node_lat=np.zeros(3), node_lon=np.zeros(3))

    ratio = engine._median_detour_ratio(context, np.array([0, 1, 2]), np.array([4000.0, 9999.0, 4000.0]))

    assert ratio == pytest.approx(1.5)


def test_median_detour_ratio_is_nan_when_every_target_is_at_zero_distance(monkeypatch):
    monkeypatch.setattr(engine, "haversine_distance_km_array", lambda lat, lon, origin: np.zeros(2))
    context = make_context(node_lat=np.zeros(2), node_lon=np.zeros(2))

    assert math.isnan(engine._median_detour_ratio(context, np.array([0, 1]), np.array([100.0, 200.0])))


def test_learn_detour_ratio_stores_a_usable_measurement(cache):
    context = make_context(composer=Bag(detour_ratio=1.4))

    assert engine._learn_detour_ratio(context, 1.9) == 1.9
    assert cache.detour_ratios[TILES] == 1.9


@pytest.mark.parametrize("measured", [float("nan"), 0.0])
def test_learn_detour_ratio_keeps_the_current_value_for_unusable_measurements(cache, measured):
    """学習値が0や負になると、到着予定時刻が0秒や負の時刻になって画面へ出る。"""
    context = make_context(composer=Bag(detour_ratio=1.4))

    assert engine._learn_detour_ratio(context, measured) == 1.4
    assert cache.detour_ratios == {}


# --------------------------------------------------------------------------------------
# A*ヒューリスティックの素材
# --------------------------------------------------------------------------------------


def test_estimate_distances_m_converts_kilometres_to_metres(monkeypatch):
    """km/mの取り違えは、そのまま1000倍のヒューリスティックになりA*が壊れる。"""
    monkeypatch.setattr(
        engine, "haversine_distance_km_array", lambda lat, lon, target: np.array([1.0, 2.5])
    )
    graph = make_graph([("e1", "n1", "n2", 10.0)])

    result = engine._estimate_distances_m(graph, np.zeros(2), np.zeros(2), "n2")

    assert result == [1000.0, 2500.0]
    assert isinstance(result, list)


def test_origin_estimate_is_computed_once_per_request(monkeypatch):
    calls = []

    def fake(graph, lat, lon, target):
        calls.append(target)
        return [1.0, 2.0]

    monkeypatch.setattr(engine, "_estimate_distances_m", fake)
    context = make_context()

    first = engine._origin_estimate(context)
    second = engine._origin_estimate(context)

    assert calls == ["n1"]
    assert second is first
    assert context.origin_estimate is first


# --------------------------------------------------------------------------------------
# CSR／遷移構造からの索引
# --------------------------------------------------------------------------------------


def test_origin_states_are_the_edges_leaving_the_node():
    csr = FakeCsr(
        indptr=np.array([0, 2, 3]),
        entry_edge_index=np.array([7, 8, 9], dtype=np.int32),
        node_count=2,
    )
    states = engine._origin_states(FakeStatics(csr=csr, edge_length_m=np.zeros(3)), 0)

    assert states.tolist() == [7, 8]
    assert states.dtype == np.int64


def test_destination_states_are_the_edges_entering_the_node():
    structure = FakeTurnStructure(
        indptr=np.array([0]), target_state=np.array([]), turn_seconds=np.array([]),
        edge_from=np.array([0, 1, 2]), edge_to=np.array([1, 2, 1]), state_count=3,
    )
    assert engine._destination_states(structure, 1).tolist() == [0, 2]


def test_node_intersection_attributes_follow_the_lazy_node_order():
    graph = make_graph(
        [("e1", "n1", "n2", 100.0)],
        nodes=[
            lean_node("n1", has_traffic_signals=True, max_highway_rank=5),
            lean_node("n2", has_traffic_signals=False, max_highway_rank=2),
        ],
    )
    lazy = make_lazy_graph(graph, node_ids=["n2", "n1"])

    signals, ranks = engine._node_intersection_attributes(graph, lazy)

    assert signals.tolist() == [False, True]
    assert ranks.tolist() == [2, 5]


def test_edge_highway_ranks_follow_the_lazy_edge_order(monkeypatch):
    monkeypatch.setattr(engine, "highway_rank", lambda highway: {"primary": 5, "path": 1}[highway])
    graph = make_graph([("e1", "n1", "n2", 100.0), ("e2", "n2", "n3", 100.0)],
                       highways={"e1": "primary", "e2": "path"})
    lazy = make_lazy_graph(graph, edge_ids=["e2", "e1"])

    assert engine._edge_highway_ranks(graph, lazy).tolist() == [1, 5]


# --------------------------------------------------------------------------------------
# 目的地そのものを経由Nodeとする候補
# --------------------------------------------------------------------------------------


def make_junction(count):
    return FakeJunction(
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
    forward = FakeTree(
        node_cost=np.array([0.0, 5.0]), node_length_m=np.array([0.0, 60.0]),
        node_seconds=np.array([0.0, 4.0]), node_best_state=np.array([-1, 3]),
    )

    engine._add_terminal_candidate(junction, forward, 1)

    assert junction.cost[1] == 5.0
    assert junction.length_m[1] == 60.0
    assert junction.seconds[1] == 4.0
    assert junction.forward_state[1] == 3
    assert junction.backward_state[1] == -1


def test_add_terminal_candidate_does_nothing_when_the_forward_tree_never_arrived():
    junction = make_junction(2)
    forward = FakeTree(
        node_cost=np.array([0.0, np.inf]), node_length_m=np.zeros(2),
        node_seconds=np.zeros(2), node_best_state=np.array([-1, -1]),
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
# 探索用グラフ・統計・遷移構造のキャッシュ
# --------------------------------------------------------------------------------------


async def test_lazy_graph_is_built_once_per_tile_set(cache, monkeypatch):
    built = []
    graph = make_graph([("e1", "n1", "n2", 100.0)])
    monkeypatch.setattr(engine, "build_lazy_road_graph", lambda g: built.append(g) or "LAZY")

    first, hit_first = await engine._get_or_build_lazy_graph(TILES, graph)
    second, hit_second = await engine._get_or_build_lazy_graph(TILES, graph)

    assert (first, hit_first) == ("LAZY", False)
    assert (second, hit_second) == ("LAZY", True)
    assert len(built) == 1


async def test_consistent_lazy_graph_is_returned_untouched(cache, monkeypatch):
    monkeypatch.setattr(engine, "find_missing_lazy_graph_edge_id", bound(engine.find_missing_lazy_graph_edge_id, lambda *a, **k: None))
    monkeypatch.setattr(engine, "build_lazy_road_graph", lambda g: pytest.fail("再構築は不要"))
    lazy = object()

    assert await engine._ensure_lazy_graph_consistent(TILES, lazy, object(), {}) is lazy
    assert cache.invalidated == []


async def test_stale_lazy_graph_is_rebuilt_from_the_graph(cache, monkeypatch):
    """古い探索用グラフをそのまま使うと、後続のedge_id引きがKeyErrorで500になる。"""
    answers = iter(["e_missing", None])
    monkeypatch.setattr(engine, "find_missing_lazy_graph_edge_id", bound(engine.find_missing_lazy_graph_edge_id, lambda *a, **k: next(answers)))
    monkeypatch.setattr(engine, "build_lazy_road_graph", lambda g: "REBUILT")

    result = await engine._ensure_lazy_graph_consistent(TILES, "STALE", object(), {})

    assert result == "REBUILT"
    assert cache.invalidated == [TILES]
    assert cache.lazy_graphs[TILES] == "REBUILT"


async def test_rebuilding_that_does_not_help_is_raised_not_swallowed(cache, monkeypatch):
    """作り直しても解消しない＝ずれているのは静的スコア行列側。黙って進むと原因不明の500になる。"""
    monkeypatch.setattr(engine, "find_missing_lazy_graph_edge_id", bound(engine.find_missing_lazy_graph_edge_id, lambda *a, **k: "e_missing"))
    monkeypatch.setattr(engine, "build_lazy_road_graph", lambda g: "REBUILT")

    with pytest.raises(engine.LazyGraphEdgeMismatchError) as raised:
        await engine._ensure_lazy_graph_consistent(TILES, "STALE", object(), {})

    assert "e_missing" in str(raised.value)


async def test_search_statics_are_built_once_per_tile_set(cache, monkeypatch):
    built = []
    monkeypatch.setattr(
        engine, "build_search_graph_statics", lambda lazy, graph: built.append(1) or "STATICS"
    )

    first = await engine._get_or_build_search_statics(TILES, object(), object())
    second = await engine._get_or_build_search_statics(TILES, object(), object())

    assert first == ("STATICS", False)
    assert second == ("STATICS", True)
    assert len(built) == 1


async def test_turn_structure_cache_key_includes_the_turn_cost(cache, monkeypatch):
    """ターンの費用はリクエストで上書きできる。鍵に含めないと別の較正値の構造を引く。"""
    monkeypatch.setattr(engine, "highway_rank", lambda highway: 1)
    monkeypatch.setattr(engine, "edge_bearings", lambda graph, lazy: np.zeros(len(lazy.edge_ids)))
    built = []

    def fake_build(csr, lazy, bearings, ranks, turn_cost, signals, node_ranks):
        built.append(turn_cost)
        return "STRUCTURE_%s" % turn_cost

    monkeypatch.setattr(engine, "build_turn_expanded_structure", fake_build)
    graph = make_graph([("e1", "n1", "n2", 100.0)])
    lazy = make_lazy_graph(graph)
    statics = FakeStatics(csr=FakeCsr(np.array([0, 1, 1]), np.array([0]), 2), edge_length_m=np.zeros(1))

    first = await engine._get_or_build_turn_structure(TILES, statics, lazy, graph, "cost_a")
    again = await engine._get_or_build_turn_structure(TILES, statics, lazy, graph, "cost_a")
    other = await engine._get_or_build_turn_structure(TILES, statics, lazy, graph, "cost_b")

    assert first == ("STRUCTURE_cost_a", False)
    assert again == ("STRUCTURE_cost_a", True)
    assert other == ("STRUCTURE_cost_b", False)
    assert built == ["cost_a", "cost_b"]


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
    """合成が呼ぶ相手（走行モデル・風・軸の合成）の代役。渡された値を記録する。"""

    def __init__(self):
        self.passages = []
        self.compose_calls = []
        self.weighted_sum_calls = []
        self.crr_inputs = []


@pytest.fixture
def composer_world(monkeypatch):
    world = ComposerWorld()

    class FakeDynamicContext:
        def __init__(self, *, bearing_deg, weather, travel_speed_ms, wind_series, start, passage_hours):
            self.bearing_deg = bearing_deg
            self.weather = weather
            self.travel_speed_ms = travel_speed_ms
            self.wind_series = wind_series
            self.start = start
            self.passage_hours = passage_hours

        def wind_inputs(self):
            return None if self.wind_series is None else (3.0, 5.0)

    def fake_evaluate(static_axis_scores, context):
        world.passages.append(None if context.passage_hours is None else np.asarray(context.passage_hours).copy())
        count = len(context.bearing_deg)
        marker = -1.0 if context.passage_hours is None else float(np.asarray(context.passage_hours)[0])
        resolved = dict(static_axis_scores)
        resolved[AXIS_WIND] = np.full(count, marker)
        resolved[MAT_DYN] = np.full(count, 7.0)
        resolved[MAT_DYN_EMPTY] = np.full(count, np.nan)
        return resolved

    def fake_wind_components(headwind_ms, crosswind_ms, bearing_deg):
        count = len(bearing_deg)
        return np.full(count, headwind_ms), np.full(count, crosswind_ms)

    def fake_crr(values, count):
        world.crr_inputs.append(values)
        return np.full(count, 0.005)

    def fake_travel(distance_m, profile, grade, headwind, crosswind, crr):
        return np.asarray(distance_m, dtype=float) / 10.0 + np.asarray(headwind, dtype=float)

    def fake_compose_costs(distance_m, time_varying, weights, penalty, *, base, static_sums):
        count = len(distance_m)
        total = np.zeros(count)
        for axis_id, values in time_varying.items():
            total = total + weights.get(axis_id, 0.0) * np.asarray(values, dtype=float)
        world.compose_calls.append(
            {"axes": sorted(time_varying), "penalty": penalty, "static_sums": static_sums}
        )
        return Bag(
            cost=np.asarray(base, dtype=float) + total,
            difficulty=total.copy(),
            weight_sums=np.full(count, float(len(time_varying))),
        )

    def fake_weighted_sums(arrays, weights, count):
        world.weighted_sum_calls.append(sorted(arrays))
        return np.zeros(count), np.zeros(count)

    monkeypatch.setattr(engine, "AXIS_DEFINITIONS", {})
    monkeypatch.setattr(engine, "dynamic_axis_topological_order", lambda definitions: [AXIS_WIND])
    monkeypatch.setattr(engine, "REQUEST_DYNAMIC_MATERIAL_IDS", (MAT_DYN, MAT_DYN_EMPTY))
    monkeypatch.setattr(engine, "DynamicAxisRequestContext", FakeDynamicContext)
    monkeypatch.setattr(engine, "evaluate_dynamic_axis_arrays", fake_evaluate)
    monkeypatch.setattr(engine, "wind_components", fake_wind_components)
    monkeypatch.setattr(engine, "crr_for_surface", fake_crr)
    monkeypatch.setattr(engine, "travel_seconds", fake_travel)
    monkeypatch.setattr(engine, "RiderProfile", lambda **kwargs: Bag(**kwargs))
    monkeypatch.setattr(engine, "ROLLING_RESISTANCE_MATERIAL_ID", MAT_CRR)
    monkeypatch.setattr(engine, "POI_COUNT_KINDS", ("kind_a", "kind_b"))
    monkeypatch.setattr(engine, "stop_count_material_ids", lambda: [MAT_STOP_A, MAT_STOP_B])
    monkeypatch.setattr(engine, "stop_seconds", lambda kind: {"kind_a": 10.0, "kind_b": 2.0}[kind])
    monkeypatch.setattr(engine, "compose_costs_from_axis_matrix", fake_compose_costs)
    monkeypatch.setattr(engine, "axis_weighted_sums", fake_weighted_sums)
    monkeypatch.setattr(engine, "kmh_to_ms", lambda kmh: kmh / 3.6)
    return world


def make_score_matrix(count=3, **overrides):
    columns = {
        AXIS_STATIC: np.full(count, 1.0),
        AXIS_WIND: np.full(count, 0.0),
    }
    defaults = dict(
        edge_ids=["e%d" % i for i in range(count)],
        distance_m=np.full(count, 1000.0),
        axis_ids=[AXIS_STATIC, AXIS_WIND],
        axis_columns=columns,
        raw_axis_ids=[AXIS_STATIC],
        axis_raw_values=np.arange(count, dtype=float).reshape(count, 1),
        material_ids=[MAT_STOP_A, MAT_CRR],
        material_values=np.column_stack([np.full(count, 2.0), np.full(count, 0.004)]),
        categorical_material_ids=["cat_a"],
        categorical_material_values=np.array([["paved"]] * count, dtype=object),
    )
    defaults.update(overrides)
    return FakeScoreMatrix(**defaults)


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
    assert make_composer(wind_series=Bag()).time_varying is True


def test_to_full_row_order_marks_edges_absent_from_the_search_graph(composer_world):
    """並行Edgeの採られなかった方は探索に載らない。別Edgeの値で埋めると通過時刻がずれる。"""
    composer = make_composer(make_score_matrix(count=3), lazy_row_index=[2, 0])

    restored = composer.to_full_row_order(np.array([10.0, 20.0]))

    assert restored[2] == 10.0
    assert restored[0] == 20.0
    assert math.isnan(restored[1])


def test_lazy_hard_filter_excluded_is_reindexed_and_kept(composer_world):
    composer = make_composer(make_score_matrix(count=3), excluded=[True, False, True], lazy_row_index=[2, 1, 0])

    first = composer.lazy_hard_filter_excluded

    assert first.tolist() == [True, False, True]
    assert composer.lazy_hard_filter_excluded is first


def test_bin_count_is_one_without_a_duration_or_without_wind(composer_world):
    with_wind = make_composer(wind_series=Bag())
    assert with_wind._bin_count(None) == 1
    assert make_composer()._bin_count(5.0) == 1


def test_bin_count_covers_the_duration_up_to_the_ceiling(composer_world):
    """ビン1本ごとにbbox全体の合成が1回走るため、長いレグでも上限で頭打ちにする。"""
    composer = make_composer(wind_series=Bag())

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
    composer = make_composer(wind_series=Bag())

    leg = composer.compose("outbound", coords(35.0, 139.0), 0.0, +1, duration_hours=3.0)

    assert leg.cost_bins_lazy.shape == (3, 3)
    assert leg.travel_bins_lazy.shape == (3, 3)
    assert leg.bin_seconds == engine.TIME_BIN_HOURS * 3600.0
    assert [float(p[0]) for p in composer_world.passages] == [0.0, 1.0, 2.0]


def test_compose_of_an_inbound_leg_counts_time_from_the_start_of_that_leg(composer_world):
    """`direction=-1`の`offset_hours`はレグの終了時刻。開始時刻へ直さないと風が2時間ずれる。"""
    composer = make_composer(wind_series=Bag())

    composer.compose("inbound", coords(35.0, 139.0), 5.0, -1, duration_hours=2.0)

    assert [float(p[0]) for p in composer_world.passages] == [3.0, 4.0]


def test_compose_representative_arrays_come_from_the_middle_bin(composer_world):
    """表示と、時刻ラベルを持てない探索が読む値。端のビンだと実際に走る時刻と合わない。"""
    composer = make_composer(wind_series=Bag())

    leg = composer.compose("outbound", coords(35.0, 139.0), 0.0, +1, duration_hours=3.0)

    assert leg.cost_lazy.tolist() == leg.cost_bins_lazy[1].tolist()


def test_compose_reuses_a_leg_composed_for_the_same_start_and_bins(composer_world):
    composer = make_composer(wind_series=Bag())

    first = composer.compose("outbound", coords(35.0, 139.0), 1.0, +1, duration_hours=2.0)
    again = composer.compose("leg1", coords(36.0, 140.0), 1.0, +1, duration_hours=2.0)

    assert again is first
    assert len(composer_world.passages) == 2


def test_compose_with_measured_passage_hours_is_a_single_bin(composer_world):
    """後ろ向き木は時刻ラベルを持てない。前向き木の実到達時間を区間ごとに渡す。"""
    composer = make_composer(wind_series=Bag())
    passage = np.array([0.5, 1.5, 2.5])

    leg = composer.compose("inbound", coords(35.0, 139.0), 4.0, -1, passage_hours=passage)

    assert leg.cost_bins_lazy.shape[0] == 1
    assert leg.bin_seconds == np.inf
    assert composer_world.passages[-1].tolist() == [0.5, 1.5, 2.5]


def test_compose_keeps_composing_by_time_even_without_an_anchor(composer_world):
    """風は軸である前に走行モデルの入力。系列があれば基準点の有無に関わらず時刻で引く。"""
    composer = make_composer(wind_series=Bag())

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
        edge_ids=["e0", "e1"],
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


def test_fixed_axis_sums_exclude_the_time_varying_axes(composer_world):
    """時刻で変わる軸が固定側にも入ると、合成で二重に足される。"""
    composer = make_composer(wind_series=Bag())

    composer.compose("outbound", coords(35.0, 139.0), 0.0, +1, duration_hours=3.0)

    assert composer_world.weighted_sum_calls == [[AXIS_STATIC]]
    assert composer_world.compose_calls[0]["axes"] == [AXIS_WIND]


# --------------------------------------------------------------------------------------
# エンジン本体の土台（bbox全体の探索用グラフとリクエスト単位の文脈）
# --------------------------------------------------------------------------------------


class FakeGraphService:
    def __init__(self, built, years=3):
        self._built = built
        self._years = years
        self.bboxes = []
        self.hydrate_calls = []

    async def get_search_materials_for_bbox(self, bbox):
        self.bboxes.append(bbox)
        return self._built

    async def get_accident_years_covered(self):
        return self._years

    async def get_edges_with_geometry(self, edges):
        self.hydrate_calls.append([edge.edge_id for edge in edges])
        return {edge.edge_id: edge for edge in edges}


class FakeWeatherService:
    def __init__(self, conditions=None, wind_series=None):
        self._conditions = conditions
        self._wind_series = wind_series
        self.asked = []

    async def get_conditions(self, origin):
        self.asked.append(("conditions", origin))
        return self._conditions

    async def get_wind_forecast_series(self, origin):
        self.asked.append(("series", origin))
        return self._wind_series


def make_engine(graph_service, weather_service, **kwargs):
    preference = Bag(with_time_scope=lambda scopes: Bag(weights={AXIS_STATIC: 1.0, AXIS_WIND: 2.0}, scopes=scopes))
    defaults = dict(penalty_strength=1.0, assumed_speed_kmh=20.0, turn_cost="cost_a")
    defaults.update(kwargs)
    return engine.RoadGraphEngine(graph_service, weather_service, preference, **defaults)


@pytest.fixture
def search_world(monkeypatch, cache, composer_world):
    """`_build_search_graph`が触る境界をすべて架空にした一式。"""
    graph = make_graph(
        [("e0", "n0", "n1", 1000.0), ("e1", "n1", "n2", 1000.0), ("e2", "n2", "n0", 1000.0)],
        nodes=[lean_node(f"n{index}", 35.0 + index, 139.0 + index) for index in range(3)],
    )
    lazy = make_lazy_graph(graph)
    score_matrix = make_score_matrix(count=3, edge_ids=list(graph.edges))
    statics = FakeStatics(
        csr=FakeCsr(indptr=np.array([0, 1, 2, 3]), entry_edge_index=np.array([0, 1, 2]), node_count=3),
        edge_length_m=np.full(3, 1000.0),
    )
    structure = FakeTurnStructure(
        indptr=np.array([0, 1, 2, 3]),
        target_state=np.array([1, 2, 0]),
        turn_seconds=np.array([4.0, 6.0, 8.0]),
        edge_from=np.array([0, 1, 2]),
        edge_to=np.array([1, 2, 0]),
        state_count=3,
    )
    built = (Bag(graph=graph, materials=Bag()), score_matrix, TILES)
    graph_service = FakeGraphService(built)
    weather_service = FakeWeatherService()

    monkeypatch.setattr(engine, "is_night", lambda origin, now: False)
    monkeypatch.setattr(engine, "compute_hard_filter_excluded", bound(engine.compute_hard_filter_excluded, lambda *a: np.zeros(3, dtype=bool)))
    monkeypatch.setattr(engine, "build_lazy_road_graph", lambda g: lazy)
    monkeypatch.setattr(engine, "find_missing_lazy_graph_edge_id", bound(engine.find_missing_lazy_graph_edge_id, lambda *a, **k: None))
    monkeypatch.setattr(engine, "build_search_graph_statics", lambda lz, g: statics)
    monkeypatch.setattr(engine, "build_turn_expanded_structure", bound(engine.build_turn_expanded_structure, lambda *a: structure))
    monkeypatch.setattr(engine, "edge_bearings", lambda g, lz: np.zeros(len(lz.edge_ids)))
    monkeypatch.setattr(engine, "highway_rank", lambda highway: 1)
    monkeypatch.setattr(engine, "compute_routable_node_ids", lambda g, ids, excluded: list(g.nodes))
    monkeypatch.setattr(engine, "build_node_spatial_index", lambda g, node_ids: Bag(node_ids=list(node_ids)))
    monkeypatch.setattr(engine, "find_nearest_node_indexed", bound(engine.find_nearest_node_indexed, lambda index, point, **kwargs: "n0"))
    monkeypatch.setattr(engine, "haversine_distance_km_array", lambda lat, lon, target: np.ones(len(lat)))
    monkeypatch.setattr(engine, "haversine_distance_km", lambda a, b: 5.0)
    monkeypatch.setattr(engine, "tuning_value", lambda key: {"speed.walking_kmh": 4.0, "speed.max_descent_kmh": 60.0}[key])
    monkeypatch.setattr(engine, "current_turn_cost", lambda: "cost_default")

    return Bag(
        graph=graph, lazy=lazy, score_matrix=score_matrix, statics=statics, structure=structure,
        graph_service=graph_service, weather_service=weather_service, cache=cache, world=composer_world,
        engine=make_engine(graph_service, weather_service),
    )


NOW = datetime(2026, 9, 22, 0, 0, tzinfo=timezone.utc)


def test_turn_cost_defaults_to_the_calibrated_value(search_world):
    """較正中はリクエストで上書きして試せること（既定は現行の較正値）。"""
    default = make_engine(search_world.graph_service, search_world.weather_service, turn_cost=None)
    overridden = make_engine(search_world.graph_service, search_world.weather_service, turn_cost="cost_b")

    assert default._turn_cost == "cost_default"
    assert overridden._turn_cost == "cost_b"


async def test_build_search_graph_gives_up_when_the_area_has_no_edges(search_world):
    empty = make_graph([])
    search_world.graph_service._built = (Bag(graph=empty, materials=Bag()), search_world.score_matrix, TILES)

    assert await search_world.engine._build_search_graph(Bag(), coords(35.0, 139.0), NOW) is None


async def test_build_search_graph_starts_the_clock_in_local_time(search_world):
    """風の時別系列はJSTのローカル時刻。揃えないと通過時刻が9時間ずれる。"""
    search = await search_world.engine._build_search_graph(Bag(), coords(35.0, 139.0), NOW)

    assert search.composer.start.tzinfo is None
    assert search.composer.start - NOW.replace(tzinfo=None) == timedelta(hours=9)


async def test_build_search_graph_activates_night_scoped_axes_only_at_night(search_world, monkeypatch):
    """夜間軸の重みをそのまま使うか0倍にするかは、出発地点が薄明の外かで決まる。"""
    monkeypatch.setattr(engine, "is_night", lambda origin, now: True)
    at_night = await search_world.engine._build_search_graph(Bag(), coords(35.0, 139.0), NOW)

    monkeypatch.setattr(engine, "is_night", lambda origin, now: False)
    by_day = await search_world.engine._build_search_graph(Bag(), coords(35.0, 139.0), NOW)

    assert at_night.night_active is True
    assert by_day.night_active is False


async def test_build_search_graph_prefers_a_learned_detour_ratio(search_world):
    search_world.cache.detour_ratios[TILES] = 1.77

    search = await search_world.engine._build_search_graph(Bag(), coords(35.0, 139.0), NOW)

    assert search.composer.detour_ratio == 1.77


async def test_build_search_graph_falls_back_to_the_default_detour_ratio(search_world):
    search = await search_world.engine._build_search_graph(Bag(), coords(35.0, 139.0), NOW)

    assert search.composer.detour_ratio == engine.ROUTE_DETOUR_RATIO


async def test_build_search_graph_orders_node_coordinates_like_the_search_graph(search_world, monkeypatch):
    """A*のヒューリスティックはこの並びで引く。ずれると別のNodeの距離が使われる。"""
    reordered = make_lazy_graph(search_world.graph, node_ids=["n2", "n1", "n0"])
    monkeypatch.setattr(engine, "build_lazy_road_graph", lambda g: reordered)

    search = await search_world.engine._build_search_graph(Bag(), coords(35.0, 139.0), NOW)

    assert search.node_lat.tolist() == [37.0, 36.0, 35.0]


async def test_build_search_graph_asks_the_weather_at_the_given_origin(search_world):
    origin = coords(35.5, 139.5)

    await search_world.engine._build_search_graph(Bag(), origin, NOW)

    assert search_world.weather_service.asked == [("conditions", origin), ("series", origin)]


# --------------------------------------------------------------------------------------
# routable Node索引のキャッシュ
# --------------------------------------------------------------------------------------


async def test_routable_node_index_is_keyed_by_the_zeroth_filter_settings(search_world, monkeypatch):
    """索引は除外後のNodeに絞ってある。設定が変われば別物で、使い回すと通れない道を通る。"""
    built = []
    monkeypatch.setattr(
        engine, "build_node_spatial_index",
        lambda g, node_ids: built.append(1) or Bag(node_ids=list(node_ids)),
    )
    lenient = make_engine(search_world.graph_service, search_world.weather_service, max_average_grade_percent=None)
    strict = make_engine(search_world.graph_service, search_world.weather_service, max_average_grade_percent=8.0)
    args = (TILES, search_world.graph, search_world.score_matrix.edge_ids, np.zeros(3, dtype=bool))

    first, hit_first = await lenient._get_or_build_node_index(*args)
    _again, hit_again = await lenient._get_or_build_node_index(*args)
    _other, hit_other = await strict._get_or_build_node_index(*args)

    assert (hit_first, hit_again, hit_other) == (False, True, False)
    assert len(built) == 2
    assert first.node_ids == ["n0", "n1", "n2"]


# --------------------------------------------------------------------------------------
# prepare（リクエスト単位の文脈の組み立て）
# --------------------------------------------------------------------------------------


async def test_prepare_covers_the_loop_radius_plus_a_proportional_margin(search_world):
    """道なりは直線の外接矩形からはみ出る。半径に比例した余裕を足して取り直しを防ぐ。"""
    await search_world.engine.prepare(coords(35.0, 139.0), 20.0, now=NOW)
    await search_world.engine.prepare(coords(35.0, 139.0), 40.0, now=NOW)
    twenty, forty = search_world.graph_service.bboxes

    twenty_span = twenty.max_latitude - twenty.min_latitude
    forty_span = forty.max_latitude - forty.min_latitude
    assert forty_span == pytest.approx(twenty_span * 2.0)
    assert twenty_span / 2 > 20.0 / engine.KM_PER_DEGREE_LATITUDE


async def test_prepare_keeps_a_minimum_margin_for_small_radii(search_world):
    """比例だけだと短距離で余裕がほぼ消え、川や線路の迂回で探索が失敗する。"""
    await search_world.engine.prepare(coords(35.0, 139.0), 1.0, now=NOW)
    bbox = search_world.graph_service.bboxes[0]

    half_span_km = (bbox.max_latitude - bbox.min_latitude) / 2 * engine.KM_PER_DEGREE_LATITUDE
    assert half_span_km > 1.0 * (1.0 + engine.BBOX_MARGIN_RATIO)


async def test_prepare_with_waypoints_covers_every_point_instead_of_the_radius(search_world):
    """経由地は半径の中にあるとは限らない。円形bboxだと指定地点が範囲外になる。"""
    origin = coords(35.0, 139.0)
    far = coords(35.9, 139.9)

    await search_world.engine.prepare(origin, 1.0, now=NOW, waypoints=[far])
    bbox = search_world.graph_service.bboxes[0]

    assert bbox.min_latitude < 35.0
    assert bbox.max_latitude > 35.9
    assert bbox.max_longitude > 139.9


async def test_prepare_gives_up_when_the_area_has_no_graph(search_world):
    search_world.graph_service._built = None

    assert await search_world.engine.prepare(coords(35.0, 139.0), 10.0, now=NOW) is None


async def test_prepare_gives_up_when_the_origin_cannot_be_snapped(search_world, monkeypatch):
    monkeypatch.setattr(engine, "find_nearest_node_indexed", bound(engine.find_nearest_node_indexed, lambda index, point, **kwargs: None))

    assert await search_world.engine.prepare(coords(35.0, 139.0), 10.0, now=NOW) is None


async def test_prepare_hands_on_the_outbound_leg_and_the_origin_index(search_world):
    context = await search_world.engine.prepare(coords(35.0, 139.0), 10.0, now=NOW)

    assert context.origin_node == "n0"
    assert context.origin_index == search_world.lazy.node_id_to_index["n0"]
    assert len(context.legs) == 1
    assert context.tile_set == TILES
    assert context.full_edge_row == {"e0": 0, "e1": 1, "e2": 2}


# --------------------------------------------------------------------------------------
# preview_segment（2点間の単発区間確認）
# --------------------------------------------------------------------------------------


async def test_preview_segment_reports_distance_and_duration_of_the_path(search_world, monkeypatch):
    monkeypatch.setattr(engine, "turn_expanded_shortest_path", bound(engine.turn_expanded_shortest_path, lambda *a: [0, 1]))
    shapes = {"e0": [[35.0, 139.0], [35.1, 139.1]], "e1": [[35.1, 139.1], [35.2, 139.2]]}
    hydrate_with_geometry(search_world.graph_service, shapes.__getitem__)

    segment = await search_world.engine.preview_segment(
        coords(35.0, 139.0), coords(35.2, 139.2), now=NOW
    )

    assert segment.distance_km == 2.0
    assert segment.duration_minutes == 6.0
    assert segment.geometry["coordinates"] == [[139.0, 35.0], [139.1, 35.1], [139.2, 35.2]]


async def test_preview_segment_is_none_when_either_end_cannot_be_snapped(search_world, monkeypatch):
    monkeypatch.setattr(engine, "find_nearest_node_indexed", bound(engine.find_nearest_node_indexed, lambda index, point, **kwargs: None))

    assert await search_world.engine.preview_segment(
        coords(35.0, 139.0), coords(35.2, 139.2), now=NOW
    ) is None


@pytest.mark.parametrize("path", [None, []])
async def test_preview_segment_is_none_when_no_path_exists(search_world, monkeypatch, path):
    monkeypatch.setattr(engine, "turn_expanded_shortest_path", bound(engine.turn_expanded_shortest_path, lambda *a: path))

    assert await search_world.engine.preview_segment(
        coords(35.0, 139.0), coords(35.2, 139.2), now=NOW
    ) is None


async def test_preview_segment_is_none_when_the_area_has_no_graph(search_world):
    search_world.graph_service._built = None

    assert await search_world.engine.preview_segment(
        coords(35.0, 139.0), coords(35.2, 139.2), now=NOW
    ) is None


# --------------------------------------------------------------------------------------
# 地点列を順に結ぶ（経由地・目的地指定ルート）
# --------------------------------------------------------------------------------------


async def prepared(world, origin=None, **kwargs):
    origin = origin or coords(35.0, 139.0)
    return await world.engine.prepare(origin, 10.0, now=NOW, **kwargs)


class PathRecorder:
    """`turn_expanded_shortest_path`の代役。呼ばれた目的地を控えつつ決められた経路を返す。"""

    def __init__(self, results):
        self._results = list(results)
        self.destinations = []
        self.calls = []

    def __call__(self, structure, costs, heuristic, origin_states, destination_index, *rest):
        self.destinations.append(destination_index)
        self.calls.append((costs, rest))
        return self._results.pop(0)


def snap_by_latitude(mapping, default=None):
    def snap(index, point, **kwargs):
        return mapping.get(round(point.latitude, 4), default)

    return bound(engine.find_nearest_node_indexed, snap)


async def test_trace_loop_reuses_the_snapped_origin_for_a_closed_loop(search_world, monkeypatch):
    """起終点を同じNodeに揃えないと周回が閉じない。"""
    context = await prepared(search_world)
    recorder = PathRecorder([[0, 1], [2]])
    monkeypatch.setattr(engine, "turn_expanded_shortest_path", recorder)
    monkeypatch.setattr(engine, "find_nearest_node_indexed", snap_by_latitude({36.0: "n1"}, default="n9"))
    origin = coords(35.0, 139.0)

    await search_world.engine.trace_loop(context, [origin, coords(36.0, 139.5), origin], 90)

    assert recorder.destinations[-1] == search_world.lazy.node_id_to_index[context.origin_node]


async def test_trace_loop_snaps_a_distinct_destination_on_its_own(search_world, monkeypatch):
    context = await prepared(search_world)
    recorder = PathRecorder([[0, 1]])
    monkeypatch.setattr(engine, "turn_expanded_shortest_path", recorder)
    monkeypatch.setattr(engine, "find_nearest_node_indexed", snap_by_latitude({37.0: "n2"}))

    await search_world.engine.trace_loop(
        context, [coords(35.0, 139.0), coords(37.0, 139.9)], None
    )

    assert recorder.destinations == [search_world.lazy.node_id_to_index["n2"]]


async def test_trace_loop_numbers_the_legs_in_travel_order(search_world, monkeypatch):
    """レグ番号は区間表示が読む時刻帯の添字。境目がずれると別の時刻の風で描かれる。"""
    context = await prepared(search_world)
    monkeypatch.setattr(engine, "turn_expanded_shortest_path", PathRecorder([[0, 1], [2]]))
    monkeypatch.setattr(engine, "find_nearest_node_indexed", snap_by_latitude({36.0: "n1"}, default="n0"))
    origin = coords(35.0, 139.0)

    traced = await search_world.engine.trace_loop(context, [origin, coords(36.0, 139.5), origin], 90)

    assert traced.data == ["e0", "e1", "e2"]
    assert traced.leg_of_edge == [0, 0, 1]
    assert traced.distance_km == 3.0
    assert traced.bearing == 90
    assert len(context.legs) == 2


async def test_trace_loop_refuses_a_waypoint_that_cannot_be_snapped(search_world, monkeypatch):
    context = await prepared(search_world)
    monkeypatch.setattr(engine, "find_nearest_node_indexed", snap_by_latitude({}, default=None))
    origin = coords(35.0, 139.0)

    with pytest.raises(engine.RoutingError, match="snap waypoints"):
        await search_world.engine.trace_loop(context, [origin, coords(36.0, 139.5), origin], 90)


async def test_trace_loop_refuses_a_destination_that_cannot_be_snapped(search_world, monkeypatch):
    context = await prepared(search_world)
    monkeypatch.setattr(engine, "find_nearest_node_indexed", snap_by_latitude({}, default=None))

    with pytest.raises(engine.RoutingError, match="snap destination"):
        await search_world.engine.trace_loop(
            context, [coords(35.0, 139.0), coords(37.0, 139.9)], None
        )


async def test_trace_loop_refuses_when_a_leg_has_no_path(search_world, monkeypatch):
    context = await prepared(search_world)
    monkeypatch.setattr(engine, "turn_expanded_shortest_path", PathRecorder([[0], None]))
    monkeypatch.setattr(engine, "find_nearest_node_indexed", snap_by_latitude({36.0: "n1"}, default="n0"))
    origin = coords(35.0, 139.0)

    with pytest.raises(engine.RoutingError, match="no path found"):
        await search_world.engine.trace_loop(context, [origin, coords(36.0, 139.5), origin], 90)


async def test_trace_loop_refuses_a_path_made_of_no_edges(search_world, monkeypatch):
    """区間0本の経路は評価も描画もできない。空のまま候補一覧へ並べない。"""
    context = await prepared(search_world)
    monkeypatch.setattr(engine, "turn_expanded_shortest_path", PathRecorder([[]]))
    monkeypatch.setattr(engine, "find_nearest_node_indexed", snap_by_latitude({37.0: "n2"}))

    with pytest.raises(engine.RoutingError, match="no edges"):
        await search_world.engine.trace_loop(
            context, [coords(35.0, 139.0), coords(37.0, 139.9)], None
        )


async def test_trace_loop_discards_legs_left_over_from_a_previous_trace(search_world, monkeypatch):
    """レグ番号は`context.legs`の添字。前の候補のレグが残ると別の時刻帯を指す。"""
    context = await prepared(search_world)
    context.legs = [context.legs[0], "STALE", "STALE"]
    monkeypatch.setattr(engine, "turn_expanded_shortest_path", PathRecorder([[0]]))
    monkeypatch.setattr(engine, "find_nearest_node_indexed", snap_by_latitude({37.0: "n2"}))

    await search_world.engine.trace_loop(
        context, [coords(35.0, 139.0), coords(37.0, 139.9)], None
    )

    assert context.legs == [context.legs[0]]


# --------------------------------------------------------------------------------------
# クライアントが組み立てたEdge列の検証
# --------------------------------------------------------------------------------------


async def test_built_path_must_not_be_empty(search_world):
    context = await prepared(search_world)

    with pytest.raises(engine.RoutingError, match="空です"):
        search_world.engine.build_traced_from_edge_ids(context, [])


async def test_built_path_must_only_use_edges_of_this_graph(search_world):
    """未知のidをそのまま信じると、評価は通るのに描けない経路が候補一覧へ並ぶ。"""
    context = await prepared(search_world)

    with pytest.raises(engine.RoutingError, match="未知のEdge"):
        search_world.engine.build_traced_from_edge_ids(context, ["e0", "e_unknown"])


async def test_built_path_must_start_at_the_origin(search_world):
    context = await prepared(search_world)

    with pytest.raises(engine.RoutingError, match="起点から始まっていません"):
        search_world.engine.build_traced_from_edge_ids(context, ["e1", "e2"])


async def test_built_path_must_be_connected(search_world):
    context = await prepared(search_world)

    with pytest.raises(engine.RoutingError, match="つながっていません"):
        search_world.engine.build_traced_from_edge_ids(context, ["e0", "e2"])


async def test_built_path_must_reach_the_destination_when_one_is_given(search_world, monkeypatch):
    context = await prepared(search_world)
    monkeypatch.setattr(engine, "find_nearest_node_indexed", bound(engine.find_nearest_node_indexed, lambda index, point, **kwargs: "n2"))

    with pytest.raises(engine.RoutingError, match="目的地に着いていません"):
        search_world.engine.build_traced_from_edge_ids(context, ["e0"], destination=coords(37.0, 139.9))


async def test_built_path_skips_the_destination_check_when_it_cannot_be_snapped(search_world, monkeypatch):
    context = await prepared(search_world)
    monkeypatch.setattr(engine, "find_nearest_node_indexed", bound(engine.find_nearest_node_indexed, lambda index, point, **kwargs: None))

    traced = search_world.engine.build_traced_from_edge_ids(
        context, ["e0"], destination=coords(37.0, 139.9)
    )

    assert traced.data == ["e0"]


async def test_built_path_splits_its_legs_at_half_the_distance(search_world):
    context = await prepared(search_world)

    traced = search_world.engine.build_traced_from_edge_ids(context, ["e0", "e1", "e2"])

    assert traced.leg_of_edge == [0, 0, 1]
    assert traced.distance_km == 3.0
    assert traced.bearing is None


async def test_built_path_creates_the_inbound_leg_it_numbers(search_world):
    """レグ番号を振る側がそのレグを用意する。用意しないと表示が範囲外の添字を引く。"""
    context = await prepared(search_world)
    assert len(context.legs) == 1

    search_world.engine.build_traced_from_edge_ids(context, ["e0", "e1"])

    assert len(context.legs) == 2


async def test_built_path_of_a_single_edge_stays_on_the_outbound_leg(search_world):
    context = await prepared(search_world)

    traced = search_world.engine.build_traced_from_edge_ids(context, ["e0"])

    assert traced.leg_of_edge == [0]
    assert len(context.legs) == 1


# --------------------------------------------------------------------------------------
# 周回同士の重複判定
# --------------------------------------------------------------------------------------


def make_similarity_context(edge_specs):
    return make_context(graph=make_graph(edge_specs))


def test_a_loop_is_too_similar_when_it_shares_most_of_its_length():
    context = make_similarity_context(
        [("a", "n1", "n2", 800.0), ("b", "n2", "n3", 200.0), ("c", "n3", "n4", 200.0)]
    )
    candidate = Bag(bearing=90, data=["a", "b"])
    accepted = [Bag(bearing=180, data=["a", "c"])]

    assert engine.RoadGraphEngine.is_loop_too_similar(None, context, candidate, accepted) is True


def test_a_loop_that_shares_little_is_kept():
    context = make_similarity_context(
        [("a", "n1", "n2", 200.0), ("b", "n2", "n3", 800.0), ("c", "n3", "n4", 200.0)]
    )
    candidate = Bag(bearing=90, data=["a", "b"])
    accepted = [Bag(bearing=180, data=["a", "c"])]

    assert engine.RoadGraphEngine.is_loop_too_similar(None, context, candidate, accepted) is False


def test_a_loop_ridden_the_other_way_round_counts_as_the_same_loop():
    """往路と復路が入れ替わっただけの周回を、別候補として一覧へ並べない。"""
    context = make_similarity_context(
        [("a", "n1", "n2", 500.0), ("b", "n2", "n1", 500.0)]
    )
    candidate = Bag(bearing=90, data=["a"])
    accepted = [Bag(bearing=270, data=["b"])]

    assert engine.RoadGraphEngine.is_loop_too_similar(None, context, candidate, accepted) is True


def test_an_empty_candidate_is_never_too_similar():
    context = make_similarity_context([("a", "n1", "n2", 500.0)])

    assert engine.RoadGraphEngine.is_loop_too_similar(None, context, Bag(bearing=None, data=[]), []) is False


def test_a_zero_length_candidate_is_never_too_similar():
    context = make_similarity_context([("a", "n1", "n2", 0.0)])
    candidate = Bag(bearing=90, data=["a"])

    assert engine.RoadGraphEngine.is_loop_too_similar(None, context, candidate, [candidate]) is False


# --------------------------------------------------------------------------------------
# 折返し点から周回を閉じる（復路探索）
# --------------------------------------------------------------------------------------


async def loop_context(world, monkeypatch):
    """往路レグと復路レグを持つ文脈（`select_loop_turnarounds`が作る状態と同じ形）。"""
    context = await prepared(world)
    inbound = engine.LegCostArrays(
        cost_lazy=np.array([10.0, 20.0, 30.0]),
        difficulty_array=np.zeros(3),
        axis_arrays={}, weight_sums=np.zeros(3), weights={}, axis_raw_arrays={},
        material_arrays={}, categorical_material_arrays={},
        travel_seconds_full=np.array([100.0, 200.0, 300.0]),
        travel_seconds_lazy=np.array([100.0, 200.0, 300.0]),
        cost_bins_lazy=np.array([[10.0, 20.0, 30.0], [11.0, 21.0, 31.0]]),
        travel_bins_lazy=np.array([[100.0, 200.0, 300.0], [100.0, 200.0, 300.0]]),
        bin_seconds=3600.0,
    )
    context.legs = [context.legs[0], inbound]
    monkeypatch.setattr(engine, "overlap_ratio", lambda a, b, lengths: 0.25)
    return context


def turnaround(node_id="n1", outbound=(0,), length_m=5000.0, bearing=90):
    return Bag(
        bearing=bearing,
        outbound_difficulty=1.0,
        data=engine._TurnaroundData(
            node_id=node_id, outbound_edge_indices=list(outbound), outbound_length_m=length_m
        ),
    )


async def test_return_search_penalises_the_outbound_edges_and_their_opposites(search_world, monkeypatch):
    """往路をそのまま引き返す復路を避ける。逆方向Edgeも同じ道なので一緒に上げる。"""
    context = await loop_context(search_world, monkeypatch)
    search_world.lazy.edge_index_by_node_pair[(1, 0)] = 2  # e2を「e0の逆方向」に見立てる
    seen = {}

    def fake_path(structure, cost_bins, heuristic, origin_states, destination, *rest):
        seen["costs"] = cost_bins.copy()
        return [1]

    monkeypatch.setattr(engine, "turn_expanded_shortest_path", bound(engine.turn_expanded_shortest_path, fake_path))

    await search_world.engine.trace_loop_from_turnaround(context, turnaround(outbound=(0,)))

    assert seen["costs"][0].tolist() == [80.0, 20.0, 240.0]


async def test_return_search_restores_the_shared_cost_array(search_world, monkeypatch):
    """コスト配列は全候補で共有する。戻し損ねると次の候補が上がったコストを見る。"""
    context = await loop_context(search_world, monkeypatch)
    before = context.legs[1].cost_bins_lazy.copy()
    monkeypatch.setattr(engine, "turn_expanded_shortest_path", bound(engine.turn_expanded_shortest_path, lambda *a: [1]))

    await search_world.engine.trace_loop_from_turnaround(context, turnaround(outbound=(0, 2)))

    assert context.legs[1].cost_bins_lazy.tolist() == before.tolist()


async def test_return_search_restores_the_cost_array_even_when_the_search_explodes(search_world, monkeypatch):
    context = await loop_context(search_world, monkeypatch)
    before = context.legs[1].cost_bins_lazy.copy()

    def explode(*args):
        raise RuntimeError("探索が落ちた")

    monkeypatch.setattr(engine, "turn_expanded_shortest_path", explode)

    with pytest.raises(RuntimeError):
        await search_world.engine.trace_loop_from_turnaround(context, turnaround())

    assert context.legs[1].cost_bins_lazy.tolist() == before.tolist()


async def test_return_search_uses_the_outbound_leg_when_no_inbound_was_composed(search_world, monkeypatch):
    context = await prepared(search_world)
    monkeypatch.setattr(engine, "overlap_ratio", lambda a, b, lengths: 0.1)
    seen = {}

    def fake_path(structure, cost_bins, *rest):
        seen["bins"] = cost_bins
        return [1]

    monkeypatch.setattr(engine, "turn_expanded_shortest_path", bound(engine.turn_expanded_shortest_path, fake_path))

    await search_world.engine.trace_loop_from_turnaround(context, turnaround())

    assert seen["bins"] is context.legs[0].cost_bins_lazy


async def test_closed_loop_keeps_the_outbound_edges_ahead_of_the_return(search_world, monkeypatch):
    context = await loop_context(search_world, monkeypatch)
    monkeypatch.setattr(engine, "turn_expanded_shortest_path", bound(engine.turn_expanded_shortest_path, lambda *a: [1, 2]))

    traced = await search_world.engine.trace_loop_from_turnaround(context, turnaround(outbound=(0,)))

    assert traced.data == ["e0", "e1", "e2"]
    assert traced.leg_of_edge == [0, 1, 1]
    assert traced.distance_km == 3.0
    assert traced.bearing == 90


@pytest.mark.parametrize("result, message", [(None, "no return path"), ([], "no edges")])
async def test_a_turnaround_without_a_usable_return_is_refused(search_world, monkeypatch, result, message):
    context = await loop_context(search_world, monkeypatch)
    monkeypatch.setattr(engine, "turn_expanded_shortest_path", bound(engine.turn_expanded_shortest_path, lambda *a: result))

    with pytest.raises(engine.RoutingError, match=message):
        await search_world.engine.trace_loop_from_turnaround(context, turnaround())


# --------------------------------------------------------------------------------------
# 時間最短の基準線
# --------------------------------------------------------------------------------------


async def test_fastest_route_searches_on_travel_time_not_on_axis_cost(search_world, monkeypatch):
    """軸の重みを一切使わない基準線。コスト配列を渡すと基準線でなくなる。"""
    context = await prepared(search_world)
    seen = {}

    def fake_path(structure, costs, heuristic, origin_states, destination, *rest):
        seen["costs"] = costs
        seen["rest"] = rest
        return [0, 1]

    monkeypatch.setattr(engine, "turn_expanded_shortest_path", fake_path)

    await search_world.engine.select_fastest_route(context, coords(37.0, 139.9))

    assert seen["costs"] is context.legs[0].travel_bins_lazy
    assert seen["rest"][0] is context.legs[0].travel_bins_lazy


async def test_fastest_route_splits_its_legs_by_time_not_by_distance(search_world, monkeypatch):
    """境目は時間で取る。距離で割ると、長く時間のかかる区間が帰路側の時刻帯で評価される。"""
    context = await prepared(search_world)
    context.legs[0].travel_seconds_lazy = np.array([10.0, 10.0, 100.0])
    monkeypatch.setattr(engine, "turn_expanded_shortest_path", bound(engine.turn_expanded_shortest_path, lambda *a: [0, 1, 2]))

    traced = await search_world.engine.select_fastest_route(context, coords(37.0, 139.9))

    assert traced.leg_of_edge == [0, 0, 0]


async def test_fastest_route_puts_the_boundary_after_the_edge_that_crosses_half(search_world, monkeypatch):
    context = await prepared(search_world)
    context.legs[0].travel_seconds_lazy = np.array([100.0, 100.0, 100.0])
    monkeypatch.setattr(engine, "turn_expanded_shortest_path", bound(engine.turn_expanded_shortest_path, lambda *a: [0, 1, 2]))

    traced = await search_world.engine.select_fastest_route(context, coords(37.0, 139.9))

    assert traced.leg_of_edge == [0, 0, 1]
    assert traced.distance_km == 3.0
    assert traced.bearing is None


async def test_fastest_route_follows_a_corrected_destination(search_world, monkeypatch):
    """目的地を補正したなら基準線も補正後へ向かう。片方だけ元の座標だと比較にならない。"""
    context = await prepared(search_world)
    context.destination_correction = coords(36.5, 139.5)
    asked = []
    monkeypatch.setattr(
        engine, "find_nearest_node_indexed",
        bound(engine.find_nearest_node_indexed, lambda index, point, **kwargs: asked.append(point) or "n2"),
    )
    monkeypatch.setattr(engine, "turn_expanded_shortest_path", bound(engine.turn_expanded_shortest_path, lambda *a: [0]))

    await search_world.engine.select_fastest_route(context, coords(37.0, 139.9))

    assert asked == [context.destination_correction]


async def test_fastest_route_is_none_when_the_destination_cannot_be_snapped(search_world, monkeypatch):
    context = await prepared(search_world)
    monkeypatch.setattr(engine, "find_nearest_node_indexed", bound(engine.find_nearest_node_indexed, lambda index, point, **kwargs: None))

    assert await search_world.engine.select_fastest_route(context, coords(37.0, 139.9)) is None


async def test_fastest_route_is_none_when_no_path_reaches_the_destination(search_world, monkeypatch):
    context = await prepared(search_world)
    monkeypatch.setattr(engine, "turn_expanded_shortest_path", bound(engine.turn_expanded_shortest_path, lambda *a: None))

    assert await search_world.engine.select_fastest_route(context, coords(37.0, 139.9)) is None


# --------------------------------------------------------------------------------------
# 所要時間の見積もり
# --------------------------------------------------------------------------------------


def make_duration_context(travel_seconds_full, turn_seconds=None, speed_kmh=36.0):
    graph = make_graph([("e0", "n0", "n1", 1000.0), ("e1", "n1", "n2", 2000.0)])
    lazy = make_lazy_graph(graph)
    structure = FakeTurnStructure(
        indptr=np.array([0, 2, 2]),
        target_state=np.array([5, 1]),
        turn_seconds=np.array([99.0, 7.0]) if turn_seconds is None else np.asarray(turn_seconds),
        edge_from=np.array([0, 1]), edge_to=np.array([1, 2]), state_count=2,
    )
    leg = engine.LegCostArrays(
        cost_lazy=np.zeros(2), difficulty_array=np.zeros(2),
        axis_arrays={}, weight_sums=np.zeros(2), weights={}, axis_raw_arrays={},
        material_arrays={}, categorical_material_arrays={},
        travel_seconds_full=np.asarray(travel_seconds_full, dtype=float),
        travel_seconds_lazy=np.asarray(travel_seconds_full, dtype=float),
        cost_bins_lazy=np.zeros((1, 2)), travel_bins_lazy=np.zeros((1, 2)), bin_seconds=np.inf,
    )
    return make_context(
        graph=graph, lazy_graph=lazy, turn_structure=structure, legs=[leg],
        full_edge_row={"e0": 0, "e1": 1}, composer=Bag(speed_kmh=speed_kmh),
    ), graph


def test_duration_is_the_travel_time_of_the_legs_plus_the_turn_waits(search_world, monkeypatch):
    """表示の所要時間は探索が使った配列をそのまま読む。別計算だと片方だけ直って食い違う。"""
    monkeypatch.setattr(engine, "kmh_to_ms", lambda kmh: kmh / 3.6)
    context, graph = make_duration_context([120.0, 240.0])
    edges = [graph.edges["e0"], graph.edges["e1"]]

    total = search_world.engine._estimate_duration_seconds(context, edges, [0, 0])

    assert total == 120.0 + 240.0 + 7.0


def test_duration_falls_back_to_the_cruising_speed_for_unreachable_edges(search_world, monkeypatch):
    """0にすると所要時間が実態より短く出る（除外区間を含む合成経路が来うる）。"""
    monkeypatch.setattr(engine, "kmh_to_ms", lambda kmh: kmh / 3.6)
    context, graph = make_duration_context([np.inf, 240.0], speed_kmh=36.0)
    edges = [graph.edges["e0"], graph.edges["e1"]]

    total = search_world.engine._estimate_duration_seconds(context, edges, [0, 0])

    assert total == 100.0 + 240.0 + 7.0


def test_duration_is_none_for_an_empty_path(search_world):
    context, _graph = make_duration_context([120.0, 240.0])

    assert search_world.engine._estimate_duration_seconds(context, [], []) is None


def test_turn_waits_are_zero_for_a_single_edge(search_world):
    context, graph = make_duration_context([120.0, 240.0])

    assert search_world.engine._turn_seconds_along(context, [graph.edges["e0"]]) == 0.0


def test_turn_waits_only_count_the_transition_actually_taken(search_world):
    """同じ区間から出る遷移は複数ある。経路が実際に通った1本だけを足す。"""
    context, graph = make_duration_context([120.0, 240.0], turn_seconds=[99.0, 7.0])

    total = search_world.engine._turn_seconds_along(context, [graph.edges["e0"], graph.edges["e1"]])

    assert total == 7.0


# --------------------------------------------------------------------------------------
# 候補の組み立て（実ジオメトリの取り直し・逆回りの採否・区間表示）
# --------------------------------------------------------------------------------------


async def test_geometry_is_fetched_once_for_every_candidate_together(search_world, monkeypatch):
    """候補ごとに問い合わせると、区間を共有するぶんだけ同じ行を何度も引くことになる。"""
    context = await prepared(search_world)
    built = []

    async def fake_build(ctx, traced, edges_in_path, start_time):
        built.append([edge.edge_id for edge in edges_in_path])
        return Bag(traced=traced)

    search_world.engine._build_best_candidate = fake_build
    traced = [Bag(data=["e0", "e1"], bearing=90), Bag(data=["e1", "e2"], bearing=270)]

    candidates = await search_world.engine.evaluate_loops(context, traced, NOW)

    assert search_world.graph_service.hydrate_calls == [["e0", "e1", "e2"]]
    assert built == [["e0", "e1"], ["e1", "e2"]]
    assert [c.traced for c in candidates] == traced


def elevation_context(world, attributes):
    return make_context(
        graph=world.graph,
        materials=Bag(elevation_attribute=lambda edge_id: attributes.get(edge_id)),
        lazy_graph=world.lazy,
    )


def test_elevation_by_edge_only_carries_the_edges_that_have_one(search_world):
    context = elevation_context(search_world, {"e0": FakeElevation("e0", elevation_gain_m=5.0)})
    edges = [search_world.graph.edges["e0"], search_world.graph.edges["e1"]]

    found = search_world.engine._elevation_by_edge(context, edges)

    assert set(found) == {"e0"}


async def test_a_waypoint_route_is_never_flipped(search_world, monkeypatch):
    """経由地ルートは訪問順序そのものが要件。逆回りは別のルートになる。"""
    context = elevation_context(search_world, {})
    monkeypatch.setattr(engine, "_reverse_traced_edges", lambda *a: pytest.fail("逆回りを作ってはいけない"))
    search_world.engine._build_candidate = bound(search_world.engine._build_candidate, lambda *a, **k: Bag(name="forward", segments=[]))

    result = await search_world.engine._build_best_candidate(
        context, Bag(bearing=None, leg_of_edge=[0]), [search_world.graph.edges["e0"]], NOW
    )

    assert result.name == "forward"


async def test_a_one_way_loop_stays_in_its_original_direction(search_world, monkeypatch):
    context = elevation_context(search_world, {})
    monkeypatch.setattr(engine, "_reverse_traced_edges", bound(engine._reverse_traced_edges, lambda *a: None))
    search_world.engine._build_candidate = bound(search_world.engine._build_candidate, lambda *a, **k: Bag(name="forward", segments=[]))

    result = await search_world.engine._build_best_candidate(
        context, Bag(bearing=90, leg_of_edge=[0]), [search_world.graph.edges["e0"]], NOW
    )

    assert result.name == "forward"


async def test_a_reversible_loop_keeps_the_easier_direction(search_world, monkeypatch):
    """逆走は勾配・風で評点が変わる。両方向を別候補として並べず、走りやすい方だけ残す。"""
    context = elevation_context(search_world, {})
    monkeypatch.setattr(engine, "_reverse_traced_edges", bound(engine._reverse_traced_edges, lambda *a: [search_world.graph.edges["e1"]]))
    monkeypatch.setattr(engine, "_reverse_elevation_by_edge", bound(engine._reverse_elevation_by_edge, lambda *a: {}))
    monkeypatch.setattr(engine, "distance_weighted_difficulty", lambda pairs: pairs[0][0])
    built = []

    def fake_build(ctx, traced, edges_in_path, attributes, start_time, leg_of_edge):
        built.append(leg_of_edge)
        difficulty = 9.0 if edges_in_path[0].edge_id == "e0" else 2.0
        return Bag(name=edges_in_path[0].edge_id, segments=[Bag(difficulty=difficulty, distance_km=1.0)])

    search_world.engine._build_candidate = fake_build

    result = await search_world.engine._build_best_candidate(
        context, Bag(bearing=90, leg_of_edge=[0, 1]), [search_world.graph.edges["e0"]], NOW
    )

    assert result.name == "e1"
    assert built == [[0, 1], [0, 1]]


def test_material_category_shares_are_folded_before_the_segments_are_aggregated(search_world, monkeypatch):
    """集約後に畳むと、割合がビンの粒度へ量子化される。"""
    detailed = [Bag(difficulty=1.0, distance_km=1.0), Bag(difficulty=2.0, distance_km=3.0)]
    categories = [{"cat_a": "paved"}, {}]
    folded = {}

    def merge(pairs):
        folded["pairs"] = list(pairs)
        return {"cat_a": {"paved": 1.0}}

    binned = engine.RouteSegmentDetail(
        start_latitude=35.0, start_longitude=139.0, end_latitude=35.2, end_longitude=139.2,
        cumulative_distance_km=4.0, distance_km=4.0,
    )
    monkeypatch.setattr(engine, "merge_material_category_shares", merge)
    monkeypatch.setattr(engine, "aggregate_segments_into_bins", lambda segments: [binned])
    monkeypatch.setattr(engine, "sum_or_none", lambda values: None)
    monkeypatch.setattr(engine, "min_or_none", lambda values: None)
    monkeypatch.setattr(engine, "max_or_none", lambda values: None)
    search_world.engine._build_segment_details = bound(search_world.engine._build_segment_details, lambda *a: (detailed, categories))
    search_world.engine._estimate_duration_seconds = bound(search_world.engine._estimate_duration_seconds, lambda *a: 1234.0)
    context = elevation_context(search_world, {})
    edges = [
        lean_edge("e0", "n0", "n1", geometry=[[35.0, 139.0], [35.1, 139.1]]),
        lean_edge("e1", "n1", "n2", geometry=[[35.1, 139.1], [35.2, 139.2]]),
    ]

    candidate = search_world.engine._build_candidate(
        context, Bag(bearing=90, distance_km=2.0), edges, {}, NOW, [0, 0]
    )

    assert folded["pairs"] == [(1.0, {"cat_a": "paved"}), (3.0, {})]
    assert candidate.segments == [binned]
    assert candidate.material_category_shares == {"cat_a": {"paved": 1.0}}
    assert candidate.node_ids == ["n0", "n1", "n2"]
    assert candidate.edge_ids == ["e0", "e1"]
    assert candidate.estimated_duration_seconds == 1234.0


# --------------------------------------------------------------------------------------
# 区間ごとの表示値
# --------------------------------------------------------------------------------------


def segment_leg(count=2, **overrides):
    defaults = dict(
        cost_lazy=np.zeros(count),
        difficulty_array=np.array([12.0, np.nan][:count]),
        axis_arrays={AXIS_STATIC: np.array([0.5, np.nan][:count])},
        weight_sums=np.ones(count),
        weights={AXIS_STATIC: 1.0},
        axis_raw_arrays={AXIS_STATIC: np.array([3.0, np.nan][:count])},
        material_arrays={MAT_STOP_A: np.array([2.0, np.nan][:count])},
        categorical_material_arrays={"cat_a": np.array(["paved", None][:count], dtype=object)},
        travel_seconds_full=np.zeros(count),
        travel_seconds_lazy=np.zeros(count),
        cost_bins_lazy=np.zeros((1, count)),
        travel_bins_lazy=np.zeros((1, count)),
        bin_seconds=np.inf,
    )
    defaults.update(overrides)
    return engine.LegCostArrays(**defaults)


@pytest.fixture
def segment_world(monkeypatch, search_world):
    monkeypatch.setattr(engine, "axis_contributions_at_row", lambda arrays, weights, sums, row: {AXIS_STATIC: 1.0})
    monkeypatch.setattr(engine, "displayed_material_ids", lambda weights, lens: {MAT_STOP_A, "cat_a", "gradient_percent"})
    return search_world


def segment_context(world, legs, edges):
    return make_context(
        graph=world.graph, legs=legs,
        full_edge_row={edge.edge_id: i for i, edge in enumerate(edges)},
        composer=Bag(_weights={AXIS_STATIC: 1.0}, _lens_axis_id=None, speed_kmh=20.0),
    )


def two_segment_edges():
    return [
        lean_edge("e0", "n0", "n1", distance_m=1000.0,
                  geometry=[[35.0, 139.0], [35.1, 139.1]]),
        lean_edge("e1", "n1", "n2", distance_m=2000.0,
                  geometry=[[35.1, 139.1]]),
    ]


def test_segment_details_accumulate_distance_and_arrival_time(segment_world):
    """到達予想時刻は累積距離から出す。1区間ずれると画面の時刻が全体的にずれる。"""
    edges = two_segment_edges()
    context = segment_context(segment_world, [segment_leg()], edges)

    segments, _categories = segment_world.engine._build_segment_details(edges, {}, context, NOW, [0, 0])

    assert [s.cumulative_distance_km for s in segments] == [0.0, 1.0]
    assert [s.distance_km for s in segments] == [1.0, 2.0]
    assert segments[0].estimated_arrival_time == NOW.isoformat()
    assert segments[1].estimated_arrival_time == (NOW + timedelta(hours=1.0 / 20.0)).isoformat()


def test_segment_details_drop_values_the_leg_has_no_data_for(segment_world):
    """欠損を0として出すと、データが無いことと「良い」が画面で区別できなくなる。"""
    edges = two_segment_edges()
    context = segment_context(segment_world, [segment_leg()], edges)

    (first, second), categories = segment_world.engine._build_segment_details(edges, {}, context, NOW, [0, 0])

    assert first.axis_difficulties == {AXIS_STATIC: 0.5}
    assert first.axis_raw_values == {AXIS_STATIC: 3.0}
    assert first.difficulty == 12.0
    assert first.material_values == {MAT_STOP_A: 2.0}
    assert second.axis_difficulties == {}
    assert second.axis_raw_values == {}
    assert second.difficulty is None
    assert second.material_values == {}
    assert categories == [{"cat_a": "paved"}, {}]


def test_segment_details_take_the_gradient_from_the_elevation_attribute(segment_world):
    edges = two_segment_edges()
    context = segment_context(segment_world, [segment_leg()], edges)
    attributes = {"e0": FakeElevation("e0", average_grade=3.46)}

    (first, second), _categories = segment_world.engine._build_segment_details(edges, attributes, context, NOW, [0, 0])

    assert first.material_values["gradient_percent"] == 3.5
    assert "gradient_percent" not in second.material_values


def test_segment_details_omit_materials_the_screen_is_not_showing(monkeypatch, segment_world):
    """出す材料は重みとレンズから決まる。無関係な材料まで載せるとペイロードが膨らむ。"""
    monkeypatch.setattr(engine, "displayed_material_ids", lambda weights, lens: set())
    edges = two_segment_edges()
    context = segment_context(segment_world, [segment_leg()], edges)
    attributes = {"e0": FakeElevation("e0", average_grade=3.4)}

    (first, _second), categories = segment_world.engine._build_segment_details(
        edges, attributes, context, NOW, [0, 0]
    )

    assert first.material_values == {}
    assert categories == [{}, {}]


def test_segment_details_read_the_leg_the_edge_was_searched_on(segment_world):
    """探索コストと表示を一致させる。別レグの配列を読むと違う時刻の風の値が出る。"""
    edges = two_segment_edges()
    inbound = segment_leg(difficulty_array=np.array([77.0, 88.0]))
    context = segment_context(segment_world, [segment_leg(), inbound], edges)

    (first, second), _categories = segment_world.engine._build_segment_details(edges, {}, context, NOW, [0, 1])

    assert first.difficulty == 12.0
    assert second.difficulty == 88.0


def test_segment_details_have_no_geometry_when_the_edge_is_a_single_point(segment_world):
    """2点未満は線にならない。空のLineStringを配るとフロントが描けない。"""
    edges = two_segment_edges()
    context = segment_context(segment_world, [segment_leg()], edges)

    (first, second), _categories = segment_world.engine._build_segment_details(edges, {}, context, NOW, [0, 0])

    assert first.geometry == {"type": "LineString", "coordinates": [[139.0, 35.0], [139.1, 35.1]]}
    assert second.geometry is None
    assert (second.start_latitude, second.start_longitude) == (35.1, 139.1)
    assert (second.end_latitude, second.end_longitude) == (35.1, 139.1)


# --------------------------------------------------------------------------------------
# 折返し点の選定（リングの上下限・難易度の逆算・間引き）
# --------------------------------------------------------------------------------------


RING_NODE_IDS = ["r0", "r1", "r2", "r3", "r4", "r5"]
RING_LENGTHS = [0.0, 8000.0, 9100.0, 9400.0, 9800.0, 10000.0]


class DiverseRecorder:
    """`select_diverse_by_overlap`の代役。検討対象へ渡された候補をそのまま採る。"""

    def __init__(self, limit=None):
        self.tie_groups = None
        self.thresholds = None
        self.args = None
        self.kwargs = None
        self._limit = limit

    def __call__(self, ranked, path_fn, lengths, thresholds, limit, *rest, **kwargs):
        self.thresholds = list(thresholds)
        self.args = (list(ranked), path_fn, lengths, limit, rest)
        self.kwargs = kwargs
        self.tie_groups = kwargs.get("tie_groups")
        candidates = [node for group in (self.tie_groups or []) for node in group] or list(ranked)
        for node_index in candidates:
            path_fn(node_index)   # 本物も経路を引いて重複率を見る。二度引かれることを再現する。
        return candidates[: (self._limit if self._limit is not None else limit)]


@pytest.fixture
def ring_world(monkeypatch, cache, composer_world):
    graph = make_graph(
        [("e0", "r0", "r1", 1000.0), ("e1", "r1", "r2", 1000.0), ("e2", "r2", "r0", 1000.0)],
        node_ids=RING_NODE_IDS,
        nodes=[lean_node(node_id, 35.0 + i * 0.05, 139.0) for i, node_id in enumerate(RING_NODE_IDS)],
    )
    lazy = make_lazy_graph(graph, node_ids=RING_NODE_IDS)
    statics = FakeStatics(
        csr=FakeCsr(indptr=np.array([0, 1, 2, 3, 3, 3, 3]), entry_edge_index=np.array([0, 1, 2]), node_count=6),
        edge_length_m=np.full(3, 1000.0),
    )
    tree = FakeTree(
        node_cost=np.array([0.0, 120.0, 120.0, 120.0, 120.0, 120.0]),
        node_length_m=np.array(RING_LENGTHS),
        node_seconds=np.array([1.0, 100.0, 100.0, 100.0, 100.0, 100.0]),
        node_best_state=np.zeros(6, dtype=np.int64),
    )
    diverse = DiverseRecorder()

    monkeypatch.setattr(engine, "build_turn_expanded_tree", bound(engine.build_turn_expanded_tree, lambda *a, **k: tree))
    monkeypatch.setattr(engine, "turn_expanded_path_edge_indices", lambda t, node_index: [0])
    monkeypatch.setattr(engine, "select_diverse_by_overlap", diverse)
    monkeypatch.setattr(engine, "pareto_layer_index", bound(engine.pareto_layer_index, lambda a, b, **k: np.zeros(len(a), dtype=np.int64)))
    monkeypatch.setattr(engine, "bearing_between_array", lambda origin, lat, lon: np.zeros(len(lat)))
    monkeypatch.setattr(engine, "bearing_between", lambda origin, node: 45.0)
    monkeypatch.setattr(engine, "haversine_distance_km_array", lambda lat, lon, origin: np.full(len(lat), 5.0))
    monkeypatch.setattr(engine, "tuning_value", lambda key: 4.0)

    composer = make_composer(make_score_matrix(count=3, edge_ids=["e0", "e1", "e2"]))
    context = make_context(
        graph=graph, lazy_graph=lazy, statics=statics, turn_structure=Bag(state_count=3, target_state=[0]),
        composer=composer, legs=[composer.compose("outbound", coords(35.0, 139.0), 0.0, +1)],
        origin_node="r0", origin_index=0,
        node_lat=np.array([graph.nodes[n].latitude for n in RING_NODE_IDS]),
        node_lon=np.array([graph.nodes[n].longitude for n in RING_NODE_IDS]),
        full_edge_row={"e0": 0, "e1": 1, "e2": 2},
    )
    return Bag(
        graph=graph, lazy=lazy, statics=statics, tree=tree, diverse=diverse, context=context,
        cache=cache, engine=make_engine(FakeGraphService(None), FakeWeatherService()),
    )


async def test_the_ring_is_the_outbound_length_that_can_close_into_the_target_loop(ring_world):
    """復路は往路と同程度以上に長くなる。その比で割り戻した幅だけをリングにする。"""
    await ring_world.engine.select_loop_turnarounds(ring_world.context, 20.0, 2.0, 4)

    assert sorted(node for group in ring_world.diverse.tie_groups for node in group) == [2, 3]


async def test_equally_difficult_turnarounds_are_tried_from_the_ring_centre_outwards(ring_world):
    """周回では距離は「短いほど良い」ではなく「目標に近いほど良い」。"""
    await ring_world.engine.select_loop_turnarounds(ring_world.context, 20.0, 2.0, 4)

    # リング中心は20km÷2.15≒9302m。9400mの方が9100mより中心に近い。
    assert [node for group in ring_world.diverse.tie_groups for node in group] == [3, 2]


async def test_the_ring_falls_back_to_half_the_target_when_the_bounds_invert(ring_world):
    """許容が狭いと比から作った下限が上限を追い越す。そのまま使うとリングが空になる。"""
    await ring_world.engine.select_loop_turnarounds(ring_world.context, 20.0, 0.5, 4)

    assert [node for group in ring_world.diverse.tie_groups for node in group] == [4, 5]


async def test_the_origin_is_never_its_own_turnaround(ring_world):
    ring_world.tree.node_length_m = np.array([9200.0, 8000.0, 9100.0, 9400.0, 9800.0, 10000.0])

    await ring_world.engine.select_loop_turnarounds(ring_world.context, 20.0, 2.0, 4)

    assert 0 not in [node for group in ring_world.diverse.tie_groups for node in group]


async def test_no_turnarounds_when_nothing_is_at_the_right_distance(ring_world):
    ring_world.tree.node_length_m = np.zeros(6)

    assert await ring_world.engine.select_loop_turnarounds(ring_world.context, 20.0, 2.0, 4) == []


async def test_turnaround_difficulty_is_read_back_out_of_the_cost(ring_world):
    """コスト式`所要時間 × (1 + P × difficulty/100)`の逆算。一覧に出る往路の難易度になる。"""
    turnarounds = await ring_world.engine.select_loop_turnarounds(ring_world.context, 20.0, 2.0, 4)

    assert [t.outbound_difficulty for t in turnarounds] == [20.0, 20.0]


async def test_turnaround_difficulty_is_flat_when_difficulty_is_switched_off(ring_world):
    """P=0はコスト＝所要時間。難易度を一切考慮しないので全候補同点になる。"""
    ring_world.engine._penalty_strength = 0.0

    turnarounds = await ring_world.engine.select_loop_turnarounds(ring_world.context, 20.0, 2.0, 4)

    assert [t.outbound_difficulty for t in turnarounds] == [0.0, 0.0]


async def test_turnaround_difficulty_of_an_unreachable_cost_is_not_nan(ring_world):
    """NaNのまま一覧へ出すと、並べ替えでも表示でも扱えない値が画面に届く。"""
    ring_world.tree.node_seconds = np.zeros(6)

    turnarounds = await ring_world.engine.select_loop_turnarounds(ring_world.context, 20.0, 2.0, 4)

    assert [t.outbound_difficulty for t in turnarounds] == [0.0, 0.0]


async def test_turnaround_bearing_wraps_around_north(ring_world, monkeypatch):
    monkeypatch.setattr(engine, "bearing_between", lambda origin, node: 359.7)

    turnarounds = await ring_world.engine.select_loop_turnarounds(ring_world.context, 20.0, 2.0, 4)

    assert [t.bearing for t in turnarounds] == [0, 0]


async def test_a_turnaround_without_a_recoverable_outbound_path_is_dropped(ring_world, monkeypatch):
    monkeypatch.setattr(
        engine, "turn_expanded_path_edge_indices", lambda t, node_index: [] if node_index == 2 else [0]
    )

    turnarounds = await ring_world.engine.select_loop_turnarounds(ring_world.context, 20.0, 2.0, 4)

    assert [t.data.node_id for t in turnarounds] == ["r3"]


async def test_turnaround_selection_composes_the_inbound_leg(ring_world):
    """復路レグは探索が作る。用意しないと`trace_loop_from_turnaround`が往路を使い回す。"""
    await ring_world.engine.select_loop_turnarounds(ring_world.context, 20.0, 2.0, 4)

    assert len(ring_world.context.legs) == 2


async def test_turnaround_selection_relaxes_the_overlap_threshold_when_the_pool_stays_empty(ring_world):
    """閾値を昇順に渡し、埋まらなかったときの緩和までを1回の呼び出しで行う。"""
    await ring_world.engine.select_loop_turnarounds(ring_world.context, 20.0, 2.0, 4)

    assert ring_world.diverse.thresholds == [
        engine.TURNAROUND_MAX_OVERLAP_RATIO, engine.TURNAROUND_RELAXED_OVERLAP_RATIO
    ]


async def test_turnaround_selection_thins_out_neighbours_of_what_it_already_took(ring_world):
    """近接Nodeは同じ周回の変種にしかならない。間引かないと似た周回が一覧を埋める。"""
    await ring_world.engine.select_loop_turnarounds(ring_world.context, 20.0, 2.0, 4)
    far_enough = ring_world.diverse.args[4][0]

    # r2(35.10) と r3(35.15) は約5.5km離れており、r2 と r2 自身は0km。
    assert far_enough(3, [2]) is True
    assert far_enough(2, [2]) is False


async def test_equally_difficult_turnarounds_are_spread_by_bearing_as_they_are_taken(ring_world, monkeypatch):
    """同点グループの試行順は、採用のたびに採用済みとの方位角距離で決め直す。"""
    bearings = {35.05: 0.0, 35.1: 10.0, 35.15: 180.0, 35.2: 90.0, 35.25: 45.0}
    monkeypatch.setattr(
        engine, "bearing_between_array",
        lambda origin, lat, lon: np.array([bearings[round(float(v), 2)] for v in lat]),
    )
    await ring_world.engine.select_loop_turnarounds(ring_world.context, 20.0, 4.0, 5)
    prefer = ring_world.diverse.kwargs["prefer"]

    # 採用済みr1は方位0度。残りr2=10度・r3=180度・r4=90度なら、遠い順に試す。
    assert prefer([2, 3, 4], [1]) == [3, 4, 2]


async def test_turnaround_selection_learns_the_detour_ratio_of_this_area(ring_world):
    """直線距離を走行時間へ直す係数。目的地ルートの到着予定時刻がこれを読む。"""
    await ring_world.engine.select_loop_turnarounds(ring_world.context, 20.0, 2.0, 4)

    # リング上の2点（9100m・9400m）の直線距離はどちらも5km。その比の中央値。
    assert ring_world.cache.detour_ratios[TILES] == pytest.approx(1.85)


# --------------------------------------------------------------------------------------
# 経由Nodeによる代替経路（目的地ルート）
# --------------------------------------------------------------------------------------


VIA_NODE_IDS = ["v0", "v1", "v2", "v3"]
VIA_EDGES = [
    ("e0", "v0", "v1", 1000.0),
    ("e1", "v1", "v3", 1000.0),
    ("e2", "v0", "v2", 1500.0),
    ("e3", "v2", "v3", 1500.0),
    ("e4", "v3", "v1", 1000.0),
]


@pytest.fixture
def via_world(monkeypatch, cache, composer_world):
    graph = make_graph(
        VIA_EDGES, node_ids=VIA_NODE_IDS,
        nodes=[lean_node(node_id, 35.0 + i * 0.01, 139.0) for i, node_id in enumerate(VIA_NODE_IDS)],
    )
    lazy = make_lazy_graph(graph, node_ids=VIA_NODE_IDS)
    statics = FakeStatics(
        csr=FakeCsr(indptr=np.array([0, 2, 3, 4, 5]), entry_edge_index=np.array([0, 2, 1, 3, 4]), node_count=4),
        edge_length_m=np.array([1000.0, 1000.0, 1500.0, 1500.0, 1000.0]),
    )
    structure = FakeTurnStructure(
        indptr=np.array([0, 1, 2, 3, 4, 5]),
        target_state=np.array([1, 4, 3, 4, 1]),
        turn_seconds=np.zeros(5),
        edge_from=np.array([0, 1, 0, 2, 3]),
        edge_to=np.array([1, 3, 2, 3, 1]),
        state_count=5,
    )
    forward = FakeTree(
        node_cost=np.array([0.0, 50.0, 60.0, 90.0]),
        node_length_m=np.array([0.0, 1000.0, 1500.0, 900.0]),
        node_seconds=np.array([0.0, 40.0, 50.0, 60.0]),
        node_best_state=np.array([-1, 0, 2, 4]),
    )
    backward = FakeTree(
        node_cost=np.array([120.0, 50.0, 70.0, 0.0]),
        node_length_m=np.array([2000.0, 1000.0, 1500.0, 0.0]),
        node_seconds=np.array([90.0, 40.0, 50.0, 0.0]),
        node_best_state=np.array([1, 1, 3, -1]),
    )
    junction = FakeJunction(
        cost=np.array([np.inf, 100.0, 130.0, np.inf]),
        length_m=np.array([0.0, 1000.0, 3000.0, 0.0]),
        seconds=np.array([0.0, 80.0, 100.0, 0.0]),
        forward_state=np.array([-1, 0, 2, -1], dtype=np.int64),
        backward_state=np.array([-1, 1, 3, -1], dtype=np.int64),
    )
    forward_paths = {0: [0], 2: [2], 4: [0, 1]}
    backward_paths = {1: [1], 3: [3]}
    diverse = DiverseRecorder()

    def fake_tree(*args, **kwargs):
        return backward if kwargs.get("reverse") else forward

    monkeypatch.setattr(engine, "build_turn_expanded_tree", bound(engine.build_turn_expanded_tree, fake_tree))
    monkeypatch.setattr(engine, "combine_forward_backward_at_nodes", bound(engine.combine_forward_backward_at_nodes, lambda *a: junction))
    monkeypatch.setattr(engine, "turn_expanded_path_from_state", lambda tree, state: forward_paths.get(state))
    monkeypatch.setattr(engine, "turn_expanded_path_from_state_to_source", lambda tree, state: backward_paths.get(state, []))
    monkeypatch.setattr(engine, "select_diverse_by_overlap", diverse)
    monkeypatch.setattr(engine, "pareto_layer_index", bound(engine.pareto_layer_index, lambda a, b, **k: np.zeros(len(a), dtype=np.int64)))
    monkeypatch.setattr(engine, "haversine_distance_km", lambda a, b: 4.0)
    monkeypatch.setattr(engine, "haversine_distance_km_array", lambda lat, lon, origin: np.full(len(lat), 2.0))
    monkeypatch.setattr(engine, "estimate_passage_hours", bound(engine.estimate_passage_hours, lambda *a, **k: np.full(5, 9.0)))
    monkeypatch.setattr(engine, "find_nearest_node_indexed", bound(engine.find_nearest_node_indexed, lambda index, point, **kwargs: "v3"))

    composer = make_composer(make_score_matrix(count=5, edge_ids=[spec[0] for spec in VIA_EDGES]))
    context = make_context(
        graph=graph, lazy_graph=lazy, statics=statics, turn_structure=structure, composer=composer,
        legs=[composer.compose("outbound", coords(35.0, 139.0), 0.0, +1)],
        origin_node="v0", origin_index=0,
        node_lat=np.array([graph.nodes[n].latitude for n in VIA_NODE_IDS]),
        node_lon=np.array([graph.nodes[n].longitude for n in VIA_NODE_IDS]),
        full_edge_row={spec[0]: i for i, spec in enumerate(VIA_EDGES)},
    )
    return Bag(
        graph=graph, lazy=lazy, forward=forward, backward=backward, junction=junction, diverse=diverse,
        context=context, cache=cache, forward_paths=forward_paths, backward_paths=backward_paths,
        engine=make_engine(FakeGraphService(None), FakeWeatherService()),
    )


DESTINATION = coords(35.03, 139.0)


async def test_via_nodes_are_empty_when_the_destination_is_off_the_routable_graph(via_world, monkeypatch):
    monkeypatch.setattr(engine, "find_nearest_node_indexed", bound(engine.find_nearest_node_indexed, lambda index, point, **kwargs: None))

    assert await via_world.engine.select_via_nodes(via_world.context, DESTINATION, 3) == []


async def test_an_isolated_destination_is_moved_to_the_nearest_reachable_node(via_world, monkeypatch):
    """タップ先が本線から孤立した小塊だと、後ろ向き木が起点と重ならず毎回0件になる。"""
    via_world.forward.node_cost = np.array([0.0, 50.0, 60.0, np.inf])
    snapped = iter(["v3", "v1"])
    monkeypatch.setattr(engine, "find_nearest_node_indexed", bound(engine.find_nearest_node_indexed, lambda index, point, **kwargs: next(snapped)))

    await via_world.engine.select_via_nodes(via_world.context, DESTINATION, 3)

    assert via_world.context.destination_correction == engine.Coordinates(latitude=35.01, longitude=139.0)


async def test_a_failure_at_the_origin_is_named_as_such(via_world, monkeypatch):
    """0件の原因が起点側なら、目的地を名指ししても調査が空振りする。"""
    via_world.forward.node_cost = np.full(4, np.inf)
    monkeypatch.setattr(engine, "find_nearest_node_indexed", lambda index, point, **kwargs: "v3" if "predicate" not in kwargs else None)

    assert await via_world.engine.select_via_nodes(via_world.context, DESTINATION, 3) == []
    assert via_world.context.no_candidates_side == "origin"


async def test_a_failure_only_near_the_destination_is_named_as_such(via_world, monkeypatch):
    via_world.forward.node_cost = np.array([0.0, 50.0, 60.0, np.inf])
    monkeypatch.setattr(engine, "find_nearest_node_indexed", lambda index, point, **kwargs: "v3" if "predicate" not in kwargs else None)

    assert await via_world.engine.select_via_nodes(via_world.context, DESTINATION, 3) == []
    assert via_world.context.no_candidates_side == "destination"


async def test_via_nodes_are_empty_when_nothing_joins_the_two_trees(via_world):
    via_world.junction.cost = np.full(4, np.inf)
    via_world.forward.node_best_state = np.array([-1, -1, -1, -1])

    assert await via_world.engine.select_via_nodes(via_world.context, DESTINATION, 3) == []


async def test_going_straight_to_the_destination_is_itself_a_candidate(via_world):
    """繋ぎ目は「入る区間×出る区間」の対で作るため、そこで終わる経路は現れない。"""
    await via_world.engine.select_via_nodes(via_world.context, DESTINATION, 3)

    assert via_world.junction.cost[3] == 90.0
    assert via_world.junction.backward_state[3] == -1


async def test_candidates_longer_than_the_allowed_stretch_are_dropped(via_world):
    """伸び率の上限を外すと、遠回りするほど平均difficultyが下がるぶん上位を占める。"""
    await via_world.engine.select_via_nodes(via_world.context, DESTINATION, 3)

    assert sorted(via_world.diverse.args[0]) == [1, 3]


async def test_the_lowest_cost_route_is_always_offered_first(via_world):
    """合成コスト最小の経路が、難易度順では上位に来ないことがある。"""
    await via_world.engine.select_via_nodes(via_world.context, DESTINATION, 3)

    assert via_world.diverse.args[0][0] == 3


async def test_a_candidate_that_doubles_back_on_itself_is_rejected(via_world):
    """前向き・後ろ向きが同じ物理区間を通る経路は、行って戻る形で経路として成立しない。"""
    via_world.forward_paths[0] = [1]     # v1へ入る前向き経路が e1(v1-v3) を使う
    via_world.backward_paths[1] = [4]    # v1からの後ろ向き経路が e4(v3-v1) を使う

    traced = await via_world.engine.select_via_nodes(via_world.context, DESTINATION, 3)

    assert [t.distance_km for t in traced] == [2.0]


async def test_a_via_node_whose_outbound_path_cannot_be_recovered_is_dropped(via_world):
    """経路が復元できないNodeは候補にならない（前向き木が届いていないのと同じ）。"""
    via_world.forward_paths[0] = None

    traced = await via_world.engine.select_via_nodes(via_world.context, DESTINATION, 3)

    assert [t.leg_of_edge for t in traced] == [[0, 0]]


async def test_a_via_node_route_changes_leg_at_the_node_it_passes_through(via_world):
    traced = await via_world.engine.select_via_nodes(via_world.context, DESTINATION, 3)
    by_legs = {tuple(t.leg_of_edge): t for t in traced}

    assert (0, 0) in by_legs      # 目的地で終わる経路（後ろ向きの区間が無い）
    assert (0, 1) in by_legs      # v1を経由する経路
    assert by_legs[(0, 1)].data == ["e0", "e1"]
    assert by_legs[(0, 1)].bearing is None


async def test_via_node_candidates_are_cut_off_after_they_are_ranked(via_world, monkeypatch):
    """Node index順に先に切ると、良い候補が後ろのindexに居るだけで検討対象から外れる。"""
    monkeypatch.setattr(engine, "MAX_VIA_NODE_CANDIDATES_EXAMINED", 1)
    via_world.junction.seconds[1] = 50.0   # v1経由を最も難易度の高い候補にする

    await via_world.engine.select_via_nodes(via_world.context, DESTINATION, 3)

    assert via_world.diverse.args[0] == [3]


async def test_the_lowest_cost_route_survives_the_cut_off(via_world, monkeypatch):
    """打ち切りで落ちても、合成コスト最小の経路だけは結果に含まれる。"""
    monkeypatch.setattr(engine, "MAX_VIA_NODE_CANDIDATES_EXAMINED", 1)

    await via_world.engine.select_via_nodes(via_world.context, DESTINATION, 3)

    assert via_world.diverse.args[0] == [3, 1]


async def test_via_node_difficulty_is_flat_when_difficulty_is_switched_off(via_world):
    via_world.engine._penalty_strength = 0.0

    await via_world.engine.select_via_nodes(via_world.context, DESTINATION, 3)

    assert sorted(via_world.diverse.args[0]) == [1, 3]


async def test_the_backward_tree_is_given_the_measured_passage_time_where_it_exists(via_world):
    """直線距離からの推定より実態に近い。前向き木が届かない区間だけ推定へ落とす。"""
    via_world.forward.node_seconds = np.array([0.0, 3600.0, np.inf, 7200.0])
    recorded = {}
    original = via_world.context.composer.compose

    def record(label, anchor, offset, direction, **kwargs):
        if label == "inbound":
            recorded["passage"] = np.asarray(kwargs["passage_hours"]).copy()
        return original(label, anchor, offset, direction, **kwargs)

    via_world.context.composer.compose = record

    await via_world.engine.select_via_nodes(via_world.context, DESTINATION, 3)

    # edge_from=[0,1,0,2,3] → 秒は[0, 3600, 0, inf, 7200]。有限でない行だけ推定値9.0。
    assert recorded["passage"].tolist() == [0.0, 1.0, 0.0, 9.0, 2.0]


async def test_via_node_selection_relaxes_the_overlap_threshold_when_the_pool_stays_empty(via_world):
    await via_world.engine.select_via_nodes(via_world.context, DESTINATION, 3)

    assert via_world.diverse.thresholds == [
        engine.VIA_NODE_MAX_OVERLAP_RATIO, engine.VIA_NODE_RELAXED_OVERLAP_RATIO
    ]


async def test_via_node_selection_composes_the_inbound_leg(via_world):
    await via_world.engine.select_via_nodes(via_world.context, DESTINATION, 3)

    assert len(via_world.context.legs) == 2


# --------------------------------------------------------------------------------------
# 実ジオメトリの取り直しと、並べ替えの決定性
# --------------------------------------------------------------------------------------


def hydrate_with_geometry(graph_service, shape_of, distance_m=None):
    """取り直した区間を、探索用グラフの空プレースホルダと区別できる形で返すようにする。

    `shape_of`はedge_idから形状点列を返す。`distance_m`を渡すと距離も探索用グラフの値から変える。
    """

    async def hydrate(edges):
        graph_service.hydrate_calls.append([edge.edge_id for edge in edges])
        return {
            edge.edge_id: replace(
                edge,
                geometry=shape_of(edge.edge_id),
                distance_m=edge.distance_m if distance_m is None else distance_m,
            )
            for edge in edges
        }

    graph_service.get_edges_with_geometry = hydrate


async def test_preview_draws_the_refetched_shape_not_the_search_graph_placeholder(search_world, monkeypatch):
    """探索用グラフのEdgeはgeometryが空。そのまま配ると地図に線が出ない。"""
    monkeypatch.setattr(engine, "turn_expanded_shortest_path", bound(engine.turn_expanded_shortest_path, lambda *a: [0, 1]))
    hydrate_with_geometry(search_world.graph_service, lambda edge_id: [[35.0, 139.0], [35.5, 139.5]], 500.0)

    segment = await search_world.engine.preview_segment(
        coords(35.0, 139.0), coords(35.2, 139.2), now=NOW
    )

    assert segment.geometry["coordinates"] == [[139.0, 35.0], [139.5, 35.5], [139.0, 35.0], [139.5, 35.5]]
    assert segment.distance_km == 1.0


async def test_candidates_are_built_from_the_refetched_edges(search_world):
    context = await prepared(search_world)
    hydrate_with_geometry(search_world.graph_service, lambda edge_id: [[35.0, 139.0], [35.5, 139.5]], 500.0)
    built = []

    async def fake_build(ctx, traced, edges_in_path, start_time):
        built.append([edge.geometry for edge in edges_in_path])
        return Bag()

    search_world.engine._build_best_candidate = fake_build

    await search_world.engine.evaluate_loops(context, [Bag(data=["e0"], bearing=90)], NOW)

    assert built == [[[[35.0, 139.0], [35.5, 139.5]]]]


async def test_tied_via_node_candidates_keep_a_stable_order(via_world):
    """同じリクエストが毎回違うルートを返すと、区間の乗り換えで送り返すidが指す先が変わる。"""
    via_world.junction.length_m[2] = 1000.0
    via_world.junction.seconds[2] = 104.0   # v1・v2をdifficulty 25.0で同点にする

    await via_world.engine.select_via_nodes(via_world.context, DESTINATION, 3)

    assert via_world.diverse.args[0] == [3, 1, 2]


async def test_a_dominated_turnaround_is_never_tried_before_a_non_dominated_one(ring_world, monkeypatch):
    """同じdifficultyでも層が違えば別グループ。混ぜると劣解が非劣解より先に試されうる。"""
    monkeypatch.setattr(engine, "pareto_layer_index", bound(engine.pareto_layer_index, lambda a, b, **k: np.array([0, -1])))

    await ring_world.engine.select_loop_turnarounds(ring_world.context, 20.0, 2.0, 4)

    assert ring_world.diverse.tie_groups == [[2], [3]]
