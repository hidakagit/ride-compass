from app.domain.geo import haversine_distance_km
from app.domain.graph import WaySpec, build_road_graph
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
