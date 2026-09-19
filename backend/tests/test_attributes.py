
from app.domain.attributes import (
    MAX_PLAUSIBLE_AVERAGE_GRADE_PERCENT,
    compute_elevation_attribute,
    surface_by_edge_id,
)
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


# --- EdgeMaterialTable（改善計画T546、T538再検討案C1）---



























# P1から約11m北。舗装公道としてありえない勾配を短い区間で作るために使う。
P_NEAR = Coordinates(latitude=35.7001, longitude=139.700)


def test_compute_elevation_attribute_blanks_physically_impossible_grade():
    """ありえない急勾配は値を持たせない。DEMが路面でない地物を指したときに出る。"""
    attr = compute_elevation_attribute("edge-x", [P1, P_NEAR], [2.1, 7.1], data_source="test")

    # 5.0m ÷ 約11.1m ＝ 約45%。
    assert attr.average_grade is None
    # 標高そのものは残す（値が出せないのは勾配だけ）。
    assert attr.start_elevation_m == 2.1
    assert attr.end_elevation_m == 7.1


def test_compute_elevation_attribute_keeps_steep_but_possible_grade():
    """上限の内側は急でもそのまま残す（実在する激坂を消さない）。"""
    attr = compute_elevation_attribute("edge-y", [P1, P_NEAR], [2.1, 6.0], data_source="test")

    # 3.9m ÷ 約11.1m ＝ 約35%。
    assert attr.average_grade is not None
    assert 30 < attr.average_grade < MAX_PLAUSIBLE_AVERAGE_GRADE_PERCENT


def test_compute_elevation_attribute_blanks_impossible_downhill_too():
    attr = compute_elevation_attribute("edge-z", [P1, P_NEAR], [7.1, 2.1], data_source="test")

    assert attr.average_grade is None


def test_compute_elevation_attribute_blanks_grade_on_structure():
    """橋・トンネルでは勾配を出さない。DEMは桁や坑道ではなく地表面を返すため。"""
    attr = compute_elevation_attribute(
        "edge-bridge", [P1, P2], [10.0, 22.0], data_source="test", dem_reflects_road_surface=False
    )

    assert attr.average_grade is None
    # 標高そのものは残す（消えるのは勾配だけ）。
    assert attr.start_elevation_m == 10.0
    assert attr.end_elevation_m == 22.0
    assert attr.elevation_gain_m == 12.0


def test_compute_elevation_attribute_keeps_grade_off_structure():
    attr = compute_elevation_attribute(
        "edge-ground", [P1, P2], [10.0, 22.0], data_source="test", dem_reflects_road_surface=True
    )

    assert attr.average_grade is not None
