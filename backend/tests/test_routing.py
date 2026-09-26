"""`app/domain/routing.py`——Road Graphのトポロジと計算済みEdge Costだけで経路を探す層。

ここで見ないもの:
- Edge Costの中身（勾配・路面・風がどう秒へ化けるか） → `domain/evaluation.py`側
- 道路網全体の配列の作り方・範囲の切り出し → `test_road_network*.py`
- 較正値そのものの妥当性（左折が何秒か） → `domain/tuning.py`側
- 候補ルートの並べ方・返し方 → `route_generator`側

**対象の入力は番号の配列だが、テストは名前で書く。** `make_graph`がノードと区間に名前を付けた
小さな道路網を配列へ直し（区間の行は渡した順）、`lazy_of`・`build_all`が探索用グラフの区間の番号と
名前を結ぶ。値はこのモジュールが読む列（位置・端点・距離・方位）だけを指定する。
"""
import dataclasses
import math
from typing import NamedTuple

import numba
import numpy as np
import pytest

from app.domain import routing
from app.domain.route import Coordinates


class EdgeSpec(NamedTuple):
    from_node_id: str
    to_node_id: str
    distance_m: float


@dataclasses.dataclass
class Net:
    """名前付きの小さな道路網と、それを直した配列（区間の行は渡した順）。"""

    node_ids: list[str]
    node_id_to_index: dict[str, int]
    # 行の順の区間の名前。
    edge_ids: list[str]
    edges: dict[str, EdgeSpec]
    latitude: np.ndarray
    longitude: np.ndarray
    edge_from: np.ndarray
    edge_to: np.ndarray
    distance_m: np.ndarray
    # 方位を持たない区間はNaN。
    bearing_deg: np.ndarray


def make_graph(nodes, edges):
    """`nodes`は`{node_id: (緯度, 経度)}`、`edges`は`{edge_id: (始点, 終点[, 距離m[, 方位]])}`。"""
    node_ids = list(nodes)
    index = {node_id: i for i, node_id in enumerate(node_ids)}
    specs = {edge_id: _edge(*spec) for edge_id, spec in edges.items()}
    bearings = [spec[3] if len(spec) > 3 and spec[3] is not None else math.nan for spec in edges.values()]
    return Net(
        node_ids=node_ids,
        node_id_to_index=index,
        edge_ids=list(edges),
        edges={edge_id: EdgeSpec(*spec[:3]) for edge_id, spec in specs.items()},
        latitude=np.array([lat for lat, _ in nodes.values()], dtype=float),
        longitude=np.array([lon for _, lon in nodes.values()], dtype=float),
        edge_from=np.array([index[spec[0]] for spec in specs.values()], dtype=np.int64),
        edge_to=np.array([index[spec[1]] for spec in specs.values()], dtype=np.int64),
        distance_m=np.array([spec[2] for spec in specs.values()], dtype=float),
        bearing_deg=np.array(bearings, dtype=float),
    )


def _edge(from_node_id, to_node_id, distance_m=100.0, bearing_deg=None):
    return (from_node_id, to_node_id, distance_m, bearing_deg)


@dataclasses.dataclass
class NamedLazy:
    """探索用グラフと、その区間の番号順の名前。"""

    graph: routing.LazyRoadGraph
    edge_ids: list[str]
    node_id_to_index: dict[str, int]
    index_to_node_id: list[str]

    @property
    def node_count(self):
        return self.graph.node_count


def lazy_of(net):
    graph = routing.build_lazy_road_graph(net.edge_from, net.edge_to, len(net.node_ids))
    return NamedLazy(
        graph=graph,
        edge_ids=[net.edge_ids[row] for row in graph.edge_rows.tolist()],
        node_id_to_index=net.node_id_to_index,
        index_to_node_id=net.node_ids,
    )


def coords(latitude, longitude):
    return Coordinates(latitude=latitude, longitude=longitude)


# ターンの費用をすべて0にする仕様（ターン以外の挙動を見るとき用）。
FLAT_SPEC = routing.TurnCostSpec(
    left_seconds=0.0, right_seconds=0.0, uturn_seconds=0.0, straight_max_deg=180.0,
    major_crossing_seconds=0.0, major_turn_seconds=0.0,
)
# ターンの種別が全部違う値になる仕様。
TURN_SPEC = routing.TurnCostSpec(
    left_seconds=5.0, right_seconds=3.0, uturn_seconds=20.0, straight_max_deg=30.0,
    major_crossing_seconds=7.0, major_turn_seconds=11.0,
)


def build_all(graph, spec=FLAT_SPEC, edge_rank=None, node_has_signal=None, node_db_rank=None):
    """lazy graph・静的派生物・ターン展開構造を一度に組む。

    ターンの費用に要る3つの列は`None`を渡せない（渡し忘れが「上位の道の横断に待ちが付かない」
    構造を黙って作るため）。省略したときは、待ちが付かない値——階級0・信号なし——で埋める。
    """
    lazy = lazy_of(graph)
    statics = routing.build_search_graph_statics(lazy.graph, graph.distance_m)
    bearings = routing.edge_bearings(lazy.graph, graph.bearing_deg, graph.latitude, graph.longitude)
    node_count = lazy.node_count
    structure = routing.build_turn_expanded_structure(
        statics.csr, lazy.graph, bearings,
        np.zeros(len(lazy.edge_ids), dtype=np.int64) if edge_rank is None else edge_rank,
        spec,
        np.zeros(node_count, dtype=bool) if node_has_signal is None else node_has_signal,
        np.zeros(node_count, dtype=np.int64) if node_db_rank is None else node_db_rank,
    )
    return lazy, statics, structure


def state_index(lazy):
    return {edge_id: i for i, edge_id in enumerate(lazy.edge_ids)}


def transition_seconds(lazy, structure):
    """`(遷移元edge_id, 遷移先edge_id) -> ターンの秒数`。"""
    out = {}
    for source in range(structure.state_count):
        for entry in range(int(structure.indptr[source]), int(structure.indptr[source + 1])):
            target = int(structure.target_state[entry])
            out[(lazy.edge_ids[source], lazy.edge_ids[target])] = float(structure.turn_seconds[entry])
    return out


def rank_array(lazy, by_edge_id):
    return np.array([by_edge_id[edge_id] for edge_id in lazy.edge_ids], dtype=np.int64)


# 十字路。中心Cへ東向き（方位90）で入る状態`WC`から、直進・左折・右折・Uターンが1つずつ出る。
PLUS_NODES = {
    "C": (35.00, 139.00),
    "N": (35.01, 139.00),
    "S": (34.99, 139.00),
    "E": (35.00, 139.01),
    "W": (35.00, 138.99),
}
PLUS_EDGES = {
    "WC": ("W", "C", 100.0, 90.0),
    "CW": ("C", "W", 100.0, 270.0),
    "CE": ("C", "E", 100.0, 90.0),
    "EC": ("E", "C", 100.0, 270.0),
    "CN": ("C", "N", 100.0, 0.0),
    "NC": ("N", "C", 100.0, 180.0),
    "CS": ("C", "S", 100.0, 180.0),
    "SC": ("S", "C", 100.0, 0.0),
}

# 直線 A-B-C（＋どのEdgeにも繋がらない孤立Node Z）。
LINE_NODES = {"A": (35.0, 139.0), "B": (35.0, 139.01), "C": (35.0, 139.02), "Z": (35.0, 139.03)}
LINE_EDGES = {
    "AB": ("A", "B", 100.0, 90.0),
    "BA": ("B", "A", 100.0, 270.0),
    "BC": ("B", "C", 100.0, 90.0),
    "CB": ("C", "B", 100.0, 270.0),
}


def make_grid(size, cell=0.01, base_lat=35.0, base_lon=139.0):
    """`size`×`size`の格子。全Edgeが双方向・距離100m。"""
    nodes = {}
    edges = {}
    for row in range(size):
        for col in range(size):
            nodes[f"n{row}_{col}"] = (base_lat + row * cell, base_lon + col * cell)
    for row in range(size):
        for col in range(size):
            here = f"n{row}_{col}"
            if col + 1 < size:
                east = f"n{row}_{col + 1}"
                edges[f"{here}>{east}"] = (here, east, 100.0, 90.0)
                edges[f"{east}>{here}"] = (east, here, 100.0, 270.0)
            if row + 1 < size:
                north = f"n{row + 1}_{col}"
                edges[f"{here}>{north}"] = (here, north, 100.0, 0.0)
                edges[f"{north}>{here}"] = (north, here, 100.0, 180.0)
    return make_graph(nodes, edges)


def out_states(lazy, node_id):
    node_index = lazy.node_id_to_index[node_id]
    return np.flatnonzero(lazy.graph.edge_from == node_index).astype(np.int64)


# --- build_lazy_road_graph ---


def test_parallel_edges_resolve_to_the_lowest_row():
    """同一Node対に複数の区間があるとき、採用されるのは元の行が最も小さい1本。

    ここが並べ替えの揺れに依ると、同じ範囲・同じ設定でも呼ぶたびに別の区間が探索へ出て、
    返るルートが揺れる。
    """
    graph = make_graph(
        {"a": (35.0, 139.0), "b": (35.0, 139.01)},
        {"first": ("a", "b"), "second": ("a", "b"), "third": ("a", "b")},
    )
    lazy = lazy_of(graph)
    assert lazy.edge_ids == ["first"]
    assert list(lazy.graph.edge_rows) == [0]


def test_opposite_directions_are_kept_as_separate_edges():
    """(a,b)と(b,a)は別の対として両方残る（並行区間の解消は向きを区別する）。"""
    graph = make_graph(
        {"a": (35.0, 139.0), "b": (35.0, 139.01)},
        {"forward": ("a", "b"), "backward": ("b", "a")},
    )
    lazy = lazy_of(graph)
    assert sorted(lazy.edge_ids) == ["backward", "forward"]


def test_edges_are_numbered_in_ascending_order_of_their_endpoints():
    """区間の番号は`(始点, 終点)`の昇順。CSRの行がこの並びをそのまま使う。"""
    lazy = lazy_of(make_graph(PLUS_NODES, PLUS_EDGES))
    pairs = list(zip(lazy.graph.edge_from.tolist(), lazy.graph.edge_to.tolist(), strict=True))
    assert pairs == sorted(pairs)


# --- build_search_graph_statics ---


def test_statics_carry_edge_length_in_edge_number_order():
    edges = dict(LINE_EDGES)
    edges["AB"] = ("A", "B", 250.0, 90.0)
    edges["BC"] = ("B", "C", 70.0, 90.0)
    graph = make_graph(LINE_NODES, edges)
    lazy = lazy_of(graph)
    statics = routing.build_search_graph_statics(lazy.graph, graph.distance_m)
    expected = [graph.edges[edge_id].distance_m for edge_id in lazy.edge_ids]
    assert list(statics.edge_length_m) == expected


def test_csr_rows_hold_the_outgoing_edges_of_each_node_in_ascending_order():
    """CSRの行は「そのNodeから出る区間」で、entry_edge_index経由で区間へ戻れる。
    行内の遷移先Nodeは昇順（探索の隣接走査と`edge_index_between`がこの並びを前提にする）。"""
    graph = make_graph(PLUS_NODES, PLUS_EDGES)
    lazy = lazy_of(graph)
    csr = routing.build_search_graph_statics(lazy.graph, graph.distance_m).csr
    for node_id, node_index in lazy.node_id_to_index.items():
        start, end = int(csr.indptr[node_index]), int(csr.indptr[node_index + 1])
        row = [(int(csr.indices[k]), lazy.edge_ids[int(csr.entry_edge_index[k])]) for k in range(start, end)]
        assert [to_index for to_index, _ in row] == sorted(to_index for to_index, _ in row)
        recovered = {
            (lazy.index_to_node_id[to_index], edge_id) for to_index, edge_id in row
        }
        expected = {
            (edge.to_node_id, edge_id)
            for edge_id, edge in graph.edges.items()
            if edge.from_node_id == node_id
        }
        assert recovered == expected


def test_csr_of_a_graph_without_edges_is_empty():
    """Edgeが1本も無くても（道の無い範囲）構造は組める。"""
    graph = make_graph({"a": (35.0, 139.0)}, {})
    lazy = lazy_of(graph)
    statics = routing.build_search_graph_statics(lazy.graph, graph.distance_m)
    assert statics.csr.node_count == 1
    assert list(statics.csr.indptr) == [0, 0]
    assert len(statics.csr.indices) == 0
    assert len(statics.edge_length_m) == 0


# --- edge_index_between ---


def test_edge_between_finds_each_direction_and_nothing_where_no_road_runs():
    """両端のノードから区間の番号を引く。一方通行の逆向きや繋がっていない対はNone。"""
    graph = make_graph(ONE_WAY_NODES, ONE_WAY_EDGES)
    lazy = lazy_of(graph)
    csr = routing.build_search_graph_statics(lazy.graph, graph.distance_m).csr
    node = lazy.node_id_to_index
    for edge_id, edge in graph.edges.items():
        found = routing.edge_index_between(csr, node[edge.from_node_id], node[edge.to_node_id])
        assert found is not None and lazy.edge_ids[found] == edge_id
    assert routing.edge_index_between(csr, node["N"], node["C"]) is None
    assert routing.edge_index_between(csr, node["N"], node["E"]) is None


# --- overlap_ratio ---


def test_overlap_ratio_of_an_empty_candidate_is_zero():
    lengths = np.array([10.0, 10.0])
    assert routing.overlap_ratio(np.array([], dtype=np.int64), np.array([0]), lengths) == 0.0


def test_overlap_ratio_weights_by_distance_not_by_edge_count():
    """共有の割合は本数ではなく距離で測る（短い区間を1本共有しても重複とは呼ばない）。"""
    lengths = np.array([10.0, 90.0])
    assert routing.overlap_ratio(np.array([0, 1]), np.array([1]), lengths) == pytest.approx(0.9)
    assert routing.overlap_ratio(np.array([0, 1]), np.array([0]), lengths) == pytest.approx(0.1)


# --- pareto_layer_index ---


def test_pareto_layers_are_empty_for_no_candidates():
    layer = routing.pareto_layer_index(
        np.array([]), np.array([]), quantum_a=1.0, quantum_b=1.0, max_items=3
    )
    assert len(layer) == 0


def test_pareto_layers_rank_by_how_many_candidates_dominate():
    """両指標で負けている候補ほど後ろの層へ回る。層に入れば0以上、入らなければ-1。"""
    a = np.array([1.0, 2.0, 3.0, 3.0, 2.0])
    b = np.array([10.0, 5.0, 1.0, 10.0, 10.0])
    layer = routing.pareto_layer_index(a, b, quantum_a=1.0, quantum_b=1.0, max_items=5)
    assert list(layer) == [0, 0, 0, 2, 1]


def test_pareto_quantum_makes_near_equal_candidates_mutually_non_dominated():
    """粒度より小さい差は「実質同じ」として扱う。

    粒度が効かないと、1m短いだけの候補が互いに非劣解として全件残り、フィルタとして
    機能しなくなる。
    """
    a = np.array([0.0, 50.0, 500.0])
    b = np.array([0.0, 0.02, 0.5])
    layer = routing.pareto_layer_index(a, b, quantum_a=200.0, quantum_b=0.1, max_items=3)
    assert list(layer) == [0, 0, 1]


def test_pareto_layers_do_not_depend_on_the_order_of_the_candidates():
    """並べ替えて渡しても各候補の層は変わらない。

    依存すると、同じ起点・同じ設定でも候補の並べ方次第で返るルート集合が変わる。
    """
    a = np.array([0.0, 0.0, 0.0, 1.0, 1.0])
    b = np.array([2.0, 0.0, 1.0, 0.0, 5.0])
    shuffle = np.array([4, 1, 3, 0, 2])
    straight = routing.pareto_layer_index(a, b, quantum_a=1.0, quantum_b=1.0, max_items=2)
    # 層分けと足切りの両方が効いた状態でしか、並べ替えの影響は現れない。
    assert len(set(straight)) > 1 and -1 in straight
    shuffled = routing.pareto_layer_index(
        a[shuffle], b[shuffle], quantum_a=1.0, quantum_b=1.0, max_items=2
    )
    assert list(shuffled) == [straight[i] for i in shuffle]


def test_pareto_assigns_every_candidate_when_there_are_fewer_than_requested():
    """候補が要求件数に満たないときは、全件が層に入って走査が終わる（-1が残らない）。"""
    a = np.array([1.0, 2.0, 3.0])
    b = np.array([3.0, 2.0, 1.0])
    layer = routing.pareto_layer_index(a, b, quantum_a=1.0, quantum_b=1.0, max_items=10)
    assert list(layer) == [0, 0, 0]


def test_pareto_drops_candidates_that_cannot_reach_a_layer_below_max_items():
    """同じ距離段階でbがmax_items番目より後ろの候補は、どの層にも入らない（-1）。"""
    a = np.array([0.0, 0.0, 0.0, 0.0])
    b = np.array([0.0, 1.0, 2.0, 3.0])
    layer = routing.pareto_layer_index(a, b, quantum_a=1.0, quantum_b=1.0, max_items=2)
    assert list(layer) == [0, 1, -1, -1]


def test_pareto_keeps_a_whole_tie_group_even_beyond_max_items():
    """完全に同点の候補群は、max_items件を超えても丸ごと同じ層に入る。

    点単位で切ると、全方位が等距離・同難易度の地形で候補が層からこぼれ、後段の方位分散が
    働く同点グループが壊れる。
    """
    a = np.zeros(5)
    b = np.zeros(5)
    layer = routing.pareto_layer_index(a, b, quantum_a=1.0, quantum_b=1.0, max_items=2)
    assert list(layer) == [0, 0, 0, 0, 0]


# --- select_diverse_by_overlap ---

DIVERSE_LENGTHS = np.array([10.0, 10.0, 10.0, 10.0, 10.0])


def test_select_diverse_rejects_max_count_beyond_the_bitmask_width():
    """採用済みの集合はuint64のビットで持つため、65件以上は表せない。黙って取りこぼさず送出する。"""
    with pytest.raises(ValueError):
        routing.select_diverse_by_overlap([], lambda item: [], DIVERSE_LENGTHS, [1.0], 65)


def test_select_diverse_skips_candidates_over_the_overlap_threshold():
    """重複率が閾値を「超えた」ものだけ飛ばす（ちょうど閾値なら採用する）。"""
    edges = {"a": [0, 1], "b": [1, 2], "c": [3, 4]}
    strict = routing.select_diverse_by_overlap(
        ["a", "b", "c"], edges.__getitem__, DIVERSE_LENGTHS, [0.4], 3
    )
    assert strict == ["a", "c"]
    at_threshold = routing.select_diverse_by_overlap(
        ["a", "b", "c"], edges.__getitem__, DIVERSE_LENGTHS, [0.5], 3
    )
    assert at_threshold == ["a", "b", "c"]


def test_select_diverse_retries_overlap_rejects_but_not_incompatible_ones():
    """閾値を緩めたパスで再検査されるのは「重複率で飛ばした候補」だけ。

    非互換・経路無しで飛ばした候補は閾値を緩めても結果が変わらないため、再検査しない。
    """
    edges = {"a": [0, 1], "b": [0, 1], "c": [2], "d": [3], "e": None}
    selected = routing.select_diverse_by_overlap(
        ["a", "b", "c", "d", "e"],
        edges.__getitem__,
        DIVERSE_LENGTHS,
        [0.5, 1.0],
        max_count=4,
        is_compatible=lambda item, chosen: item != "d",
    )
    assert selected == ["a", "c", "b"]


def test_select_diverse_compares_against_each_accepted_route_separately():
    """重複率は採用済みの1件ごとに見る（合算しない）。

    2本と半分ずつ重なる候補は、合計では全部が既出でも「どれとも半分しか重ならない」ため通る。
    """
    lengths = np.array([10.0, 10.0, 10.0, 10.0])
    edges = {"a": [0, 1], "b": [2, 3], "c": [0, 2]}
    selected = routing.select_diverse_by_overlap(
        ["a", "b", "c"], edges.__getitem__, lengths, [0.6], max_count=3
    )
    assert selected == ["a", "b", "c"]


def test_select_diverse_stops_at_max_count_without_trying_looser_thresholds():
    edges = {"a": [0, 1], "b": [0, 1]}
    selected = routing.select_diverse_by_overlap(
        ["a", "b"], edges.__getitem__, DIVERSE_LENGTHS, [0.5, 1.0], max_count=1
    )
    assert selected == ["a"]


def test_select_diverse_reruns_prefer_after_every_acceptance():
    """同点グループ内の試行順は、1件採用するたびに採用済みを見て決め直す。

    採用済み集合に依存する優先順（どれだけ離れているか）を、走査した候補の数ではなく
    採用件数ぶんの回数だけ計算すれば済ませるための契約。
    """
    edges = {"a": [0], "b": [1], "c": [2]}
    calls = []

    def prefer(remaining, chosen):
        calls.append((list(remaining), list(chosen)))
        return list(reversed(remaining))

    selected = routing.select_diverse_by_overlap(
        [], edges.__getitem__, DIVERSE_LENGTHS, [1.0], max_count=3,
        tie_groups=[["a", "b", "c"]], prefer=prefer,
    )
    assert selected == ["c", "a", "b"]
    assert calls == [
        (["a", "b", "c"], []),
        (["b", "a"], ["c"]),
        (["b"], ["c", "a"]),
    ]


def test_select_diverse_drops_candidates_passed_over_before_an_acceptance():
    """採用した候補より前で飛ばしたものは、そのグループの残り候補から外れる。"""
    edges = {"a": [0], "b": [1], "c": [2]}
    selected = routing.select_diverse_by_overlap(
        [], edges.__getitem__, DIVERSE_LENGTHS, [1.0], max_count=3,
        is_compatible=lambda item, chosen: item != "c",
        tie_groups=[["a", "b", "c"]],
        prefer=lambda remaining, chosen: ["c", *[x for x in remaining if x != "c"]],
    )
    assert selected == ["a", "b"]


# --- build_node_spatial_index / find_nearest_node_indexed ---

SNAP_GRAPH = make_graph(
    {
        "center": (35.0099, 139.0099),
        "north": (35.0101, 139.0050),
        # `north`と同じセルにあり、そこより遠い（同一バケツ内での比較を通す）。
        "same_cell_farther": (35.0105, 139.0099),
        "far": (35.0400, 139.0000),
    },
    {},
)


def node_index_of(net, only=None):
    """`only`（ノード名の集合）を渡すと、そのノードだけを索引の候補にする。"""
    candidates = None if only is None else np.array([node_id in only for node_id in net.node_ids])
    return routing.build_node_spatial_index(net.latitude, net.longitude, candidates)


def nearest(net, index, point, allowed_names=None, **kwargs):
    """最寄りノードの名前（無ければNone）。`allowed_names`は候補にしてよいノード名の集合。"""
    allowed = None if allowed_names is None else np.array([node_id in allowed_names for node_id in net.node_ids])
    found = routing.find_nearest_node_indexed(index, point, allowed, **kwargs)
    return None if found is None else net.node_ids[found]


def test_nearest_node_is_none_when_the_index_has_no_nodes():
    index = node_index_of(make_graph({}, {}))
    assert index.cell_bounds is None
    assert routing.find_nearest_node_indexed(index, coords(35.0, 139.0)) is None


@pytest.mark.parametrize(
    "point",
    [
        coords(35.0650, 139.0050),   # 緯度が索引の上端より2セル外
        coords(34.9750, 139.0050),   # 緯度が下端より2セル外
        coords(35.0050, 139.0350),   # 経度が右端より2セル外
        coords(35.0050, 138.9750),   # 経度が左端より2セル外
    ],
)
def test_nearest_node_is_none_far_outside_the_indexed_area(point):
    """索引が覆う範囲の外を指した点には寄せない。

    ここを通すと、何十kmも離れた道へ黙って寄せた結果が「利用者が指した地点」として扱われ、
    指した覚えのない場所を通るルートになる。
    """
    index = node_index_of(SNAP_GRAPH)
    assert routing.find_nearest_node_indexed(index, point) is None


def test_nearest_node_tolerates_a_point_just_outside_the_indexed_area():
    """範囲の縁を1セルだけ外した点は、すぐ隣の道へ寄せる（地図の端をクリックした場合）。"""
    index = node_index_of(SNAP_GRAPH)
    assert nearest(SNAP_GRAPH, index, coords(35.0550, 139.0000)) == "far"


def test_nearest_node_keeps_expanding_rings_until_the_bound_is_safe():
    """最初のセルで見つけた点で打ち切らない——隣のセルにもっと近い点が残りうる。

    同じセルに後から出てくる、より遠いNodeで最近傍を上書きしない。
    """
    index = node_index_of(SNAP_GRAPH)
    assert nearest(SNAP_GRAPH, index, coords(35.0050, 139.0050)) == "north"


def test_nearest_node_skips_nodes_that_are_not_allowed():
    """`allowed`が偽のNodeは最近傍候補にしない（本線から孤立したNodeを外すため）。"""
    index = node_index_of(SNAP_GRAPH)
    allowed = set(SNAP_GRAPH.node_ids) - {"north"}
    assert nearest(SNAP_GRAPH, index, coords(35.0050, 139.0050), allowed) == "center"


def test_nearest_node_is_none_when_no_node_is_allowed():
    """1件も真にならないときも索引の範囲を出た時点で止まる（走査が終わる）。"""
    index = node_index_of(SNAP_GRAPH)
    assert nearest(SNAP_GRAPH, index, coords(35.0050, 139.0050), set()) is None


def test_nearest_node_respects_max_distance_km():
    """「近くに無いなら寄せない」を距離で表す呼び出し。"""
    index = node_index_of(SNAP_GRAPH)
    point = coords(35.0050, 139.0050)
    assert routing.find_nearest_node_indexed(index, point, max_distance_km=0.1) is None
    assert nearest(SNAP_GRAPH, index, point, max_distance_km=5.0) == "north"


def test_node_index_only_holds_the_candidate_nodes():
    """`candidates`を渡すとその真のノードだけが索引に入る（Hard Constraintで孤立したNodeを外す用途）。"""
    index = node_index_of(SNAP_GRAPH, only={"center"})
    assert nearest(SNAP_GRAPH, index, coords(35.0101, 139.0050)) == "center"


# --- current_turn_cost ---


def test_turn_cost_is_rebuilt_from_tuning_on_every_call(monkeypatch):
    """呼ぶたびに較正値を引き直す。束ねると管理画面から変えた値が効かなくなる。"""
    shift = {"value": 0.0}
    monkeypatch.setattr(routing, "tuning_value", lambda key: float(len(key)) + shift["value"])
    before = dataclasses.asdict(routing.current_turn_cost())
    shift["value"] = 100.0
    after = dataclasses.asdict(routing.current_turn_cost())
    assert before
    assert all(after[name] == before[name] + 100.0 for name in before)


# --- edge_bearings ---


def test_edge_bearings_prefer_the_stored_value_and_fall_back_to_the_node_pair():
    """折れ線から求めた向きがあればそれを使い、持たない区間だけ両端Nodeから補う。"""
    graph = make_graph(
        {"a": (35.0, 139.0), "b": (35.0, 139.01)},
        {"stored": ("a", "b", 100.0, 123.0), "derived": ("b", "a", 100.0, None)},
    )
    lazy = lazy_of(graph)
    bearings = dict(
        zip(lazy.edge_ids, routing.edge_bearings(lazy.graph, graph.bearing_deg, graph.latitude, graph.longitude))
    )
    assert bearings["stored"] == pytest.approx(123.0)
    assert bearings["derived"] == pytest.approx(270.0, abs=1.0)


# --- build_turn_expanded_structure ---


def test_turn_transitions_cover_every_outgoing_edge_including_the_u_turn():
    """状態eの遷移先は「eの終点Nodeから出る全区間」。Uターンも禁止せず遷移として持つ
    （袋小路からの折り返しに要る）。"""
    graph = make_graph(PLUS_NODES, PLUS_EDGES)
    lazy, _, structure = build_all(graph)
    targets = {
        target for (source, target) in transition_seconds(lazy, structure) if source == "WC"
    }
    assert targets == {"CE", "CN", "CS", "CW"}
    assert structure.state_count == len(lazy.edge_ids)


def test_turn_seconds_classify_straight_left_right_and_u_turn():
    """方位差の符号で左右を分け、直進とみなす幅の内側は0秒、始点へ戻る遷移はUターン。"""
    graph = make_graph(PLUS_NODES, PLUS_EDGES)
    lazy, _, structure = build_all(graph, spec=TURN_SPEC)
    seconds = transition_seconds(lazy, structure)
    assert seconds[("WC", "CE")] == pytest.approx(0.0)
    assert seconds[("WC", "CN")] == pytest.approx(TURN_SPEC.left_seconds)
    assert seconds[("WC", "CS")] == pytest.approx(TURN_SPEC.right_seconds)
    assert seconds[("WC", "CW")] == pytest.approx(TURN_SPEC.uturn_seconds)


@pytest.fixture
def major_threshold(monkeypatch):
    """「そもそも待ちの要る階級か」の境目は`domain/traffic.py`が決める。差し替えて与える。"""
    threshold = 4
    monkeypatch.setattr(routing, "MAJOR_CROSSING_MIN_RANK", threshold)
    return threshold


def _plus_ranks(lazy, crossing_rank, entering_rank):
    return rank_array(
        lazy,
        {
            edge_id: (crossing_rank if edge_id in {"CN", "NC", "CS", "SC"} else entering_rank)
            for edge_id in PLUS_EDGES
        },
    )


def test_crossing_a_higher_ranked_road_adds_a_wait_split_by_straight_or_turning(major_threshold):
    """信号の無い交差点で上位の道と交わるとき、横断（直進）と右左折で別の秒数を足す。"""
    major = major_threshold
    graph = make_graph(PLUS_NODES, PLUS_EDGES)
    lazy = lazy_of(graph)
    _, _, structure = build_all(
        graph, spec=TURN_SPEC, edge_rank=_plus_ranks(lazy, major, major - 1)
    )
    seconds = transition_seconds(lazy, structure)
    assert seconds[("WC", "CE")] == pytest.approx(TURN_SPEC.major_crossing_seconds)
    assert seconds[("WC", "CN")] == pytest.approx(
        TURN_SPEC.left_seconds + TURN_SPEC.major_turn_seconds
    )
    assert seconds[("WC", "CS")] == pytest.approx(
        TURN_SPEC.right_seconds + TURN_SPEC.major_turn_seconds
    )
    assert seconds[("WC", "CW")] == pytest.approx(TURN_SPEC.uturn_seconds)


def test_crossing_wait_needs_the_rank_to_reach_the_major_threshold(major_threshold):
    """「自分より上位」だけでは足りない——待ちの要る階級に達していなければ足さない。"""
    major = major_threshold
    graph = make_graph(PLUS_NODES, PLUS_EDGES)
    lazy = lazy_of(graph)
    _, _, structure = build_all(
        graph, spec=TURN_SPEC, edge_rank=_plus_ranks(lazy, major - 1, major - 2)
    )
    seconds = transition_seconds(lazy, structure)
    assert seconds[("WC", "CE")] == pytest.approx(0.0)
    assert seconds[("WC", "CN")] == pytest.approx(TURN_SPEC.left_seconds)


def test_crossing_wait_is_not_added_where_a_signal_exists(major_threshold):
    """信号のある交差点の待ちは停止密度の材料が運ぶ。ここで足すと同じ待ちを二重に数える。"""
    major = major_threshold
    graph = make_graph(PLUS_NODES, PLUS_EDGES)
    lazy = lazy_of(graph)
    signals = np.zeros(lazy.node_count, dtype=bool)
    signals[lazy.node_id_to_index["C"]] = True
    _, _, structure = build_all(
        graph, spec=TURN_SPEC, edge_rank=_plus_ranks(lazy, major, major - 1), node_has_signal=signals
    )
    seconds = transition_seconds(lazy, structure)
    assert seconds[("WC", "CE")] == pytest.approx(0.0)
    assert seconds[("WC", "CN")] == pytest.approx(TURN_SPEC.left_seconds)


def test_db_node_rank_raises_a_rank_the_partial_graph_cannot_show(major_threshold):
    """bboxの外へはみ出した上位の道は部分グラフに現れない。DB側の集計値があれば大きい方を採る。"""
    major = major_threshold
    graph = make_graph(PLUS_NODES, PLUS_EDGES)
    lazy = lazy_of(graph)
    flat_ranks = _plus_ranks(lazy, major - 1, major - 1)
    _, _, without_db = build_all(graph, spec=TURN_SPEC, edge_rank=flat_ranks)
    assert transition_seconds(lazy, without_db)[("WC", "CE")] == pytest.approx(0.0)

    db_rank = np.zeros(lazy.node_count, dtype=np.int64)
    db_rank[lazy.node_id_to_index["C"]] = major
    _, _, with_db = build_all(
        graph, spec=TURN_SPEC, edge_rank=flat_ranks, node_db_rank=db_rank
    )
    assert transition_seconds(lazy, with_db)[("WC", "CE")] == pytest.approx(
        TURN_SPEC.major_crossing_seconds
    )


def test_db_node_rank_never_lowers_the_rank_derived_from_the_graph(major_threshold):
    """DB側の集計値は下限を上げるだけ。未集計の0で導出した階級を打ち消さない。

    打ち消すと、バッチ未実行のDBでは上位の道の待ちが本番から丸ごと消える。
    """
    graph = make_graph(PLUS_NODES, PLUS_EDGES)
    lazy = lazy_of(graph)
    unaggregated = np.zeros(lazy.node_count, dtype=np.int64)
    _, _, structure = build_all(
        graph, spec=TURN_SPEC,
        edge_rank=_plus_ranks(lazy, major_threshold, major_threshold - 1),
        node_db_rank=unaggregated,
    )
    assert transition_seconds(lazy, structure)[("WC", "CE")] == pytest.approx(
        TURN_SPEC.major_crossing_seconds
    )


ONE_WAY_NODES = {k: PLUS_NODES[k] for k in ("C", "N", "E", "W")}
# `CN`だけが一方通行の幹線（Cから出るのみ）。Cへ「入る」区間だけを見ると階級が拾えない。
ONE_WAY_EDGES = {k: PLUS_EDGES[k] for k in ("WC", "CW", "CE", "EC", "CN")}


def test_node_rank_comes_from_roads_that_leave_the_node_too(major_threshold):
    """Nodeの階級は、そこへ入る道だけでなく出る道からも取る。

    一方通行の幹線が出ていくだけの交差点でも、渡るときの待ちが付く。
    """
    graph = make_graph(ONE_WAY_NODES, ONE_WAY_EDGES)
    lazy = lazy_of(graph)
    ranks = rank_array(
        lazy,
        {
            edge_id: (major_threshold if edge_id == "CN" else major_threshold - 1)
            for edge_id in ONE_WAY_EDGES
        },
    )
    _, _, structure = build_all(graph, spec=TURN_SPEC, edge_rank=ranks)
    assert transition_seconds(lazy, structure)[("WC", "CE")] == pytest.approx(
        TURN_SPEC.major_crossing_seconds
    )


def test_reverse_transitions_flip_direction_and_carry_the_original_wait():
    """後ろ向きの遷移は向きだけを反転し、ターンの待ちは元の進行方向の値のまま運ぶ。"""
    graph = make_graph(PLUS_NODES, PLUS_EDGES)
    lazy, _, structure = build_all(graph, spec=TURN_SPEC)
    forward = transition_seconds(lazy, structure)
    indptr, source_state, turn_seconds = structure.reverse_transitions()
    backward = {}
    for target in range(structure.state_count):
        for entry in range(int(indptr[target]), int(indptr[target + 1])):
            key = (lazy.edge_ids[int(source_state[entry])], lazy.edge_ids[target])
            backward[key] = float(turn_seconds[entry])
    assert backward == forward


# --- build_turn_expanded_tree ---


# 優先度キューの初期容量（種の数＋余裕）を確実に超える広さ。伸長の経路を普通の探索が通る、
# という設計をこの広さで実際に通す。
GRID_SIZE = 20


def grid_tree(size=GRID_SIZE, **kwargs):
    graph = make_grid(size)
    lazy, statics, structure = build_all(graph)
    cost = np.ones(structure.state_count)
    tree = routing.build_turn_expanded_tree(
        structure, cost, statics.edge_length_m, out_states(lazy, "n0_0"),
        lazy.node_count, **kwargs,
        edge_seconds=np.ones(structure.state_count),
    )
    return lazy, statics, structure, tree


def test_tree_costs_equal_the_hop_count_from_the_origin():
    """種は自分自身の区間コストから始まるため、各Nodeのコストは通った区間の本数になる。

    起点Node自身は0にならない——状態の空間に「まだ走っていない」が無く、起点のコストは
    「起点へ戻ってくるコスト」（ここではUターン1回）になる。
    """
    lazy, _, _, tree = grid_tree()
    for node_id, node_index in lazy.node_id_to_index.items():
        row, col = (int(part) for part in node_id[1:].split("_"))
        hops = row + col
        expected = hops if hops else 2
        assert tree.node_cost[node_index] == pytest.approx(expected), node_id
        assert tree.node_length_m[node_index] == pytest.approx(expected * 100.0), node_id


def test_tree_seeds_start_from_the_cost_of_their_own_edge():
    """種は自分自身の区間コストから始まる（安い種から順に確定する）。"""
    graph = make_graph(PLUS_NODES, PLUS_EDGES)
    lazy, statics, structure = build_all(graph)
    states = state_index(lazy)
    seed_cost = {"CW": 4.0, "CE": 3.0, "CN": 2.0, "CS": 1.0}
    cost = np.ones(structure.state_count)
    for edge_id, value in seed_cost.items():
        cost[states[edge_id]] = value
    tree = routing.build_turn_expanded_tree(
        structure, cost, statics.edge_length_m, out_states(lazy, "C"),
        lazy.node_count,
        edge_seconds=np.ones(structure.state_count),
    )
    for edge_id, value in seed_cost.items():
        leaf = graph.edges[edge_id].to_node_id
        assert tree.node_cost[lazy.node_id_to_index[leaf]] == pytest.approx(value), edge_id


def test_tree_seconds_come_from_the_plain_travel_time_not_from_the_cost():
    """秒はコスト（主観的割増込み）ではなく素の走行時間を積む。混ぜると到着時刻が狂う。"""
    lazy, statics, structure = build_all(make_graph(LINE_NODES, LINE_EDGES))
    states = state_index(lazy)
    tree = routing.build_turn_expanded_tree(
        structure, np.full(structure.state_count, 5.0), statics.edge_length_m,
        np.array([states["AB"]], dtype=np.int64), lazy.node_count,
        edge_seconds=np.full(structure.state_count, 2.0),
    )
    assert tree.state_cost[states["BC"]] == pytest.approx(10.0)
    assert tree.state_seconds[states["BC"]] == pytest.approx(4.0)


def test_tree_stops_at_the_cost_limit():
    """`cost_limit`を超える先へは伸ばさない（到達できるNodeだけが有限コストになる）。"""
    lazy, _, _, tree = grid_tree(cost_limit=3.0)
    for node_id, node_index in lazy.node_id_to_index.items():
        row, col = (int(part) for part in node_id[1:].split("_"))
        hops = row + col
        reachable = (hops if hops else 2) <= 3
        assert np.isfinite(tree.node_cost[node_index]) == reachable, node_id


def test_tree_never_enters_a_non_finite_cost_edge():
    """コストinfはHard Constraintの表現。種にも遷移先にもしない（迂回する）。"""
    graph = make_grid(6)
    lazy, statics, structure = build_all(graph)
    cost = np.ones(structure.state_count)
    blocked = state_index(lazy)["n0_0>n0_1"]
    cost[blocked] = np.inf
    tree = routing.build_turn_expanded_tree(
        structure, cost, statics.edge_length_m, out_states(lazy, "n0_0"),
        lazy.node_count,
        edge_seconds=np.ones(structure.state_count),
    )
    assert not np.isfinite(tree.state_cost[blocked])
    assert tree.node_cost[lazy.node_id_to_index["n0_1"]] == pytest.approx(3.0)


def test_tree_marks_unreachable_states_and_nodes():
    graph = make_graph(LINE_NODES, LINE_EDGES)
    lazy, statics, structure = build_all(graph)
    cost = np.ones(structure.state_count)
    tree = routing.build_turn_expanded_tree(
        structure, cost, statics.edge_length_m, out_states(lazy, "A"),
        lazy.node_count,
        edge_seconds=np.ones(structure.state_count),
    )
    isolated = lazy.node_id_to_index["Z"]
    assert tree.node_cost[isolated] == math.inf
    assert tree.node_best_state[isolated] == -1
    assert np.isnan(tree.node_length_m[isolated])
    assert routing.turn_expanded_path_edge_indices(tree, isolated) is None


def test_tree_adds_the_turn_wait_to_both_cost_and_seconds():
    """繋ぎ目のターンの待ちは、コストにも所要時間にも入る。"""
    graph = make_graph(PLUS_NODES, PLUS_EDGES)
    lazy, statics, structure = build_all(graph, spec=TURN_SPEC)
    states = state_index(lazy)
    cost = np.ones(structure.state_count)
    seconds = np.full(structure.state_count, 10.0)
    tree = routing.build_turn_expanded_tree(
        structure, cost, statics.edge_length_m, np.array([states["WC"]], dtype=np.int64),
        lazy.node_count, edge_seconds=seconds, bin_seconds=1000.0,
    )
    assert tree.state_cost[states["CN"]] == pytest.approx(1.0 + TURN_SPEC.left_seconds + 1.0)
    assert tree.state_seconds[states["CN"]] == pytest.approx(10.0 + TURN_SPEC.left_seconds + 10.0)


def _line_bins():
    """4本の時刻ビン。B→Cのコストだけがビンごとに変わる。"""
    graph = make_graph(LINE_NODES, LINE_EDGES)
    lazy, statics, structure = build_all(graph)
    states = state_index(lazy)
    cost = np.ones((4, structure.state_count))
    for bin_index, value in enumerate([1.0, 7.0, 50.0, 99.0]):
        cost[bin_index, states["BC"]] = value
    seconds = np.full((4, structure.state_count), 10.0)
    return lazy, statics, structure, states, cost, seconds


@pytest.mark.parametrize(("bin_seconds", "expected"), [(20.0, 2.0), (5.0, 51.0)])
def test_tree_picks_the_time_bin_by_elapsed_seconds(bin_seconds, expected):
    """時計を進めるのは素の所要時間であってコストではない。ビンの幅で引かれる行が変わる。"""
    lazy, statics, structure, states, cost, seconds = _line_bins()
    tree = routing.build_turn_expanded_tree(
        structure, cost, statics.edge_length_m, np.array([states["AB"]], dtype=np.int64),
        lazy.node_count, edge_seconds=seconds, bin_seconds=bin_seconds,
    )
    assert tree.state_cost[states["BC"]] == pytest.approx(expected)


def test_tree_clamps_an_elapsed_time_beyond_the_last_bin():
    """予報の窓より長くかかる経路は、最後のビンの条件で評価を続ける。"""
    lazy, statics, structure, states, cost, seconds = _line_bins()
    tree = routing.build_turn_expanded_tree(
        structure, cost, statics.edge_length_m, np.array([states["AB"]], dtype=np.int64),
        lazy.node_count, edge_seconds=seconds, bin_seconds=2.0,
    )
    assert tree.state_cost[states["BC"]] == pytest.approx(1.0 + 99.0)


def test_reverse_tree_measures_the_cost_from_each_state_to_the_destination():
    """逆向きの木は遷移の向きだけを反転する。Nodeのコストは「そのNodeから出て目的地まで」。"""
    graph = make_graph(LINE_NODES, LINE_EDGES)
    lazy, statics, structure = build_all(graph)
    states = state_index(lazy)
    tree = routing.build_turn_expanded_tree(
        structure, np.ones(structure.state_count), statics.edge_length_m,
        np.array([states["BC"]], dtype=np.int64), lazy.node_count, reverse=True,
        edge_seconds=np.ones(structure.state_count),
    )
    assert tree.state_cost[states["AB"]] == pytest.approx(2.0)
    assert tree.node_cost[lazy.node_id_to_index["A"]] == pytest.approx(2.0)
    assert tree.node_length_m[lazy.node_id_to_index["A"]] == pytest.approx(200.0)


def test_reverse_tree_rejects_time_bins():
    """逆向きの木には到達時刻が無い。ビンを渡せば時刻が反転した条件で評価した経路が返るため送出する。"""
    lazy, statics, structure, states, cost, seconds = _line_bins()
    with pytest.raises(ValueError):
        routing.build_turn_expanded_tree(
            structure, cost, statics.edge_length_m, np.array([states["BC"]], dtype=np.int64),
            lazy.node_count, reverse=True, edge_seconds=seconds, bin_seconds=5.0,
        )


# --- 経路の復元 ---


def test_forward_path_runs_from_the_tree_source_to_the_state():
    graph = make_graph(LINE_NODES, LINE_EDGES)
    lazy, statics, structure = build_all(graph)
    states = state_index(lazy)
    tree = routing.build_turn_expanded_tree(
        structure, np.ones(structure.state_count), statics.edge_length_m,
        np.array([states["AB"]], dtype=np.int64), lazy.node_count,
        edge_seconds=np.ones(structure.state_count),
    )
    assert routing.turn_expanded_path_from_state(tree, states["BC"]) == [states["AB"], states["BC"]]
    assert routing.turn_expanded_path_edge_indices(tree, lazy.node_id_to_index["C"]) == [
        states["AB"], states["BC"],
    ]


def test_backward_path_is_already_in_travel_order():
    """逆向きの木では、前任者を辿ることが目的地へ近づくことに当たるため反転しない。"""
    graph = make_graph(LINE_NODES, LINE_EDGES)
    lazy, statics, structure = build_all(graph)
    states = state_index(lazy)
    tree = routing.build_turn_expanded_tree(
        structure, np.ones(structure.state_count), statics.edge_length_m,
        np.array([states["BC"]], dtype=np.int64), lazy.node_count, reverse=True,
        edge_seconds=np.ones(structure.state_count),
    )
    assert routing.turn_expanded_path_from_state_to_source(tree, states["AB"]) == [
        states["AB"], states["BC"],
    ]


# --- combine_forward_backward_at_nodes ---


def test_junction_includes_the_turn_cost_at_the_meeting_node():
    """Nodeで前後の木を足すだけだと、そこを通り抜けるターンの費用が抜ける。"""
    graph = make_graph(PLUS_NODES, PLUS_EDGES)
    lazy, statics, structure = build_all(graph, spec=TURN_SPEC)
    states = state_index(lazy)
    cost = np.ones(structure.state_count)
    forward = routing.build_turn_expanded_tree(
        structure, cost, statics.edge_length_m, np.array([states["WC"]], dtype=np.int64),
        lazy.node_count,
        edge_seconds=np.ones(structure.state_count),
    )
    backward = routing.build_turn_expanded_tree(
        structure, cost, statics.edge_length_m, np.array([states["CN"]], dtype=np.int64),
        lazy.node_count, reverse=True,
        edge_seconds=np.ones(structure.state_count),
    )
    junction = routing.combine_forward_backward_at_nodes(
        structure, forward, backward, lazy.node_count
    )
    center = lazy.node_id_to_index["C"]
    assert junction.cost[center] == pytest.approx(1.0 + TURN_SPEC.left_seconds + 1.0)
    assert junction.cost[center] > forward.node_cost[center] + backward.node_cost[center]
    assert junction.forward_state[center] == states["WC"]
    assert junction.backward_state[center] == states["CN"]
    assert junction.length_m[center] == pytest.approx(200.0)


def test_junction_leaves_unreachable_nodes_empty():
    graph = make_graph(LINE_NODES, LINE_EDGES)
    lazy, statics, structure = build_all(graph)
    states = state_index(lazy)
    cost = np.ones(structure.state_count)
    node_count = lazy.node_count
    forward = routing.build_turn_expanded_tree(
        structure, cost, statics.edge_length_m, np.array([states["AB"]], dtype=np.int64), node_count,
        edge_seconds=np.ones(structure.state_count),
    )
    backward = routing.build_turn_expanded_tree(
        structure, cost, statics.edge_length_m, np.array([states["BC"]], dtype=np.int64),
        node_count, reverse=True,
        edge_seconds=np.ones(structure.state_count),
    )
    junction = routing.combine_forward_backward_at_nodes(structure, forward, backward, node_count)
    isolated = lazy.node_id_to_index["Z"]
    assert junction.cost[isolated] == math.inf
    assert np.isnan(junction.length_m[isolated])
    assert junction.forward_state[isolated] == -1
    assert junction.backward_state[isolated] == -1


# --- 時刻ビンの契約 ---


def test_one_dimensional_cost_becomes_a_single_bin():
    cost_bins, seconds_bins = routing._time_bin_arrays(
        "caller", np.array([1.0, 2.0, 3.0]), np.array([4.0, 5.0, 6.0]), math.inf
    )
    assert cost_bins.shape == (1, 3)
    assert seconds_bins.shape == (1, 3)
    assert list(seconds_bins[0]) == [4.0, 5.0, 6.0]


def test_two_dimensional_cost_is_passed_through():
    cost = np.ones((3, 4))
    cost_bins, _ = routing._time_bin_arrays("caller", cost, np.ones((3, 4)), 60.0)
    assert cost_bins.shape == (3, 4)


@pytest.mark.parametrize("cost", [np.ones(3), np.ones((2, 3))])
def test_cost_always_requires_plain_seconds(cost):
    """秒が無いと到達時刻の時計がコストで進む。ビン1本でも同じで、単位が混ざる。"""
    with pytest.raises(ValueError):
        routing._time_bin_arrays("caller", cost, None, 60.0)


def test_more_than_two_dimensions_is_refused():
    """黙って(1, n)へ潰すと、ビン数の食い違いの検査もすり抜けてJITが範囲外を読む。"""
    with pytest.raises(ValueError):
        routing._time_bin_arrays("caller", np.ones((2, 3, 4)), np.ones((2, 3, 4)), 60.0)


@pytest.mark.parametrize("bin_seconds", [0.0, -60.0, math.inf, math.nan])
def test_time_binned_cost_requires_a_positive_finite_bin_width(bin_seconds):
    """幅が無いと全区間が先頭のビンへ落ち、例外もNaNも出ないまま結果だけが変わる。"""
    with pytest.raises(ValueError):
        routing._time_bin_arrays("caller", np.ones((2, 3)), np.ones((2, 3)), bin_seconds)


def test_mismatched_cost_and_seconds_shapes_raise():
    """JITした探索は境界を検査しない。ビン数が食い違えば範囲外の読み出しになる。"""
    with pytest.raises(ValueError):
        routing._time_bin_arrays("caller", np.ones((2, 3)), np.ones((2, 4)), 60.0)


# --- turn_expanded_shortest_path ---


def test_shortest_path_returns_edge_indices_in_travel_order():
    """格子の対角へは、区間コストが一様なら最小ホップ数ぶんの区間を通る。"""
    graph = make_grid(GRID_SIZE)
    last = GRID_SIZE - 1
    goal = f"n{last}_{last}"
    lazy, _, structure = build_all(graph)
    path = routing.turn_expanded_shortest_path(
        structure, np.ones(structure.state_count),
        np.zeros(lazy.node_count), out_states(lazy, "n0_0"),
        lazy.node_id_to_index[goal],
        edge_seconds=np.ones(structure.state_count),
    )
    assert path is not None
    assert len(path) == last * 2
    assert graph.edges[lazy.edge_ids[path[0]]].from_node_id == "n0_0"
    assert graph.edges[lazy.edge_ids[path[-1]]].to_node_id == goal
    hops = [lazy.edge_ids[index] for index in path]
    assert all(
        graph.edges[a].to_node_id == graph.edges[b].from_node_id for a, b in zip(hops, hops[1:])
    )


def test_shortest_path_of_a_single_entry_edge_is_that_edge():
    """起点から出る区間の終点が既に目的地なら、その1本だけを返す。"""
    graph = make_graph(LINE_NODES, LINE_EDGES)
    lazy, _, structure = build_all(graph)
    states = state_index(lazy)
    path = routing.turn_expanded_shortest_path(
        structure, np.ones(structure.state_count), np.zeros(lazy.node_count),
        np.array([states["AB"]], dtype=np.int64), lazy.node_id_to_index["B"],
        edge_seconds=np.ones(structure.state_count),
    )
    assert path == [states["AB"]]


def test_shortest_path_ignores_non_finite_costs_among_seeds_and_successors():
    """コストinfの区間は、起点から出る区間としても遷移先としても通らない。"""
    graph = make_graph(PLUS_NODES, PLUS_EDGES)
    lazy, _, structure = build_all(graph)
    states = state_index(lazy)
    cost = np.ones(structure.state_count)
    cost[states["CW"]] = np.inf
    cost[states["CE"]] = 3.0
    cost[states["CN"]] = 1.0
    cost[states["CS"]] = 2.0
    path = routing.turn_expanded_shortest_path(
        structure, cost, np.zeros(lazy.node_count), out_states(lazy, "C"),
        lazy.node_id_to_index["E"],
        edge_seconds=np.ones(structure.state_count),
    )
    assert path == [states["CE"]]


def test_shortest_path_is_none_when_the_goal_cannot_be_reached():
    graph = make_graph(LINE_NODES, LINE_EDGES)
    lazy, _, structure = build_all(graph)
    states = state_index(lazy)
    path = routing.turn_expanded_shortest_path(
        structure, np.ones(structure.state_count), np.zeros(lazy.node_count),
        np.array([states["AB"]], dtype=np.int64), lazy.node_id_to_index["Z"],
        edge_seconds=np.ones(structure.state_count),
    )
    assert path is None


FORK_NODES = {
    "A": (35.00, 139.00),
    "B": (35.01, 139.01),
    "D": (34.99, 139.01),
    "C": (35.00, 139.02),
}
FORK_EDGES = {
    "AB": ("A", "B", 100.0, 45.0),
    "BA": ("B", "A", 100.0, 225.0),
    "BC": ("B", "C", 100.0, 135.0),
    "CB": ("C", "B", 100.0, 315.0),
    "AD": ("A", "D", 100.0, 135.0),
    "DA": ("D", "A", 100.0, 315.0),
    "DC": ("D", "C", 100.0, 45.0),
    "CD": ("C", "D", 100.0, 225.0),
}


def test_shortest_path_pays_for_turns_not_only_for_edges():
    """右折より左折が高い較正では、区間コストが安い方でも曲がりの高い経路は選ばれない。"""
    graph = make_graph(FORK_NODES, FORK_EDGES)
    lazy, _, structure = build_all(graph, spec=TURN_SPEC)
    states = state_index(lazy)
    cost = np.ones(structure.state_count)
    cost[states["BC"]] = 2.0
    path = routing.turn_expanded_shortest_path(
        structure, cost, np.zeros(lazy.node_count),
        out_states(lazy, "A"), lazy.node_id_to_index["C"],
        edge_seconds=np.ones(structure.state_count),
    )
    assert path == [states["AB"], states["BC"]]


@pytest.mark.parametrize(("bin_seconds", "expected_middle"), [(20.0, "B"), (5.0, "D")])
def test_shortest_path_reads_the_cost_of_the_bin_it_arrives_in(bin_seconds, expected_middle):
    """出発からの経過時間でビンが変わると、同じ入力でも通る経路が変わる。"""
    graph = make_graph(FORK_NODES, FORK_EDGES)
    lazy, _, structure = build_all(graph)
    states = state_index(lazy)
    cost = np.ones((2, structure.state_count))
    cost[0, states["DC"]] = 100.0
    cost[1, states["BC"]] = 100.0
    seconds = np.full((2, structure.state_count), 10.0)
    path = routing.turn_expanded_shortest_path(
        structure, cost, np.zeros(lazy.node_count), out_states(lazy, "A"),
        lazy.node_id_to_index["C"], edge_seconds=seconds, bin_seconds=bin_seconds,
    )
    assert path is not None
    assert graph.edges[lazy.edge_ids[path[0]]].to_node_id == expected_middle


# --- 優先度キューの伸長 ---


@pytest.mark.parametrize("carries_g", [True, False])
def test_heap_returns_every_entry_in_key_order_across_growth(carries_g):
    """容量1から何度も伸ばしても、積んだエントリを1件も欠かさずキーの昇順で返す。

    `g`の列を持つヒープは積んだ`g`をそのまま、持たないヒープはキーを`g`として返す。
    `g`の列を持つヒープは、伸ばした後も全列が要素数以上の長さを持つ（JITは配列の境界を
    検査しないため、1列だけ伸ばし忘れても出力からは見えないことがある）。
    """
    keys = np.random.default_rng(0).permutation(50).astype(float)
    heap = routing._empty_heap(1, carries_g)
    size = 0
    for state, key in enumerate(keys):
        if carries_g:
            heap, size = routing._heap_push(heap, size, key, state, key * 10.0 + 0.5)
        else:
            heap, size = routing._heap_push(heap, size, key, state)
    columns = heap[:3] if carries_g else heap[:2]
    assert all(column.shape[0] >= size for column in columns)
    popped = []
    while size > 0:
        g, state, size = routing._heap_pop(heap, size)
        popped.append((keys[state], g))
    assert [key for key, _ in popped] == sorted(keys)
    assert [g for _, g in popped] == [key * 10.0 + 0.5 if carries_g else key for key, _ in popped]


@pytest.fixture
def tiny_heap(monkeypatch):
    """優先度キューの初期容量を「種の数＋1」まで絞り、小さなグラフでも伸長を何度も通す。"""
    monkeypatch.setattr(routing, "_HEAP_INITIAL_SLACK", 1)


def test_tree_costs_stay_exact_while_the_queue_grows(tiny_heap):
    """伸長をまたいでも、各Nodeのコストは起点からの区間の本数のまま（起点自身はUターン1回の2）。"""
    lazy, _, _, tree = grid_tree(size=5)
    for node_id, node_index in lazy.node_id_to_index.items():
        row, col = (int(part) for part in node_id[1:].split("_"))
        hops = row + col
        assert tree.node_cost[node_index] == pytest.approx(hops if hops else 2), node_id


def test_shortest_path_stays_exact_while_the_queue_grows(tiny_heap):
    """伸長をまたいでも、A*は唯一の最安経路（1行目を東へ、最後の列を北へ）を返す。

    下界（目的地までの格子の歩数×最安の区間コスト）を0でなくし、キー（`g`＋下界）と`g`を
    別の値にする——取り出しがキーを`g`として返すと、経路が変わる。
    `g`の列そのものが伸長で崩れないことは、部品のテスト（上）が見る。この経路では崩れた`g`が
    前任者の輪を作り、経路の復元が止まらなくなることがあるため、ここでは確かめない。
    """
    size = 5
    last = size - 1
    graph = make_grid(size)
    lazy, _, structure = build_all(graph)
    states = state_index(lazy)
    route = [f"n0_{col}>n0_{col + 1}" for col in range(last)]
    route += [f"n{row}_{last}>n{row + 1}_{last}" for row in range(last)]
    cost = np.full(structure.state_count, 3.0)
    for edge_id in route:
        cost[states[edge_id]] = 1.0
    heuristic = np.zeros(lazy.node_count)
    for node_id, node_index in lazy.node_id_to_index.items():
        row, col = (int(part) for part in node_id[1:].split("_"))
        heuristic[node_index] = (last - row) + (last - col)
    path = routing.turn_expanded_shortest_path(
        structure, cost, heuristic, out_states(lazy, "n0_0"),
        lazy.node_id_to_index[f"n{last}_{last}"],
        edge_seconds=np.ones(structure.state_count),
    )
    assert path == [states[edge_id] for edge_id in route]


# --- 探索のJITの型 ---


def test_each_search_compiles_once_whatever_arrays_the_caller_passes():
    """イメージの組み立てで焼いたコンパイル結果（`compile_search_kernels`）は、型の同じ呼び出しにしか効かない。
    探索の入口が型を揃えるため、呼び出し側の配列のdtype・並び・読み取り専用かに依らず、探索1つにつき
    コンパイルは1本で済む——本番の最初のルート生成がコンパイルを払わない。"""
    if numba.config.DISABLE_JIT:
        pytest.skip("JITを切って測っている（numbaの型がそもそも無い）")
    routing.compile_search_kernels()
    lazy, statics, structure = build_all(make_grid(3))
    state_count = structure.state_count
    read_only = np.ones((2, state_count))
    read_only.flags.writeable = False
    costs = [
        np.ones(state_count, dtype=np.float32),
        np.ones((state_count, 2)).T,  # C順でない
        read_only,
    ]
    origin_states = out_states(lazy, "n0_0").astype(np.int32)
    for cost in costs:
        routing.build_turn_expanded_tree(
            structure, cost, statics.edge_length_m.astype(np.float32), origin_states, lazy.node_count,
            edge_seconds=cost, bin_seconds=3600.0,
        )
        routing.turn_expanded_shortest_path(
            structure, cost, np.zeros(lazy.node_count, dtype=np.float32), origin_states,
            lazy.node_id_to_index["n2_2"], edge_seconds=cost, bin_seconds=3600.0,
        )
    routing.build_turn_expanded_tree(
        structure, costs[0], statics.edge_length_m, origin_states, lazy.node_count,
        reverse=True, edge_seconds=costs[0],
    )

    assert len(routing._turn_expanded_dijkstra.signatures) == 1
    assert len(routing._turn_expanded_astar.signatures) == 1
