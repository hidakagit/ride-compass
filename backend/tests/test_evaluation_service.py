from app.domain.attributes import ElevationAttribute, SurfaceAttribute
from app.domain.graph import DirectedEdge, Node, RoadGraph
from app.services.evaluation_service import EvaluationService, load_route_preference


def _make_graph(*edges: DirectedEdge) -> RoadGraph:
    node = Node(node_id="node-1", latitude=35.7, longitude=139.7)
    return RoadGraph(graph_version="v1", nodes={"node-1": node}, edges={e.edge_id: e for e in edges})


def test_evaluate_graph_returns_result_per_edge():
    edge1 = DirectedEdge(
        edge_id="edge-1", from_node_id="node-1", to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]], distance_m=100.0, highway="residential",
    )
    edge2 = DirectedEdge(
        edge_id="edge-2", from_node_id="node-1", to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]], distance_m=200.0, highway="motorway",
    )
    graph = _make_graph(edge1, edge2)
    elevation_attributes = {"edge-1": ElevationAttribute(edge_id="edge-1", average_grade=2.0, data_source="t", calculated_at="t")}
    surface_attributes = {"edge-1": SurfaceAttribute(edge_id="edge-1", surface_type="asphalt", data_source="t", calculated_at="t")}

    service = EvaluationService()
    results = service.evaluate_graph(graph, elevation_attributes, surface_attributes)

    assert set(results.keys()) == {"edge-1", "edge-2"}
    assert results["edge-1"].allowed is True
    assert results["edge-1"].cost is not None
    assert results["edge-2"].allowed is False  # motorwayはHard Constraintで除外
    assert results["edge-2"].cost is None


def test_evaluate_graph_missing_attribute_entries_are_treated_as_none():
    edge = DirectedEdge(
        edge_id="edge-1", from_node_id="node-1", to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]], distance_m=50.0,
    )
    graph = _make_graph(edge)

    service = EvaluationService()
    results = service.evaluate_graph(graph, elevation_attributes={}, surface_attributes={})

    assert results["edge-1"].allowed is True
    assert results["edge-1"].difficulty is None
    assert results["edge-1"].cost == 50.0


def test_evaluate_graph_empty_graph_returns_empty_dict():
    graph = RoadGraph(graph_version="v1", nodes={}, edges={})

    service = EvaluationService()
    results = service.evaluate_graph(graph, {}, {})

    assert results == {}


def test_evaluate_graph_uses_custom_route_preference():
    from app.domain.evaluation import RoutePreference

    edge = DirectedEdge(
        edge_id="edge-1", from_node_id="node-1", to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]], distance_m=100.0,
    )
    graph = _make_graph(edge)
    elevation_attributes = {"edge-1": ElevationAttribute(edge_id="edge-1", average_grade=10.0, data_source="t", calculated_at="t")}
    surface_attributes = {"edge-1": SurfaceAttribute(edge_id="edge-1", surface_type="asphalt", data_source="t", calculated_at="t")}

    default_service = EvaluationService()
    elevation_only_service = EvaluationService(RoutePreference(elevation_weight=1.0, road_weight=0.0))

    default_result = default_service.evaluate_graph(graph, elevation_attributes, surface_attributes)["edge-1"]
    elevation_only_result = elevation_only_service.evaluate_graph(graph, elevation_attributes, surface_attributes)["edge-1"]

    # 舗装路のroad_difficulty(0)を無視する分、勾配のみ考慮する方が難易度が高くなる
    assert elevation_only_result.difficulty > default_result.difficulty


def test_load_route_preference_reads_default_config_file():
    preference = load_route_preference()

    assert preference.elevation_weight == 0.25
    assert preference.road_weight == 0.30
    assert preference.wind_weight == 0.45


def test_load_route_preference_reads_custom_path(tmp_path):
    config_path = tmp_path / "custom_route_preference.yaml"
    config_path.write_text(
        "route_preference:\n  elevation_weight: 0.8\n  road_weight: 0.2\n",
        encoding="utf-8",
    )

    preference = load_route_preference(config_path)

    assert preference.elevation_weight == 0.8
    assert preference.road_weight == 0.2


def test_evaluation_service_without_explicit_preference_uses_config_file_defaults():
    edge = DirectedEdge(
        edge_id="edge-1", from_node_id="node-1", to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]], distance_m=100.0,
    )
    graph = _make_graph(edge)
    elevation_attributes = {"edge-1": ElevationAttribute(edge_id="edge-1", average_grade=6.0, data_source="t", calculated_at="t")}
    surface_attributes = {"edge-1": SurfaceAttribute(edge_id="edge-1", surface_type="gravel", data_source="t", calculated_at="t")}

    from app.domain.evaluation import RoutePreference

    default_via_config = EvaluationService().evaluate_graph(graph, elevation_attributes, surface_attributes)["edge-1"]
    explicit_matching_weights = EvaluationService(
        RoutePreference(elevation_weight=0.25, road_weight=0.30, wind_weight=0.45)
    ).evaluate_graph(graph, elevation_attributes, surface_attributes)["edge-1"]

    assert default_via_config.difficulty == explicit_matching_weights.difficulty
