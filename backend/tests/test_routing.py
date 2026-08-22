import random

import pytest

from app.domain.evaluation import EdgeCostResult
from app.domain.graph import DirectedEdge, Node, RoadGraph
from app.domain.route import Coordinates
from app.domain.routing import (
    build_networkx_graph,
    build_node_spatial_index,
    build_sparse_graph,
    concat_node_paths,
    find_nearest_node,
    find_nearest_node_indexed,
    path_to_edge_ids,
    path_to_edge_ids_sparse,
    shortest_path_node_ids,
    shortest_path_node_ids_sparse,
)


def _node(node_id: str, lat: float, lon: float) -> Node:
    return Node(node_id=node_id, latitude=lat, longitude=lon)


def _edge(edge_id: str, from_id: str, to_id: str, distance_m: float = 100.0) -> DirectedEdge:
    return DirectedEdge(
        edge_id=edge_id, from_node_id=from_id, to_node_id=to_id,
        geometry=[[35.700, 139.700], [35.701, 139.700]], distance_m=distance_m,
    )


def _cost(edge_id: str, cost: float | None, allowed: bool = True) -> EdgeCostResult:
    return EdgeCostResult(edge_id=edge_id, cost=cost, difficulty=None, allowed=allowed)


def test_build_networkx_graph_includes_only_allowed_edges_with_cost():
    graph = RoadGraph(
        graph_version="v1",
        nodes={"a": _node("a", 35.70, 139.70), "b": _node("b", 35.71, 139.71), "c": _node("c", 35.72, 139.72)},
        edges={
            "e1": _edge("e1", "a", "b"),
            "e2": _edge("e2", "b", "c"),  # Hard Constraintで除外される想定
            "e3": _edge("e3", "a", "c"),  # cost算出不可の想定
        },
    )
    edge_costs = {
        "e1": _cost("e1", cost=100.0, allowed=True),
        "e2": _cost("e2", cost=None, allowed=False),
        "e3": _cost("e3", cost=None, allowed=True),
    }

    nx_graph = build_networkx_graph(graph, edge_costs)

    assert set(nx_graph.nodes) == {"a", "b", "c"}
    assert list(nx_graph.edges) == [("a", "b")]
    assert nx_graph["a"]["b"]["weight"] == 100.0
    assert nx_graph["a"]["b"]["edge_id"] == "e1"


def test_find_nearest_node_returns_closest():
    graph = RoadGraph(
        graph_version="v1",
        nodes={
            "near": _node("near", 35.700, 139.700),
            "far": _node("far", 36.000, 140.000),
        },
        edges={},
    )

    result = find_nearest_node(graph, Coordinates(latitude=35.701, longitude=139.701))

    assert result == "near"


def test_find_nearest_node_returns_none_for_empty_graph():
    graph = RoadGraph(graph_version="v1", nodes={}, edges={})

    assert find_nearest_node(graph, Coordinates(latitude=35.7, longitude=139.7)) is None


def test_find_nearest_node_indexed_matches_linear_scan_result():
    # 改善計画T219: グリッドバケット索引でもfind_nearest_node（線形探索）と
    # 同じ結果を返すことを確認する。
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
        assert find_nearest_node_indexed(index, point) == find_nearest_node(graph, point)


def test_shortest_path_node_ids_picks_lower_cost_route():
    graph = RoadGraph(
        graph_version="v1",
        nodes={n: _node(n, 35.7, 139.7) for n in ["a", "b", "c", "d"]},
        edges={
            "direct": _edge("direct", "a", "d"),
            "via_b": _edge("via_b", "a", "b"),
            "via_c": _edge("via_c", "b", "d"),
        },
    )
    edge_costs = {
        "direct": _cost("direct", cost=1000.0),  # 高コストの直行路
        "via_b": _cost("via_b", cost=10.0),
        "via_c": _cost("via_c", cost=10.0),
    }
    nx_graph = build_networkx_graph(graph, edge_costs)

    path = shortest_path_node_ids(nx_graph, "a", "d")

    assert path == ["a", "b", "d"]  # 遠回りでも合計コストが低い経路が選ばれる


def test_shortest_path_node_ids_returns_none_when_unreachable():
    graph = RoadGraph(
        graph_version="v1",
        nodes={"a": _node("a", 35.7, 139.7), "b": _node("b", 35.7, 139.7)},
        edges={},  # aとbを繋ぐEdgeが無い
    )
    nx_graph = build_networkx_graph(graph, {})

    assert shortest_path_node_ids(nx_graph, "a", "b") is None


def test_shortest_path_node_ids_same_start_and_end_returns_single_node():
    graph = RoadGraph(graph_version="v1", nodes={"a": _node("a", 35.7, 139.7)}, edges={})
    nx_graph = build_networkx_graph(graph, {})

    assert shortest_path_node_ids(nx_graph, "a", "a") == ["a"]


def test_path_to_edge_ids_maps_consecutive_nodes_to_edges():
    graph = RoadGraph(
        graph_version="v1",
        nodes={n: _node(n, 35.7, 139.7) for n in ["a", "b", "c"]},
        edges={"e1": _edge("e1", "a", "b"), "e2": _edge("e2", "b", "c")},
    )
    edge_costs = {"e1": _cost("e1", 10.0), "e2": _cost("e2", 10.0)}
    nx_graph = build_networkx_graph(graph, edge_costs)

    assert path_to_edge_ids(nx_graph, ["a", "b", "c"]) == ["e1", "e2"]


# --- 改善計画T220（T12 Stage 2）: scipy.sparse.csgraph版の回帰確認 ---
# build_networkx_graph/shortest_path_node_ids/path_to_edge_idsと同じ挙動になることを
# 各ケースで突き合わせる。


def test_shortest_path_node_ids_sparse_picks_lower_cost_route():
    graph = RoadGraph(
        graph_version="v1",
        nodes={n: _node(n, 35.7, 139.7) for n in ["a", "b", "c", "d"]},
        edges={
            "direct": _edge("direct", "a", "d"),
            "via_b": _edge("via_b", "a", "b"),
            "via_c": _edge("via_c", "b", "d"),
        },
    )
    edge_costs = {
        "direct": _cost("direct", cost=1000.0),
        "via_b": _cost("via_b", cost=10.0),
        "via_c": _cost("via_c", cost=10.0),
    }
    sparse_graph = build_sparse_graph(graph, edge_costs)

    path = shortest_path_node_ids_sparse(sparse_graph, "a", "d")

    assert path == ["a", "b", "d"]


def test_shortest_path_node_ids_sparse_returns_none_when_unreachable():
    graph = RoadGraph(
        graph_version="v1",
        nodes={"a": _node("a", 35.7, 139.7), "b": _node("b", 35.7, 139.7)},
        edges={},
    )
    sparse_graph = build_sparse_graph(graph, {})

    assert shortest_path_node_ids_sparse(sparse_graph, "a", "b") is None


def test_shortest_path_node_ids_sparse_same_start_and_end_returns_single_node():
    graph = RoadGraph(graph_version="v1", nodes={"a": _node("a", 35.7, 139.7)}, edges={})
    sparse_graph = build_sparse_graph(graph, {})

    assert shortest_path_node_ids_sparse(sparse_graph, "a", "a") == ["a"]


def test_shortest_path_node_ids_sparse_excludes_disallowed_and_costless_edges():
    graph = RoadGraph(
        graph_version="v1",
        nodes={"a": _node("a", 35.70, 139.70), "b": _node("b", 35.71, 139.71), "c": _node("c", 35.72, 139.72)},
        edges={
            "e1": _edge("e1", "a", "b"),
            "e2": _edge("e2", "b", "c"),  # Hard Constraintで除外
            "e3": _edge("e3", "a", "c"),  # cost算出不可
        },
    )
    edge_costs = {
        "e1": _cost("e1", cost=100.0, allowed=True),
        "e2": _cost("e2", cost=None, allowed=False),
        "e3": _cost("e3", cost=None, allowed=True),
    }
    sparse_graph = build_sparse_graph(graph, edge_costs)

    assert shortest_path_node_ids_sparse(sparse_graph, "a", "b") == ["a", "b"]
    assert shortest_path_node_ids_sparse(sparse_graph, "b", "c") is None
    assert shortest_path_node_ids_sparse(sparse_graph, "a", "c") is None


def test_path_to_edge_ids_sparse_maps_consecutive_nodes_to_edges():
    graph = RoadGraph(
        graph_version="v1",
        nodes={n: _node(n, 35.7, 139.7) for n in ["a", "b", "c"]},
        edges={"e1": _edge("e1", "a", "b"), "e2": _edge("e2", "b", "c")},
    )
    edge_costs = {"e1": _cost("e1", 10.0), "e2": _cost("e2", 10.0)}
    sparse_graph = build_sparse_graph(graph, edge_costs)

    assert path_to_edge_ids_sparse(sparse_graph, ["a", "b", "c"]) == ["e1", "e2"]


def test_build_sparse_graph_keeps_last_edge_for_parallel_edges_like_networkx():
    # scipy.sparse.coo_matrixは同一(row,col)への重複を合算してしまうため、build_sparse_graph
    # は疎行列を組む前にPython側で1本化する。NetworkXのadd_edge（後勝ち）と同じ挙動になる
    # ことを確認する（並行Edge、build_networkx_graphと同じ回帰観点）。
    graph = RoadGraph(
        graph_version="v1",
        nodes={"a": _node("a", 35.7, 139.7), "b": _node("b", 35.7, 139.7)},
        edges={
            "first": _edge("first", "a", "b", distance_m=50.0),
            "second": _edge("second", "a", "b", distance_m=200.0),
        },
    )
    edge_costs = {"first": _cost("first", cost=999.0), "second": _cost("second", cost=5.0)}
    sparse_graph = build_sparse_graph(graph, edge_costs)

    assert path_to_edge_ids_sparse(sparse_graph, ["a", "b"]) == ["second"]  # 後勝ち
    assert sparse_graph.matrix[sparse_graph.node_id_to_index["a"], sparse_graph.node_id_to_index["b"]] == 5.0


def test_sparse_graph_matches_networkx_for_random_graphs():
    # scipy版とNetworkX版が常に同じ経路コスト・到達可否を返すことを、ランダムな
    # グラフ・多数のノード対で突き合わせて確認する。
    rng = random.Random(7)
    node_ids = [f"n{i}" for i in range(30)]
    nodes = {node_id: _node(node_id, 35.7, 139.7) for node_id in node_ids}
    edges = {}
    edge_costs = {}
    for i in range(80):
        u, v = rng.sample(node_ids, 2)
        edge_id = f"e{i}"
        edges[edge_id] = _edge(edge_id, u, v, distance_m=rng.uniform(10, 500))
        allowed = rng.random() > 0.1
        edge_costs[edge_id] = _cost(edge_id, cost=rng.uniform(1, 500) if allowed else None, allowed=allowed)
    graph = RoadGraph(graph_version="v1", nodes=nodes, edges=edges)

    nx_graph = build_networkx_graph(graph, edge_costs)
    sparse_graph = build_sparse_graph(graph, edge_costs)

    for _ in range(50):
        start, end = rng.sample(node_ids, 2)
        nx_path = shortest_path_node_ids(nx_graph, start, end)
        sparse_path = shortest_path_node_ids_sparse(sparse_graph, start, end)
        if nx_path is None:
            assert sparse_path is None
        else:
            # 複数の等コスト最短路がありうるため、パス自体の完全一致ではなく
            # 合計コストの一致で比較する。
            nx_cost = sum(nx_graph[u][v]["weight"] for u, v in zip(nx_path, nx_path[1:]))
            sparse_edge_ids = path_to_edge_ids_sparse(sparse_graph, sparse_path)
            sparse_cost = sum(edge_costs[eid].cost for eid in sparse_edge_ids)
            assert sparse_cost == pytest.approx(nx_cost, abs=1e-6)


def test_concat_node_paths_removes_duplicate_boundary_nodes():
    result = concat_node_paths([["a", "b", "c"], ["c", "d"], ["d", "e", "f"]])

    assert result == ["a", "b", "c", "d", "e", "f"]


def test_concat_node_paths_handles_empty_input():
    assert concat_node_paths([]) == []
