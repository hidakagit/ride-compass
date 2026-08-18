from app.domain.attributes import ElevationAttribute
from app.domain.graph import DirectedEdge, Node, RoadGraph
from app.services.evaluation_service import (
    EvaluationService,
    load_motor_vehicle_density_recipe,
    load_road_suitability_recipe,
    load_route_preference,
    load_safety_recipe,
    load_traffic_stress_recipe,
)


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
    surface_attributes = {"edge-1": "asphalt"}

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


def test_evaluate_graph_passes_stop_counts_to_compute_edge_cost():
    edge = DirectedEdge(
        edge_id="edge-1", from_node_id="node-1", to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]], distance_m=1000.0,
    )
    graph = _make_graph(edge)
    elevation_attributes = {"edge-1": ElevationAttribute(edge_id="edge-1", average_grade=0.0, data_source="t", calculated_at="t")}
    surface_attributes = {"edge-1": "asphalt"}

    service = EvaluationService()
    no_stops = service.evaluate_graph(graph, elevation_attributes, surface_attributes)["edge-1"]
    many_stops = service.evaluate_graph(
        graph, elevation_attributes, surface_attributes, stop_counts={"edge-1": 4}
    )["edge-1"]

    assert many_stops.difficulty > no_stops.difficulty


def test_evaluate_graph_missing_stop_counts_entry_is_none():
    edge = DirectedEdge(
        edge_id="edge-1", from_node_id="node-1", to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]], distance_m=50.0,
    )
    graph = _make_graph(edge)

    service = EvaluationService()
    results = service.evaluate_graph(graph, {}, {}, stop_counts={})

    assert results["edge-1"].difficulty is None


def test_evaluate_graph_passes_accident_counts_to_compute_edge_cost():
    edge = DirectedEdge(
        edge_id="edge-1", from_node_id="node-1", to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]], distance_m=1000.0,
    )
    graph = _make_graph(edge)
    elevation_attributes = {"edge-1": ElevationAttribute(edge_id="edge-1", average_grade=0.0, data_source="t", calculated_at="t")}
    surface_attributes = {"edge-1": "asphalt"}

    service = EvaluationService()
    no_accidents = service.evaluate_graph(graph, elevation_attributes, surface_attributes)["edge-1"]
    many_accidents = service.evaluate_graph(
        graph, elevation_attributes, surface_attributes, accident_counts={"edge-1": 10}, accident_years_covered=3,
    )["edge-1"]

    assert many_accidents.difficulty > no_accidents.difficulty


def test_evaluate_graph_missing_accident_counts_entry_is_none():
    edge = DirectedEdge(
        edge_id="edge-1", from_node_id="node-1", to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]], distance_m=50.0,
    )
    graph = _make_graph(edge)

    service = EvaluationService()
    results = service.evaluate_graph(graph, {}, {}, accident_counts={}, accident_years_covered=3)

    assert results["edge-1"].difficulty is None


def test_evaluate_graph_uses_custom_route_preference():
    from app.domain.evaluation import RoutePreference

    edge = DirectedEdge(
        edge_id="edge-1", from_node_id="node-1", to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]], distance_m=100.0,
    )
    graph = _make_graph(edge)
    elevation_attributes = {"edge-1": ElevationAttribute(edge_id="edge-1", average_grade=10.0, data_source="t", calculated_at="t")}
    surface_attributes = {"edge-1": "asphalt"}

    default_service = EvaluationService()
    elevation_only_service = EvaluationService(RoutePreference(elevation_weight=1.0, road_weight=0.0))

    default_result = default_service.evaluate_graph(graph, elevation_attributes, surface_attributes)["edge-1"]
    elevation_only_result = elevation_only_service.evaluate_graph(graph, elevation_attributes, surface_attributes)["edge-1"]

    # 舗装路のroad_difficulty(0)を無視する分、勾配のみ考慮する方が難易度が高くなる
    assert elevation_only_result.difficulty > default_result.difficulty


def test_load_route_preference_reads_default_config_file():
    preference = load_route_preference()

    assert preference.elevation_weight == 0.15
    assert preference.road_weight == 0.19
    assert preference.wind_weight == 0.26
    assert preference.stop_weight == 0.15
    assert preference.traffic_weight == 0.10
    assert preference.infra_weight == 0.10
    assert preference.intersection_weight == 0.05
    assert preference.accident_weight == 0.08
    assert preference.safety_weight == 0.10


def test_load_route_preference_reads_custom_path(tmp_path):
    config_path = tmp_path / "custom_route_preference.yaml"
    config_path.write_text(
        "route_preference:\n  elevation_weight: 0.8\n  road_weight: 0.2\n",
        encoding="utf-8",
    )

    preference = load_route_preference(config_path)

    assert preference.elevation_weight == 0.8
    assert preference.road_weight == 0.2


def test_load_traffic_stress_recipe_reads_default_config_file():
    # load_route_preference/route_preference.yamlと同じ運用（domain/traffic.py:
    # TrafficStressRecipeのクラス既定値とtraffic_stress_recipe.yamlの2箇所が値を持つため、
    # 値をハードコード検証して手動同期のドリフトを検知する）。
    recipe = load_traffic_stress_recipe()

    assert recipe.lanes_low_threshold == 1
    assert recipe.lanes_low_adjustment == -1


def test_load_traffic_stress_recipe_reads_custom_path(tmp_path):
    config_path = tmp_path / "custom_traffic_stress_recipe.yaml"
    config_path.write_text(
        "traffic_stress_recipe:\n  lanes_low_threshold: 2\n  lanes_low_adjustment: -3\n",
        encoding="utf-8",
    )

    recipe = load_traffic_stress_recipe(config_path)

    assert recipe.lanes_low_threshold == 2
    assert recipe.lanes_low_adjustment == -3


def test_load_safety_recipe_reads_default_config_file():
    # load_traffic_stress_recipe/traffic_stress_recipe.yamlと同じ運用（domain/safety.py:
    # SafetyRecipeのクラス既定値とsafety_recipe.yamlの2箇所が値を持つため、値をハードコード
    # 検証して手動同期のドリフトを検知する）。
    recipe = load_safety_recipe()

    assert recipe.lit_adjustment == -1
    assert recipe.tunnel_adjustment == 1


def test_load_safety_recipe_reads_custom_path(tmp_path):
    config_path = tmp_path / "custom_safety_recipe.yaml"
    config_path.write_text(
        "safety_recipe:\n  lit_adjustment: -2\n  tunnel_adjustment: 2\n",
        encoding="utf-8",
    )

    recipe = load_safety_recipe(config_path)

    assert recipe.lit_adjustment == -2
    assert recipe.tunnel_adjustment == 2


def test_load_road_suitability_recipe_reads_default_config_file():
    # load_traffic_stress_recipeと同じ運用（domain/recipe.py: RoadSuitabilityRecipeの
    # クラス既定値とroad_suitability_recipe.yamlの2箇所が値を持つため、値をハードコード
    # 検証して手動同期のドリフトを検知する。改善計画: 車との近さ材料の共有元化）。
    recipe = load_road_suitability_recipe()

    assert recipe.base_by_highway == {
        "cycleway": 1,
        "living_street": 1,
        "residential": 2,
        "unclassified": 2,
        "track": 2,
        "tertiary": 3,
        "tertiary_link": 3,
        "secondary": 3,
        "secondary_link": 3,
        "primary": 4,
        "primary_link": 4,
        "trunk": 4,
        "trunk_link": 4,
    }
    assert recipe.cycleway_track_adjustment == -2
    assert recipe.cycleway_lane_adjustment == -1
    assert recipe.cycleway_shared_adjustment == -1


def test_load_road_suitability_recipe_reads_custom_path(tmp_path):
    config_path = tmp_path / "custom_road_suitability_recipe.yaml"
    config_path.write_text(
        "road_suitability_recipe:\n"
        "  base_by_highway: {secondary: 2}\n"
        "  cycleway_track_adjustment: -3\n"
        "  cycleway_lane_adjustment: -1\n"
        "  cycleway_shared_adjustment: -1\n",
        encoding="utf-8",
    )

    recipe = load_road_suitability_recipe(config_path)

    assert recipe.base_by_highway == {"secondary": 2}
    assert recipe.cycleway_track_adjustment == -3


def test_load_motor_vehicle_density_recipe_reads_default_config_file():
    recipe = load_motor_vehicle_density_recipe()

    assert recipe.maxspeed_low_threshold == 30
    assert recipe.maxspeed_low_adjustment == -1
    assert recipe.maxspeed_high_threshold == 60
    assert recipe.maxspeed_high_adjustment == 1
    assert recipe.lanes_high_threshold == 4
    assert recipe.lanes_high_adjustment == 1
    assert recipe.designation_adjustment == 1


def test_load_motor_vehicle_density_recipe_reads_custom_path(tmp_path):
    config_path = tmp_path / "custom_motor_vehicle_density_recipe.yaml"
    config_path.write_text(
        "motor_vehicle_density_recipe:\n"
        "  maxspeed_low_threshold: 20\n"
        "  maxspeed_low_adjustment: -2\n"
        "  maxspeed_high_threshold: 70\n"
        "  maxspeed_high_adjustment: 2\n"
        "  lanes_high_threshold: 5\n"
        "  lanes_high_adjustment: 2\n"
        "  designation_adjustment: 2\n",
        encoding="utf-8",
    )

    recipe = load_motor_vehicle_density_recipe(config_path)

    assert recipe.maxspeed_low_threshold == 20
    assert recipe.designation_adjustment == 2


def test_evaluation_service_without_explicit_preference_uses_config_file_defaults():
    edge = DirectedEdge(
        edge_id="edge-1", from_node_id="node-1", to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]], distance_m=100.0,
    )
    graph = _make_graph(edge)
    elevation_attributes = {"edge-1": ElevationAttribute(edge_id="edge-1", average_grade=6.0, data_source="t", calculated_at="t")}
    surface_attributes = {"edge-1": "gravel"}

    from app.domain.evaluation import RoutePreference

    default_via_config = EvaluationService().evaluate_graph(graph, elevation_attributes, surface_attributes)["edge-1"]
    explicit_matching_weights = EvaluationService(
        RoutePreference(
            elevation_weight=0.15, road_weight=0.19, wind_weight=0.26, stop_weight=0.15,
            traffic_weight=0.10, infra_weight=0.10, intersection_weight=0.05,
        )
    ).evaluate_graph(graph, elevation_attributes, surface_attributes)["edge-1"]

    assert default_via_config.difficulty == explicit_matching_weights.difficulty
