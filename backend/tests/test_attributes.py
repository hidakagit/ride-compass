from app.domain.attributes import compute_elevation_attribute, surface_by_edge_id
from app.domain.graph import DirectedEdge, Node, RoadGraph
from app.domain.route import Coordinates

P1 = Coordinates(latitude=35.700, longitude=139.700)
P2 = Coordinates(latitude=35.701, longitude=139.700)
P3 = Coordinates(latitude=35.702, longitude=139.700)
P4 = Coordinates(latitude=35.703, longitude=139.700)


def test_compute_elevation_attribute_uphill():
    attr = compute_elevation_attribute("edge-1", [P1, P2, P3], [10.0, 20.0, 40.0], data_source="test")

    assert attr.edge_id == "edge-1"
    assert attr.start_elevation_m == 10.0
    assert attr.end_elevation_m == 40.0
    assert attr.elevation_gain_m == 30.0
    assert attr.elevation_loss_m == 0.0
    assert attr.max_grade is not None and attr.max_grade > 0
    assert attr.min_grade is not None and attr.min_grade > 0
    assert attr.average_grade is not None and attr.average_grade > 0
    assert attr.data_source == "test"
    assert attr.calculated_at


def test_compute_elevation_attribute_downhill_has_loss_and_negative_grade():
    attr = compute_elevation_attribute("edge-1", [P1, P2, P3], [40.0, 20.0, 10.0], data_source="test")

    assert attr.elevation_gain_m == 0.0
    assert attr.elevation_loss_m == 30.0
    assert attr.max_grade is not None and attr.max_grade < 0
    assert attr.min_grade is not None and attr.min_grade < 0
    assert attr.average_grade is not None and attr.average_grade < 0


def test_compute_elevation_attribute_mixed_gain_and_loss():
    attr = compute_elevation_attribute("edge-1", [P1, P2, P3], [10.0, 30.0, 15.0], data_source="test")

    assert attr.elevation_gain_m == 20.0
    assert attr.elevation_loss_m == 15.0
    assert attr.max_grade is not None and attr.max_grade > 0  # 登り区間
    assert attr.min_grade is not None and attr.min_grade < 0  # 下り区間


def test_compute_elevation_attribute_ignores_none_values():
    attr = compute_elevation_attribute("edge-1", [P1, P2, P3], [10.0, None, 20.0], data_source="test")

    # 改善計画T463: P1(10.0)→P3(20.0)は元の点列で隣接していない（間のP2が欠損）ため、
    # start/end_elevationはvalid点から算出するが、gain/loss/gradeへは寄与しない
    # （欠損区間の実際の起伏を「一律10m上昇」と均してしまうバグの回帰テスト）。
    assert attr.start_elevation_m == 10.0
    assert attr.end_elevation_m == 20.0
    assert attr.elevation_gain_m == 0.0
    assert attr.elevation_loss_m == 0.0
    assert attr.max_grade is None
    assert attr.min_grade is None
    # average_gradeは開始・終了標高とtotal_distance_mから算出するため、欠損の有無に
    # 関わらず引き続き算出される（gain/loss/gradeとは独立した扱い）。
    assert attr.average_grade is not None and attr.average_grade > 0


def test_compute_elevation_attribute_only_counts_truly_adjacent_pairs_for_gain():
    # P1(10)→P2(20)は元の点列で隣接（gain 10に寄与）。P2(20)→P4(30)は間のP3が欠損して
    # おり隣接していないためgainに寄与しない。合計gainは20ではなく10になるはず
    # （改善計画T463の回帰テスト）。
    attr = compute_elevation_attribute("edge-1", [P1, P2, P3, P4], [10.0, 20.0, None, 30.0], data_source="test")

    assert attr.start_elevation_m == 10.0
    assert attr.end_elevation_m == 30.0
    assert attr.elevation_gain_m == 10.0
    assert attr.elevation_loss_m == 0.0
    # max/min_gradeはP1→P2ペアのみから算出される（P2→P4は欠損を挟むため寄与しない）。
    assert attr.max_grade is not None and attr.max_grade > 0
    assert attr.min_grade is not None and attr.min_grade > 0


def test_compute_elevation_attribute_returns_all_none_when_fewer_than_two_valid_points():
    attr = compute_elevation_attribute("edge-1", [P1, P2], [10.0, None], data_source="test")

    assert attr.edge_id == "edge-1"
    assert attr.start_elevation_m is None
    assert attr.elevation_gain_m is None
    assert attr.average_grade is None
    assert attr.data_source == "test"
    assert attr.calculated_at


def _make_graph(edges: dict[str, DirectedEdge]) -> RoadGraph:
    node = Node(node_id="node-1", latitude=35.7, longitude=139.7)
    return RoadGraph(graph_version="v1", nodes={"node-1": node}, edges=edges)


def test_surface_by_edge_id_maps_by_osm_way_id():
    edge = DirectedEdge(
        edge_id="edge-1",
        from_node_id="node-1",
        to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]],
        distance_m=100.0,
        osm_way_id=100,
    )
    graph = _make_graph({"edge-1": edge})

    surfaces = surface_by_edge_id(graph, surface_by_way_id={100: "asphalt"})

    assert surfaces["edge-1"] == "asphalt"


def test_surface_by_edge_id_unknown_way_id_is_none():
    edge = DirectedEdge(
        edge_id="edge-1",
        from_node_id="node-1",
        to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]],
        distance_m=100.0,
        osm_way_id=999,
    )
    graph = _make_graph({"edge-1": edge})

    surfaces = surface_by_edge_id(graph, surface_by_way_id={100: "asphalt"})

    assert surfaces["edge-1"] is None


def test_surface_by_edge_id_edge_without_osm_way_id_is_none():
    edge = DirectedEdge(
        edge_id="edge-1",
        from_node_id="node-1",
        to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]],
        distance_m=100.0,
        osm_way_id=None,
    )
    graph = _make_graph({"edge-1": edge})

    surfaces = surface_by_edge_id(graph, surface_by_way_id={100: "asphalt"})

    assert surfaces["edge-1"] is None
