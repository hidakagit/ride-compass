import math
import random
from collections.abc import Callable

import numpy as np
import pytest

from app.domain.graph import DirectedEdge, Node, RoadGraph
from app.domain.route import Coordinates
from app.domain.routing import (
    LazyGraphEdgeMismatchError,
    LazyRoadGraph,
    build_csr_structure,
    build_lazy_road_graph,
    build_node_spatial_index,
    build_search_graph_statics,
    build_shortest_path_tree,
    concat_node_paths,
    find_missing_lazy_graph_edge_id,
    find_nearest_node_indexed,
    overlap_ratio,
    path_to_edge_ids_lazy,
    select_diverse_by_overlap,
    shortest_path_node_ids_lazy,
    tree_path_edge_indices,
)


def _node(node_id: str, lat: float, lon: float) -> Node:
    return Node(node_id=node_id, latitude=lat, longitude=lon)


def _edge(edge_id: str, from_id: str, to_id: str, distance_m: float = 100.0) -> DirectedEdge:
    return DirectedEdge(
        edge_id=edge_id, from_node_id=from_id, to_node_id=to_id,
        geometry=[[35.700, 139.700], [35.701, 139.700]], distance_m=distance_m,
    )


def _linear_nearest_node(graph: RoadGraph, point: Coordinates) -> str | None:
    """総当たり線形探索によるground truth（テスト専用）。

    domain/routing.pyの本番実装は`find_nearest_node_indexed`（グリッドバケット索引）
    のみで、総当たり版は死コード監査（過去の監査）で削除済み。索引の正しさを検証する
    ためだけに、ここで最小限の総当たりをテストローカルに再実装する。
    """
    from app.domain.geo import haversine_distance_km

    nearest_node_id: str | None = None
    nearest_distance: float | None = None
    for node_id, node in graph.nodes.items():
        distance = haversine_distance_km(point, node)
        if nearest_distance is None or distance < nearest_distance:
            nearest_distance = distance
            nearest_node_id = node_id
    return nearest_node_id


def test_find_nearest_node_indexed_matches_linear_scan_result():
    # 改善計画T219: グリッドバケット索引でも総当たり線形探索と同じ結果を返すことを
    # 確認する。
    graph = RoadGraph(
        graph_version="v1",
        nodes={
            "near": _node("near", 35.700, 139.700),
            "far": _node("far", 36.000, 140.000),
        },
        edges={},
    )
    index = build_node_spatial_index(graph)

    result = find_nearest_node_indexed(index, Coordinates(latitude=35.701, longitude=139.701))

    assert result == "near"


def test_find_nearest_node_indexed_returns_none_for_empty_graph():
    graph = RoadGraph(graph_version="v1", nodes={}, edges={})
    index = build_node_spatial_index(graph)

    assert find_nearest_node_indexed(index, Coordinates(latitude=35.7, longitude=139.7)) is None


def test_find_nearest_node_indexed_matches_linear_scan_for_random_points():
    # 索引の「安全な打ち切り条件」の正しさを、ランダムな配置・多数の格子境界を跨ぐ
    # クエリ点で線形探索と突き合わせて検証する（グリッドセルをまたぐケースの回帰確認）。
    rng = random.Random(42)
    nodes = {
        f"n{i}": _node(f"n{i}", 35.6 + rng.uniform(-0.05, 0.05), 139.7 + rng.uniform(-0.05, 0.05))
        for i in range(200)
    }
    graph = RoadGraph(graph_version="v1", nodes=nodes, edges={})
    index = build_node_spatial_index(graph, cell_size_deg=0.01)

    for _ in range(100):
        point = Coordinates(
            latitude=35.6 + rng.uniform(-0.06, 0.06), longitude=139.7 + rng.uniform(-0.06, 0.06)
        )
        assert find_nearest_node_indexed(index, point) == _linear_nearest_node(graph, point)


def test_build_node_spatial_index_with_node_ids_skips_isolated_nearest_node():
    # 改善計画T256回帰テスト: 地理的に最も近いNode（"isolated"）が幹線道路にしか
    # 接続していない場合、node_idsで絞った索引はそれを候補から除き、次に近い
    # 経路探索可能なNode（"routable"）を返す。
    graph = RoadGraph(
        graph_version="v1",
        nodes={
            "isolated": _node("isolated", 35.7001, 139.7001),  # クエリ点に最も近いが孤立
            "routable": _node("routable", 35.702, 139.702),  # やや遠いが経路探索可能
        },
        edges={},
    )
    index = build_node_spatial_index(graph, node_ids={"routable"})

    result = find_nearest_node_indexed(index, Coordinates(latitude=35.700, longitude=139.700))

    assert result == "routable"


def test_concat_node_paths_removes_duplicate_boundary_nodes():
    result = concat_node_paths([["a", "b", "c"], ["c", "d"], ["d", "e", "f"]])

    assert result == ["a", "b", "c", "d", "e", "f"]


def test_concat_node_paths_handles_empty_input():
    assert concat_node_paths([]) == []


# --- 改善計画T529→T536: rustworkxベースのlazy評価版（2点間探索）。
# T536でNode/Edge payloadを整数indexへ変更したため、edge_cost_fn/
# estimate_cost_fnはedge_id/node_id文字列ではなくlazy_graph.edge_ids/index_to_node_id上の
# 整数indexを受け取る契約になった（domain/routing.py: LazyRoadGraphのdocstring参照）。 ---


def _cost_fn_from_dict(lazy_graph: LazyRoadGraph, edge_costs: dict[str, float]) -> Callable[[int], float]:
    """テスト用のedge_cost_fn。`lazy_graph.edge_ids`（edge_index→edge_id）を介して
    edge_id文字列ベースの`edge_costs`辞書から整数indexベースのlistへ変換する
    （改善計画T536でedge_cost_fnの契約が整数indexへ変わったため）。`math.inf`は
    「Hard Constraintで除外」を表す（`shortest_path_node_ids_lazy`のdocstring参照）。
    """
    values = [edge_costs.get(edge_id, math.inf) for edge_id in lazy_graph.edge_ids]
    return values.__getitem__


def _zero_estimate_fn(_node_index: int) -> float:
    """常に0を返すヒューリスティック（admissibleの下限）。A*をDijkstraと同じ挙動へ
    単純化し、経路選択そのものの正しさだけを検証する。"""
    return 0.0


def test_build_lazy_road_graph_keeps_edge_id_ascending_for_parallel_edges_without_costs():
    # 改善計画T529→T536: コスト未確定（edge_cost_by_id省略）の場合、「cost最小のEdgeを
    # 採用」はできないため、edge_idの昇順で先頭を採用する
    # 決定的な選択にフォールバックすることを確認する（並行Edgeの回帰観点、docstring参照）。
    graph = RoadGraph(
        graph_version="v1",
        nodes={"a": _node("a", 35.7, 139.7), "b": _node("b", 35.7, 139.7)},
        edges={
            "z_second": _edge("z_second", "a", "b", distance_m=50.0),
            "a_first": _edge("a_first", "a", "b", distance_m=200.0),
        },
    )
    lazy_graph = build_lazy_road_graph(graph)

    assert path_to_edge_ids_lazy(lazy_graph, ["a", "b"]) == ["a_first"]


def test_build_lazy_road_graph_picks_cheapest_edge_for_parallel_edges_when_costs_given():
    # 改善計画T536: edge_cost_by_idを渡すと、並行Edge（同一Node間の複数Edge）はcost最小の
    # Edgeを採用する（改善計画T363の元の意味論、コストが事前に判明しているため）。
    graph = RoadGraph(
        graph_version="v1",
        nodes={"a": _node("a", 35.7, 139.7), "b": _node("b", 35.7, 139.7)},
        edges={
            "cheap_first": _edge("cheap_first", "a", "b", distance_m=50.0),
            "expensive_second": _edge("expensive_second", "a", "b", distance_m=200.0),
        },
    )
    lazy_graph = build_lazy_road_graph(
        graph, edge_cost_by_id={"cheap_first": 5.0, "expensive_second": 999.0}
    )

    assert path_to_edge_ids_lazy(lazy_graph, ["a", "b"]) == ["cheap_first"]


def test_build_lazy_road_graph_parallel_edge_selection_is_order_independent():
    # 改善計画T536回帰テスト: 登場順（edge_id昇順）が「先」の方がcost最小であっても、
    # 必ずcost最小のEdgeが選ばれることを検証する（前テストとは登場順とcost最小の
    # 対応関係を逆にしてある）。
    graph = RoadGraph(
        graph_version="v1",
        nodes={"a": _node("a", 35.7, 139.7), "b": _node("b", 35.7, 139.7)},
        edges={
            "a_first": _edge("a_first", "a", "b", distance_m=200.0),
            "z_second": _edge("z_second", "a", "b", distance_m=50.0),
        },
    )
    lazy_graph = build_lazy_road_graph(
        graph, edge_cost_by_id={"a_first": 999.0, "z_second": 5.0}
    )

    assert path_to_edge_ids_lazy(lazy_graph, ["a", "b"]) == ["z_second"]


def test_shortest_path_node_ids_lazy_picks_lower_cost_route():
    graph = RoadGraph(
        graph_version="v1",
        nodes={n: _node(n, 35.7, 139.7) for n in ["a", "b", "c", "d"]},
        edges={
            "direct": _edge("direct", "a", "d"),
            "via_b": _edge("via_b", "a", "b"),
            "via_c": _edge("via_c", "b", "d"),
        },
    )
    lazy_graph = build_lazy_road_graph(graph)
    cost_fn = _cost_fn_from_dict(lazy_graph, {"direct": 1000.0, "via_b": 10.0, "via_c": 10.0})

    path = shortest_path_node_ids_lazy(lazy_graph, "a", "d", cost_fn, _zero_estimate_fn)

    assert path == ["a", "b", "d"]


def test_shortest_path_node_ids_lazy_returns_none_when_unreachable():
    graph = RoadGraph(
        graph_version="v1",
        nodes={"a": _node("a", 35.7, 139.7), "b": _node("b", 35.7, 139.7)},
        edges={},
    )
    lazy_graph = build_lazy_road_graph(graph)

    assert (
        shortest_path_node_ids_lazy(lazy_graph, "a", "b", _cost_fn_from_dict(lazy_graph, {}), _zero_estimate_fn)
        is None
    )


def test_shortest_path_node_ids_lazy_same_start_and_end_returns_single_node():
    graph = RoadGraph(graph_version="v1", nodes={"a": _node("a", 35.7, 139.7)}, edges={})
    lazy_graph = build_lazy_road_graph(graph)

    assert (
        shortest_path_node_ids_lazy(lazy_graph, "a", "a", _cost_fn_from_dict(lazy_graph, {}), _zero_estimate_fn)
        == ["a"]
    )


def test_shortest_path_node_ids_lazy_excludes_disallowed_edges():
    # 改善計画T529: LazyRoadGraphはHard Constraintを知らずトポロジ全体を含むため、
    # edge_cost_fnがmath.infを返すことで「除外」を表現する（グラフ構築時にEdge自体を
    # 除外するのではなく、コスト側で通行不能を表す仕組み）。
    graph = RoadGraph(
        graph_version="v1",
        nodes={"a": _node("a", 35.70, 139.70), "b": _node("b", 35.71, 139.71), "c": _node("c", 35.72, 139.72)},
        edges={
            "e1": _edge("e1", "a", "b"),
            "e2": _edge("e2", "b", "c"),  # Hard Constraintで除外（math.infを返す）
            "e3": _edge("e3", "a", "c"),  # cost算出不可（math.infを返す）
        },
    )
    lazy_graph = build_lazy_road_graph(graph)
    cost_fn = _cost_fn_from_dict(lazy_graph, {"e1": 100.0})  # e2/e3は辞書に無い＝math.inf

    assert shortest_path_node_ids_lazy(lazy_graph, "a", "b", cost_fn, _zero_estimate_fn) == ["a", "b"]
    assert shortest_path_node_ids_lazy(lazy_graph, "b", "c", cost_fn, _zero_estimate_fn) is None
    assert shortest_path_node_ids_lazy(lazy_graph, "a", "c", cost_fn, _zero_estimate_fn) is None


def test_path_to_edge_ids_lazy_maps_consecutive_nodes_to_edges():
    graph = RoadGraph(
        graph_version="v1",
        nodes={n: _node(n, 35.7, 139.7) for n in ["a", "b", "c"]},
        edges={"e1": _edge("e1", "a", "b"), "e2": _edge("e2", "b", "c")},
    )
    lazy_graph = build_lazy_road_graph(graph)

    assert path_to_edge_ids_lazy(lazy_graph, ["a", "b", "c"]) == ["e1", "e2"]


def test_shortest_path_node_ids_lazy_uses_estimate_fn_to_prefer_direct_route():
    # A*のestimate_cost_fnが実際に探索へ影響する（単なるダミー引数ではない）ことを、
    # 目的地に近いノードを優先探索する簡単なヒューリスティックで確認する。
    # 経路自体はDijkstraと同じ最小コストに収束するため結果は変わらないが、
    # estimate_fnが呼ばれること自体を検証する。
    graph = RoadGraph(
        graph_version="v1",
        nodes={n: _node(n, 35.7, 139.7) for n in ["a", "b", "c"]},
        edges={"e1": _edge("e1", "a", "b"), "e2": _edge("e2", "b", "c")},
    )
    lazy_graph = build_lazy_road_graph(graph)
    cost_fn = _cost_fn_from_dict(lazy_graph, {"e1": 10.0, "e2": 10.0})
    estimate_calls: list[int] = []

    def _tracking_estimate_fn(node_index: int) -> float:
        estimate_calls.append(node_index)
        return 0.0

    path = shortest_path_node_ids_lazy(lazy_graph, "a", "c", cost_fn, _tracking_estimate_fn)

    assert path == ["a", "b", "c"]
    assert len(estimate_calls) > 0


# --- 改善計画T531: 一対全最短経路木（scipy CSR）・多様性間引き ---


def _random_road_graph(seed: int, rows: int = 7, cols: int = 7, extra_edges: int = 40) -> RoadGraph:
    """格子＋ランダムな追加Edgeの有向グラフ。距離はEdgeごとにランダム（50〜300m）。
    一対全木（scipy）と2点間A*（rustworkx）が同じコストで一致することを検証する材料。"""
    rng = random.Random(seed)
    nodes: dict[str, Node] = {}
    for r in range(rows):
        for c in range(cols):
            nodes[f"n{r}-{c}"] = _node(f"n{r}-{c}", 35.70 + r * 0.001, 139.70 + c * 0.001)
    edges: dict[str, DirectedEdge] = {}

    def add(u: str, v: str) -> None:
        edge_id = f"{u}>{v}"
        if edge_id not in edges:
            edges[edge_id] = _edge(edge_id, u, v, distance_m=rng.uniform(50.0, 300.0))

    for r in range(rows):
        for c in range(cols):
            if c + 1 < cols:
                add(f"n{r}-{c}", f"n{r}-{c + 1}")
                add(f"n{r}-{c + 1}", f"n{r}-{c}")
            if r + 1 < rows:
                add(f"n{r}-{c}", f"n{r + 1}-{c}")
                add(f"n{r + 1}-{c}", f"n{r}-{c}")
    node_ids = list(nodes)
    for _ in range(extra_edges):
        u, v = rng.sample(node_ids, 2)
        add(u, v)
    return RoadGraph(graph_version="v1", nodes=nodes, edges=edges)


def _cost_array(lazy_graph: LazyRoadGraph, edge_costs: dict[str, float]) -> np.ndarray:
    return np.array([edge_costs.get(edge_id, math.inf) for edge_id in lazy_graph.edge_ids], dtype=float)


def _path_cost(lazy_graph: LazyRoadGraph, node_path: list[str], cost_array: np.ndarray) -> float:
    total = 0.0
    for u, v in zip(node_path, node_path[1:]):
        edge_index = lazy_graph.edge_index_by_node_pair[(lazy_graph.node_id_to_index[u], lazy_graph.node_id_to_index[v])]
        total += cost_array[edge_index]
    return total


def test_build_csr_structure_matches_node_pair_index():
    graph = _random_road_graph(seed=1)
    lazy_graph = build_lazy_road_graph(graph)

    structure = build_csr_structure(lazy_graph)

    n = len(lazy_graph.index_to_node_id)
    assert structure.node_count == n
    assert structure.indptr[-1] == len(lazy_graph.edge_index_by_node_pair)
    assert np.all(np.diff(structure.entry_keys) > 0)  # 昇順かつ重複なし
    for (u, v), edge_index in lazy_graph.edge_index_by_node_pair.items():
        row = slice(structure.indptr[u], structure.indptr[u + 1])
        position = structure.indptr[u] + list(structure.indices[row]).index(v)
        assert structure.entry_edge_index[position] == edge_index
        assert structure.entry_keys[position] == u * n + v


def test_build_csr_structure_handles_graph_without_edges():
    graph = RoadGraph(graph_version="v1", nodes={"a": _node("a", 35.7, 139.7)}, edges={})
    structure = build_csr_structure(build_lazy_road_graph(graph))

    assert structure.node_count == 1
    assert list(structure.indptr) == [0, 0]
    assert len(structure.indices) == 0


def test_build_search_graph_statics_aligns_edge_lengths_with_lazy_edge_order():
    graph = _random_road_graph(seed=2)
    lazy_graph = build_lazy_road_graph(graph)

    statics = build_search_graph_statics(lazy_graph, graph)

    assert list(statics.edge_length_m) == [graph.edges[e].distance_m for e in lazy_graph.edge_ids]
    assert statics.csr.node_count == len(lazy_graph.index_to_node_id)


def test_find_missing_lazy_graph_edge_id_returns_none_when_consistent():
    graph = _random_road_graph(seed=2)
    lazy_graph = build_lazy_road_graph(graph)

    assert find_missing_lazy_graph_edge_id(lazy_graph, graph) is None


def test_find_missing_lazy_graph_edge_id_detects_stale_lazy_graph_after_resplit():
    # 改善計画T569: lazy_graphが再split前のgraphから作られ、graph.edgesのedge_idが
    # 振り直された（再splitされた）場合の不整合検知（build_search_graph_staticsから
    # 独立させた軽量版チェック、CSR構築を伴わない）。
    node_a, node_b = _node("a", 35.700, 139.700), _node("b", 35.701, 139.700)
    graph_v1 = RoadGraph(graph_version="test", nodes={"a": node_a, "b": node_b}, edges={"e1-v1": _edge("e1-v1", "a", "b")})
    lazy_graph = build_lazy_road_graph(graph_v1)
    graph_v2 = RoadGraph(graph_version="test", nodes={"a": node_a, "b": node_b}, edges={"e1-v2": _edge("e1-v2", "a", "b")})

    assert find_missing_lazy_graph_edge_id(lazy_graph, graph_v2) == "e1-v1"


def test_build_search_graph_statics_raises_lazy_graph_edge_mismatch_error_when_stale():
    node_a, node_b = _node("a", 35.700, 139.700), _node("b", 35.701, 139.700)
    graph_v1 = RoadGraph(graph_version="test", nodes={"a": node_a, "b": node_b}, edges={"e1-v1": _edge("e1-v1", "a", "b")})
    lazy_graph = build_lazy_road_graph(graph_v1)
    graph_v2 = RoadGraph(graph_version="test", nodes={"a": node_a, "b": node_b}, edges={"e1-v2": _edge("e1-v2", "a", "b")})

    with pytest.raises(LazyGraphEdgeMismatchError):
        build_search_graph_statics(lazy_graph, graph_v2)


def test_shortest_path_tree_costs_match_astar_for_random_graph():
    # 一対全木（scipy）の各Nodeへの最小コストが、同じコスト配列での2点間A*（rustworkx、
    # ヒューリスティック0）の経路コストと一致する（＝2つのライブラリで同じ意味論）。
    rng = random.Random(3)
    graph = _random_road_graph(seed=3)
    lazy_graph = build_lazy_road_graph(graph)
    edge_costs = {edge_id: edge.distance_m * rng.uniform(1.0, 2.0) for edge_id, edge in graph.edges.items()}
    cost_array = _cost_array(lazy_graph, edge_costs)
    source = "n3-3"

    tree = build_shortest_path_tree(
        build_csr_structure(lazy_graph), cost_array, build_search_graph_statics(lazy_graph, graph).edge_length_m, lazy_graph.node_id_to_index[source]
    )

    for node_id, node_index in lazy_graph.node_id_to_index.items():
        path = shortest_path_node_ids_lazy(lazy_graph, source, node_id, cost_array.tolist().__getitem__, _zero_estimate_fn)
        if path is None:
            assert not tree.is_reached(node_index)
        else:
            assert tree.cost[node_index] == pytest.approx(_path_cost(lazy_graph, path, cost_array), rel=1e-9)


def test_shortest_path_tree_length_matches_python_walk_along_predecessors():
    rng = random.Random(4)
    graph = _random_road_graph(seed=4)
    lazy_graph = build_lazy_road_graph(graph)
    edge_costs = {edge_id: edge.distance_m * rng.uniform(1.0, 2.0) for edge_id, edge in graph.edges.items()}
    length_array = build_search_graph_statics(lazy_graph, graph).edge_length_m
    source_index = lazy_graph.node_id_to_index["n0-0"]

    tree = build_shortest_path_tree(build_csr_structure(lazy_graph), _cost_array(lazy_graph, edge_costs), length_array, source_index)

    assert tree.length_m[source_index] == 0.0
    assert tree.predecessor[source_index] == -1
    for node_index in range(len(lazy_graph.index_to_node_id)):
        if not tree.is_reached(node_index):
            assert math.isnan(tree.length_m[node_index])
            continue
        walked = 0.0
        current = node_index
        while current != source_index:
            parent = int(tree.predecessor[current])
            walked += length_array[lazy_graph.edge_index_by_node_pair[(parent, current)]]
            current = parent
        assert tree.length_m[node_index] == pytest.approx(walked, rel=1e-12)


def test_shortest_path_tree_treats_inf_cost_edges_as_impassable():
    graph = RoadGraph(
        graph_version="v1",
        nodes={"a": _node("a", 35.700, 139.700), "b": _node("b", 35.701, 139.700), "c": _node("c", 35.702, 139.700)},
        edges={"ab": _edge("ab", "a", "b"), "bc": _edge("bc", "b", "c")},
    )
    lazy_graph = build_lazy_road_graph(graph)
    cost_array = _cost_array(lazy_graph, {"ab": 100.0, "bc": math.inf})

    tree = build_shortest_path_tree(build_csr_structure(lazy_graph), cost_array, build_search_graph_statics(lazy_graph, graph).edge_length_m, lazy_graph.node_id_to_index["a"])

    c_index = lazy_graph.node_id_to_index["c"]
    assert tree.is_reached(lazy_graph.node_id_to_index["b"])
    assert not tree.is_reached(c_index)
    assert tree.predecessor[c_index] == -1
    assert math.isnan(tree.length_m[c_index])
    assert tree_path_edge_indices(tree, lazy_graph, c_index) is None


def test_shortest_path_tree_cost_limit_prunes_nodes_beyond_limit():
    graph = RoadGraph(
        graph_version="v1",
        nodes={"a": _node("a", 35.700, 139.700), "b": _node("b", 35.701, 139.700), "c": _node("c", 35.702, 139.700)},
        edges={"ab": _edge("ab", "a", "b"), "bc": _edge("bc", "b", "c")},
    )
    lazy_graph = build_lazy_road_graph(graph)
    cost_array = _cost_array(lazy_graph, {"ab": 100.0, "bc": 100.0})
    structure = build_csr_structure(lazy_graph)
    lengths = build_search_graph_statics(lazy_graph, graph).edge_length_m
    a = lazy_graph.node_id_to_index["a"]

    unlimited = build_shortest_path_tree(structure, cost_array, lengths, a)
    limited = build_shortest_path_tree(structure, cost_array, lengths, a, cost_limit=150.0)

    assert unlimited.is_reached(lazy_graph.node_id_to_index["c"])
    assert limited.is_reached(lazy_graph.node_id_to_index["b"])
    assert not limited.is_reached(lazy_graph.node_id_to_index["c"])


def test_shortest_path_tree_traverses_zero_cost_edges():
    # 距離0のEdge（cost=0）はscipyのCSRで「明示的な0」として保持され、通行可能でなければ
    # ならない（疎行列の暗黙の0＝Edge無しと混同しない）。
    graph = RoadGraph(
        graph_version="v1",
        nodes={"a": _node("a", 35.700, 139.700), "b": _node("b", 35.701, 139.700), "c": _node("c", 35.702, 139.700)},
        edges={"ab": _edge("ab", "a", "b", distance_m=0.0), "bc": _edge("bc", "b", "c", distance_m=10.0)},
    )
    lazy_graph = build_lazy_road_graph(graph)
    cost_array = _cost_array(lazy_graph, {"ab": 0.0, "bc": 10.0})

    tree = build_shortest_path_tree(build_csr_structure(lazy_graph), cost_array, build_search_graph_statics(lazy_graph, graph).edge_length_m, lazy_graph.node_id_to_index["a"])

    c_index = lazy_graph.node_id_to_index["c"]
    assert tree.cost[c_index] == 10.0
    assert tree.length_m[c_index] == 10.0
    assert [lazy_graph.edge_ids[i] for i in tree_path_edge_indices(tree, lazy_graph, c_index)] == ["ab", "bc"]


def test_tree_path_edge_indices_reconstructs_connected_path_from_source():
    rng = random.Random(5)
    graph = _random_road_graph(seed=5)
    lazy_graph = build_lazy_road_graph(graph)
    edge_costs = {edge_id: edge.distance_m * rng.uniform(1.0, 2.0) for edge_id, edge in graph.edges.items()}
    source_index = lazy_graph.node_id_to_index["n2-2"]

    tree = build_shortest_path_tree(build_csr_structure(lazy_graph), _cost_array(lazy_graph, edge_costs), build_search_graph_statics(lazy_graph, graph).edge_length_m, source_index)

    assert tree_path_edge_indices(tree, lazy_graph, source_index) == []
    target_index = lazy_graph.node_id_to_index["n6-6"]
    edge_indices = tree_path_edge_indices(tree, lazy_graph, target_index)
    assert edge_indices
    edges = [graph.edges[lazy_graph.edge_ids[i]] for i in edge_indices]
    assert edges[0].from_node_id == "n2-2"
    assert edges[-1].to_node_id == "n6-6"
    for previous, following in zip(edges, edges[1:]):
        assert previous.to_node_id == following.from_node_id


def test_overlap_ratio_is_distance_weighted_on_candidate_side():
    lengths = np.array([100.0, 300.0, 600.0])

    assert overlap_ratio(np.array([0, 1, 2]), np.array([1]), lengths) == pytest.approx(0.3)
    assert overlap_ratio(np.array([0, 1]), np.array([2]), lengths) == 0.0
    assert overlap_ratio(np.array([], dtype=np.int64), np.array([0]), lengths) == 0.0


def test_select_diverse_by_overlap_skips_overlapping_items_and_respects_limit():
    lengths = np.array([100.0, 100.0, 100.0, 100.0, 100.0])
    items = {
        "first": [0, 1, 2],
        "same_corridor": [0, 1, 3],  # firstと2/3=67%重複→閾値0.6超で棄却
        "distinct": [3, 4],
        "half_overlap": [2, 4],  # firstと50%・distinctと50%→閾値0.6以下で採用
        "late": [4],
    }

    selected = select_diverse_by_overlap(list(items), items.__getitem__, lengths, max_overlap_ratios=[0.6], max_count=3)

    assert selected == ["first", "distinct", "half_overlap"]


def test_select_diverse_by_overlap_uses_compatibility_hook_and_skips_missing_paths():
    lengths = np.array([100.0, 100.0, 100.0])
    items = {"a": [0], "b": [1], "c": None, "d": [2]}
    incompatible = {("b", "a")}

    def compatible(item, selected):
        return all((item, other) not in incompatible for other in selected)

    selected = select_diverse_by_overlap(
        list(items), items.__getitem__, lengths, max_overlap_ratios=[0.5], max_count=10, is_compatible=compatible,
    )

    assert selected == ["a", "d"]  # bはaと非互換、cは経路無し
    # 決定的: 同じ入力で同じ結果
    assert selected == select_diverse_by_overlap(
        list(items), items.__getitem__, lengths, max_overlap_ratios=[0.5], max_count=10, is_compatible=compatible,
    )


def test_select_diverse_by_overlap_falls_back_to_relaxed_threshold_within_single_call():
    # 改善計画T557（項目15）: 複数の閾値max_overlap_ratiosを先頭から順に試す単一呼び出しへ
    # 統合（以前は呼び出し側が「1回目→埋まらなければrejected_by_overlapを2回目の緩い
    # 閾値で再検査」を2回のselect_diverse_by_overlap呼び出しとして組み立てていた）。
    lengths = np.array([100.0, 100.0, 100.0, 100.0])
    items = {"first": [0, 1, 2], "mostly_same": [0, 1, 3], "other": [3]}

    strict_only = select_diverse_by_overlap(
        list(items), items.__getitem__, lengths, max_overlap_ratios=[0.5], max_count=3,
    )
    assert strict_only == ["first", "other"]  # mostly_sameは67%重複で棄却、緩和パス無しのため復活しない

    with_relaxed_fallback = select_diverse_by_overlap(
        list(items), items.__getitem__, lengths, max_overlap_ratios=[0.5, 0.7], max_count=3,
    )
    # 1回目（閾値0.5）の採用分を先頭に保ったまま、2回目（閾値0.7）で残りを追加する。
    assert with_relaxed_fallback == ["first", "other", "mostly_same"]
