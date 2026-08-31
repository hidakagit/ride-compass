import math
import random
from collections.abc import Callable

from app.domain.evaluation import EdgeCostResult
from app.domain.graph import DirectedEdge, Node, RoadGraph
from app.domain.route import Coordinates
from app.domain.routing import (
    build_lazy_road_graph,
    build_node_spatial_index,
    build_sparse_graph,
    concat_node_paths,
    find_nearest_node_indexed,
    path_to_edge_ids_lazy,
    path_to_edge_ids_sparse,
    routable_node_ids,
    shortest_path_node_ids_lazy,
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


def test_routable_node_ids_excludes_nodes_with_only_hard_filtered_edges():
    # 改善計画T256: 幹線道路（highway=trunk等）にしか接続していないNodeは、Hard
    # Constraint適用後のsparse_graph上では次数0の孤立点になる。routable_node_idsは
    # そのようなNodeを除外し、実際に経路探索可能なNodeだけを返す。
    graph = RoadGraph(
        graph_version="v1",
        nodes={
            "isolated": _node("isolated", 35.700, 139.700),
            "a": _node("a", 35.701, 139.701),
            "b": _node("b", 35.702, 139.702),
        },
        edges={
            "e_trunk": _edge("e_trunk", "isolated", "a"),  # Hard Constraintで除外される想定
            "e_ok": _edge("e_ok", "a", "b"),
        },
    )
    edge_costs = {
        "e_trunk": _cost("e_trunk", cost=None, allowed=False),
        "e_ok": _cost("e_ok", cost=100.0, allowed=True),
    }
    sparse_graph = build_sparse_graph(graph, edge_costs)

    result = routable_node_ids(sparse_graph)

    assert result == {"a", "b"}


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


# --- 改善計画T220（T12 Stage 2）: scipy.sparse.csgraph版のDijkstra探索 ---


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


def test_build_sparse_graph_keeps_cheapest_edge_for_parallel_edges():
    # scipy.sparse.coo_matrixは同一(row,col)への重複を合算してしまうため、build_sparse_graph
    # は疎行列を組む前にPython側で並行Edgeを1本化する（並行Edgeの回帰観点）。
    # 改善計画T363: 以前は「後から登場したEdgeで上書き」（graph.edgesの辞書挿入順＝
    # DBクエリの返却行順に依存）だったが、その行順序が非決定的（ORDER BY無し・実測で
    # Parallel Scanが選ばれ実行のたびに順序が変わる）と判明したため、辞書の挿入順に
    # 依存しないcost最小のEdgeを採用する方式へ改めた。本テストは「登場順が後の方」と
    # 「cost最小」を意図的に一致させ、min-cost選択であることを検証する。
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

    assert path_to_edge_ids_sparse(sparse_graph, ["a", "b"]) == ["second"]  # cost最小
    assert sparse_graph.matrix[sparse_graph.node_id_to_index["a"], sparse_graph.node_id_to_index["b"]] == 5.0


def test_build_sparse_graph_parallel_edge_selection_is_order_independent():
    # 改善計画T363の回帰テスト本体: 登場順が「先」の方がcost最小であっても、
    # 辞書の挿入順（＝呼び出しごとに変わりうるDB行順序の代理）に関わらず必ず
    # cost最小のEdgeが選ばれることを検証する（前テストとは登場順とcost最小の
    # 対応関係を逆にしてある）。
    graph = RoadGraph(
        graph_version="v1",
        nodes={"a": _node("a", 35.7, 139.7), "b": _node("b", 35.7, 139.7)},
        edges={
            "cheap_first": _edge("cheap_first", "a", "b", distance_m=50.0),
            "expensive_second": _edge("expensive_second", "a", "b", distance_m=200.0),
        },
    )
    edge_costs = {
        "cheap_first": _cost("cheap_first", cost=5.0),
        "expensive_second": _cost("expensive_second", cost=999.0),
    }
    sparse_graph = build_sparse_graph(graph, edge_costs)

    assert path_to_edge_ids_sparse(sparse_graph, ["a", "b"]) == ["cheap_first"]
    assert sparse_graph.matrix[sparse_graph.node_id_to_index["a"], sparse_graph.node_id_to_index["b"]] == 5.0


def test_concat_node_paths_removes_duplicate_boundary_nodes():
    result = concat_node_paths([["a", "b", "c"], ["c", "d"], ["d", "e", "f"]])

    assert result == ["a", "b", "c", "d", "e", "f"]


def test_concat_node_paths_handles_empty_input():
    assert concat_node_paths([]) == []


# --- 改善計画T529: rustworkxベースのlazy評価版（shortest_path_node_ids_sparseの置き換え） ---


def _cost_fn_from_dict(edge_costs: dict[str, float]) -> Callable[[str], float]:
    """テスト用のedge_cost_fn。`math.inf`は「Hard Constraintで除外」を表す
    （`shortest_path_node_ids_lazy`のdocstring参照）。"""

    def _cost_fn(edge_id: str) -> float:
        return edge_costs.get(edge_id, math.inf)

    return _cost_fn


def _zero_estimate_fn(_node_id: str) -> float:
    """常に0を返すヒューリスティック（admissibleの下限）。A*をDijkstraと同じ挙動へ
    単純化し、経路選択そのものの正しさだけを検証する。"""
    return 0.0


def test_build_lazy_road_graph_keeps_edge_id_ascending_for_parallel_edges():
    # 改善計画T529: lazy評価はコストを事前計算しないため、build_sparse_graphと異なり
    # 「cost最小のEdgeを採用」はできない。edge_idの昇順で先頭を採用する決定的な
    # 選択になることを確認する（並行Edgeの回帰観点、docstring参照）。
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
    cost_fn = _cost_fn_from_dict({"direct": 1000.0, "via_b": 10.0, "via_c": 10.0})

    path = shortest_path_node_ids_lazy(lazy_graph, "a", "d", cost_fn, _zero_estimate_fn)

    assert path == ["a", "b", "d"]


def test_shortest_path_node_ids_lazy_returns_none_when_unreachable():
    graph = RoadGraph(
        graph_version="v1",
        nodes={"a": _node("a", 35.7, 139.7), "b": _node("b", 35.7, 139.7)},
        edges={},
    )
    lazy_graph = build_lazy_road_graph(graph)

    assert shortest_path_node_ids_lazy(lazy_graph, "a", "b", _cost_fn_from_dict({}), _zero_estimate_fn) is None


def test_shortest_path_node_ids_lazy_same_start_and_end_returns_single_node():
    graph = RoadGraph(graph_version="v1", nodes={"a": _node("a", 35.7, 139.7)}, edges={})
    lazy_graph = build_lazy_road_graph(graph)

    assert shortest_path_node_ids_lazy(lazy_graph, "a", "a", _cost_fn_from_dict({}), _zero_estimate_fn) == ["a"]


def test_shortest_path_node_ids_lazy_excludes_disallowed_edges():
    # 改善計画T529: LazyRoadGraphはHard Constraintを知らずトポロジ全体を含むため、
    # edge_cost_fnがmath.infを返すことで「除外」を表現する（build_sparse_graphが
    # グラフ構築時にEdge自体を除外するのと異なる仕組み）。
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
    cost_fn = _cost_fn_from_dict({"e1": 100.0})  # e2/e3は辞書に無い＝math.inf

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
    cost_fn = _cost_fn_from_dict({"e1": 10.0, "e2": 10.0})
    estimate_calls: list[str] = []

    def _tracking_estimate_fn(node_id: str) -> float:
        estimate_calls.append(node_id)
        return 0.0

    path = shortest_path_node_ids_lazy(lazy_graph, "a", "c", cost_fn, _tracking_estimate_fn)

    assert path == ["a", "b", "c"]
    assert len(estimate_calls) > 0


def test_lazy_and_sparse_engines_agree_on_shortest_path_for_same_costs():
    # 改善計画T529: 新旧エンジン（rustworkxのlazy評価 vs scipyの事前一括評価）が、
    # 同一のEdgeコストに対して同じ最短経路を返すことを確認する回帰テスト
    # （新旧一致確認、docs/tasks/T529.md参照）。並行Edgeを含まないグラフで比較する
    # （並行Edge選択の仕組み自体は異なる設計のため対象外、上記の専用テスト参照）。
    graph = RoadGraph(
        graph_version="v1",
        nodes={n: _node(n, 35.7, 139.7) for n in ["a", "b", "c", "d", "e"]},
        edges={
            "a_b": _edge("a_b", "a", "b", distance_m=10.0),
            "b_d": _edge("b_d", "b", "d", distance_m=10.0),
            "a_c": _edge("a_c", "a", "c", distance_m=5.0),
            "c_d": _edge("c_d", "c", "d", distance_m=5.0),
            "d_e": _edge("d_e", "d", "e", distance_m=1.0),
        },
    )
    costs_by_edge_id = {"a_b": 100.0, "b_d": 100.0, "a_c": 10.0, "c_d": 10.0, "d_e": 1.0}

    sparse_graph = build_sparse_graph(
        graph, {eid: _cost(eid, cost=cost) for eid, cost in costs_by_edge_id.items()}
    )
    lazy_graph = build_lazy_road_graph(graph)
    cost_fn = _cost_fn_from_dict(costs_by_edge_id)

    for start, end in [("a", "e"), ("a", "d"), ("b", "d")]:
        sparse_path = shortest_path_node_ids_sparse(sparse_graph, start, end)
        lazy_path = shortest_path_node_ids_lazy(lazy_graph, start, end, cost_fn, _zero_estimate_fn)
        assert sparse_path == lazy_path
