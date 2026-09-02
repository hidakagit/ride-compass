import pickle

from app.domain.geo import haversine_distance_km
from app.domain.graph import LeanEdge, LeanNode, LeanRoadGraph, WaySpec, build_road_graph
from app.domain.route import Coordinates

# 単純な三角格子: A(交差点) - B(形状点のみ) - C(交差点、Way1とWay2で共有) - D
NODE_A, NODE_B, NODE_C, NODE_D, NODE_E = 1, 2, 3, 4, 5

OSM_NODES = {
    NODE_A: (35.700, 139.700),
    NODE_B: (35.701, 139.700),
    NODE_C: (35.702, 139.700),
    NODE_D: (35.702, 139.701),
    NODE_E: (35.703, 139.700),
}


def test_way_without_intersection_keeps_shape_point_inside_single_edge():
    ways = [WaySpec(osm_way_id=100, node_ids=[NODE_A, NODE_B, NODE_C], highway="residential")]

    graph = build_road_graph(ways, OSM_NODES)

    # A, Cのみが交差点(=Node)になり、Bは形状点としてgeometryの中に残る
    assert {n.osm_node_id for n in graph.nodes.values()} == {NODE_A, NODE_C}
    # 双方向（A→C, C→A）の2エッジが生成される
    assert len(graph.edges) == 2
    forward = next(e for e in graph.edges.values() if e.geometry[0] == [35.700, 139.700])
    assert forward.geometry == [[35.700, 139.700], [35.701, 139.700], [35.702, 139.700]]


def test_shared_node_between_two_ways_becomes_intersection_node():
    ways = [
        WaySpec(osm_way_id=100, node_ids=[NODE_A, NODE_C]),
        WaySpec(osm_way_id=101, node_ids=[NODE_C, NODE_D]),
        WaySpec(osm_way_id=102, node_ids=[NODE_C, NODE_E]),
    ]

    graph = build_road_graph(ways, OSM_NODES)

    # NODE_Cは3本のwayに共有されるため交差点Nodeになる
    assert {n.osm_node_id for n in graph.nodes.values()} == {NODE_A, NODE_C, NODE_D, NODE_E}
    # 各wayが分割されずそのまま1区間ずつ、双方向で計6エッジ
    assert len(graph.edges) == 6


def test_node_id_and_edge_id_are_independent_of_osm_ids():
    ways = [WaySpec(osm_way_id=999, node_ids=[NODE_A, NODE_C])]

    graph = build_road_graph(ways, OSM_NODES)

    for node_id, node in graph.nodes.items():
        assert node_id != str(node.osm_node_id)
        assert node.node_id == node_id
    for edge_id, edge in graph.edges.items():
        assert edge.osm_way_id == 999
        assert edge_id != str(edge.osm_way_id)


def test_direction_forward_creates_only_forward_edge():
    ways = [WaySpec(osm_way_id=100, node_ids=[NODE_A, NODE_C], direction="forward")]

    graph = build_road_graph(ways, OSM_NODES)

    assert len(graph.edges) == 1
    edge = next(iter(graph.edges.values()))
    from_node = graph.nodes[edge.from_node_id]
    to_node = graph.nodes[edge.to_node_id]
    assert from_node.osm_node_id == NODE_A
    assert to_node.osm_node_id == NODE_C


def test_direction_backward_creates_only_backward_edge():
    ways = [WaySpec(osm_way_id=100, node_ids=[NODE_A, NODE_C], direction="backward")]

    graph = build_road_graph(ways, OSM_NODES)

    assert len(graph.edges) == 1
    edge = next(iter(graph.edges.values()))
    from_node = graph.nodes[edge.from_node_id]
    to_node = graph.nodes[edge.to_node_id]
    assert from_node.osm_node_id == NODE_C
    assert to_node.osm_node_id == NODE_A


def test_direction_both_is_the_default():
    ways = [WaySpec(osm_way_id=100, node_ids=[NODE_A, NODE_C])]

    graph = build_road_graph(ways, OSM_NODES)

    assert len(graph.edges) == 2


def test_distance_m_matches_haversine_sum():
    ways = [WaySpec(osm_way_id=100, node_ids=[NODE_A, NODE_B, NODE_C])]

    graph = build_road_graph(ways, OSM_NODES)

    expected_km = haversine_distance_km(
        Coordinates(latitude=35.700, longitude=139.700), Coordinates(latitude=35.701, longitude=139.700)
    ) + haversine_distance_km(
        Coordinates(latitude=35.701, longitude=139.700), Coordinates(latitude=35.702, longitude=139.700)
    )
    forward = next(e for e in graph.edges.values() if e.geometry[0] == [35.700, 139.700])
    assert abs(forward.distance_m - round(expected_km * 1000, 1)) < 0.1


def test_way_with_missing_node_coordinates_is_skipped():
    ways = [WaySpec(osm_way_id=100, node_ids=[NODE_A, 9999])]

    graph = build_road_graph(ways, OSM_NODES)

    assert graph.edges == {}
    assert graph.nodes == {}


def test_way_with_fewer_than_two_nodes_is_skipped():
    ways = [WaySpec(osm_way_id=100, node_ids=[NODE_A])]

    graph = build_road_graph(ways, OSM_NODES)

    assert graph.edges == {}


def test_graph_version_is_generated_when_not_provided():
    graph = build_road_graph([], {})

    assert graph.graph_version
    assert graph.nodes == {}
    assert graph.edges == {}


def test_graph_version_can_be_overridden():
    graph = build_road_graph([], {}, graph_version="v-test-1")

    assert graph.graph_version == "v-test-1"


def test_highway_tag_is_carried_through_to_edges():
    ways = [WaySpec(osm_way_id=100, node_ids=[NODE_A, NODE_C], highway="cycleway")]

    graph = build_road_graph(ways, OSM_NODES)

    assert all(e.highway == "cycleway" for e in graph.edges.values())


def test_node_and_edge_ids_are_stable_across_repeated_builds():
    """永続化キャッシュ（PostGIS）が同一の現実の交差点・道路区間を同じ行として
    upsertできるためには、同じOSM入力から常に同じnode_id/edge_idが得られる
    （決定論的である）必要がある。"""
    ways = [
        WaySpec(osm_way_id=100, node_ids=[NODE_A, NODE_B, NODE_C]),
        WaySpec(osm_way_id=101, node_ids=[NODE_C, NODE_D]),
    ]

    graph1 = build_road_graph(ways, OSM_NODES)
    graph2 = build_road_graph(ways, OSM_NODES)

    assert set(graph1.nodes.keys()) == set(graph2.nodes.keys())
    assert set(graph1.edges.keys()) == set(graph2.edges.keys())
    # ノード単体でも、同じosm_node_idに対しては常に同じ内部node_idになる
    for edge_id, edge in graph1.edges.items():
        assert graph2.edges[edge_id].from_node_id == edge.from_node_id
        assert graph2.edges[edge_id].to_node_id == edge.to_node_id


def test_different_ways_produce_different_edge_ids_even_with_same_split_topology():
    ways = [
        WaySpec(osm_way_id=100, node_ids=[NODE_A, NODE_C]),
        WaySpec(osm_way_id=200, node_ids=[NODE_A, NODE_C]),  # 別Wayだが同じ端点間
    ]

    graph = build_road_graph(ways, OSM_NODES)

    way_ids_used = {e.osm_way_id for e in graph.edges.values()}
    assert way_ids_used == {100, 200}
    assert len(graph.edges) == 4  # 2way × 双方向


# --- 改善計画T248: 探索専用lean型（LeanNode/LeanEdge/LeanRoadGraph）の単体テスト ---


def test_lean_types_satisfy_road_graph_like_protocols():
    from app.domain.graph import (
        DirectedEdge,
        EdgeLike,
        LeanEdge,
        LeanNode,
        LeanRoadGraph,
        Node,
        NodeLike,
        RoadGraph,
        RoadGraphLike,
    )

    lean_node = LeanNode(node_id="n1", latitude=35.7, longitude=139.7, osm_node_id=1)
    lean_edge = LeanEdge(
        edge_id="e1", from_node_id="n1", to_node_id="n2", geometry=[],
        distance_m=10.0, osm_way_id=100, highway="residential", bearing_deg=90.0,
    )
    lean_graph = LeanRoadGraph(graph_version="v1", nodes={"n1": lean_node}, edges={"e1": lean_edge})

    # LeanNode/LeanEdge/LeanRoadGraphは探索フェーズが要求するProtocolを満たす。
    assert isinstance(lean_node, NodeLike)
    assert isinstance(lean_edge, EdgeLike)
    assert isinstance(lean_graph, RoadGraphLike)

    # 表示・保存用のPydantic型（Node/DirectedEdge/RoadGraph）も同じProtocolを満たす
    # （trace_loop等がlean/フル両方を同じリストへ混在させられることの前提）。
    full_node = Node(node_id="n1", latitude=35.7, longitude=139.7, osm_node_id=1)
    full_edge = DirectedEdge(
        edge_id="e1", from_node_id="n1", to_node_id="n2", geometry=[[35.7, 139.7]],
        distance_m=10.0, osm_way_id=100, highway="residential", bearing_deg=90.0,
    )
    full_graph = RoadGraph(graph_version="v1", nodes={"n1": full_node}, edges={"e1": full_edge})
    assert isinstance(full_node, NodeLike)
    assert isinstance(full_edge, EdgeLike)
    assert isinstance(full_graph, RoadGraphLike)


def test_lean_types_are_frozen():
    from app.domain.graph import LeanEdge, LeanNode

    node = LeanNode(node_id="n1", latitude=35.7, longitude=139.7)
    edge = LeanEdge(edge_id="e1", from_node_id="n1", to_node_id="n2", geometry=[], distance_m=10.0)

    # 改善計画T248: 探索フェーズ内で書き換えられるべきではないためfrozen。
    try:
        node.latitude = 0.0
        assert False, "frozen dataclassのはずが書き換えできてしまった"
    except AttributeError:
        pass
    try:
        edge.distance_m = 0.0
        assert False, "frozen dataclassのはずが書き換えできてしまった"
    except AttributeError:
        pass


# --- 改善計画T546: LeanRoadGraph.__reduce__（pickle列指向化）---


def test_lean_road_graph_pickle_roundtrip_preserves_nodes_and_edges():
    nodes = {
        "n1": LeanNode(node_id="n1", latitude=35.700, longitude=139.700, osm_node_id=1),
        "n2": LeanNode(node_id="n2", latitude=35.701, longitude=139.701, osm_node_id=None),
    }
    edges = {
        "e1": LeanEdge(
            edge_id="e1", from_node_id="n1", to_node_id="n2", geometry=[], distance_m=123.4,
            osm_way_id=10, highway="residential", bearing_deg=45.5,
        ),
        "e2": LeanEdge(
            edge_id="e2", from_node_id="n2", to_node_id="n1", geometry=[], distance_m=123.4,
            osm_way_id=None, highway=None, bearing_deg=None,
        ),
    }
    graph = LeanRoadGraph(graph_version="v1", nodes=nodes, edges=edges)

    restored = pickle.loads(pickle.dumps(graph, protocol=pickle.HIGHEST_PROTOCOL))

    assert restored.graph_version == graph.graph_version
    assert restored.nodes == graph.nodes
    assert restored.edges == graph.edges
    # geometryは常に空リストへ復元される（タイルキャッシュ経路の既存の規約、クラス
    # docstring参照）。
    assert all(e.geometry == [] for e in restored.edges.values())


def test_lean_road_graph_pickle_roundtrip_at_realistic_scale():
    """実データ規模相当のfixtureで、列（tupleリスト）分解→再構築の対応ズレが無いことを
    確認する（往復テストは実装リスクの優先度、docs/tasks/T546.md参照）。"""
    n = 20_000
    nodes = {
        f"n{i}": LeanNode(node_id=f"n{i}", latitude=35.0 + i * 1e-5, longitude=139.0, osm_node_id=i)
        for i in range(n)
    }
    edges = {
        f"e{i}": LeanEdge(
            edge_id=f"e{i}", from_node_id=f"n{i}", to_node_id=f"n{(i + 1) % n}", geometry=[],
            distance_m=float(i), osm_way_id=i if i % 3 else None, highway="residential" if i % 2 else None,
            bearing_deg=float(i % 360) if i % 7 else None,
        )
        for i in range(n)
    }
    graph = LeanRoadGraph(graph_version="v1", nodes=nodes, edges=edges)

    restored = pickle.loads(pickle.dumps(graph, protocol=pickle.HIGHEST_PROTOCOL))

    assert restored.graph_version == graph.graph_version
    assert restored.nodes == graph.nodes
    assert restored.edges == graph.edges


def test_lean_road_graph_pickle_roundtrip_handles_empty_graph():
    # 境界ケース: Edge0件・Node0件のタイル（空タイル）。
    graph = LeanRoadGraph(graph_version="v1", nodes={}, edges={})

    restored = pickle.loads(pickle.dumps(graph, protocol=pickle.HIGHEST_PROTOCOL))

    assert restored.graph_version == "v1"
    assert restored.nodes == {}
    assert restored.edges == {}
