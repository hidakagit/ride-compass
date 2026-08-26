from app.domain.attributes import ElevationAttribute
from app.domain.axis_definitions import default_axis_weights
from app.domain.graph import DirectedEdge, Node, RoadGraph
from app.services.evaluation_service import EvaluationService, load_route_preference

# 改善計画T350: 本番相当の14軸（実軸id前提のロジック用）はtests/conftest.pyのセッション
# スコープautouseフィクスチャが全テスト共通で用意する（tests/realistic_axis_fixtures.py参照）。


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

    service = EvaluationService(load_route_preference())
    results = service.evaluate_graph(graph, elevation_attributes, surface_attributes, load_route_preference())

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

    service = EvaluationService(load_route_preference())
    results = service.evaluate_graph(
        graph, elevation_attributes={}, surface_attributes={}, preference=load_route_preference()
    )

    assert results["edge-1"].allowed is True
    assert results["edge-1"].difficulty is None
    assert results["edge-1"].cost == 50.0


def test_evaluate_graph_empty_graph_returns_empty_dict():
    graph = RoadGraph(graph_version="v1", nodes={}, edges={})

    service = EvaluationService(load_route_preference())
    results = service.evaluate_graph(graph, {}, {}, load_route_preference())

    assert results == {}


def test_evaluate_graph_passes_stop_counts_to_compute_edge_cost():
    edge = DirectedEdge(
        edge_id="edge-1", from_node_id="node-1", to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]], distance_m=1000.0,
    )
    graph = _make_graph(edge)
    elevation_attributes = {"edge-1": ElevationAttribute(edge_id="edge-1", average_grade=0.0, data_source="t", calculated_at="t")}
    surface_attributes = {"edge-1": "asphalt"}

    service = EvaluationService(load_route_preference())
    no_stops = service.evaluate_graph(graph, elevation_attributes, surface_attributes, load_route_preference())["edge-1"]
    many_stops = service.evaluate_graph(
        graph, elevation_attributes, surface_attributes, load_route_preference(), stop_counts={"edge-1": 4}
    )["edge-1"]

    assert many_stops.difficulty > no_stops.difficulty


def test_evaluate_graph_missing_stop_counts_entry_is_none():
    edge = DirectedEdge(
        edge_id="edge-1", from_node_id="node-1", to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]], distance_m=50.0,
    )
    graph = _make_graph(edge)

    service = EvaluationService(load_route_preference())
    results = service.evaluate_graph(graph, {}, {}, load_route_preference(), stop_counts={})

    assert results["edge-1"].difficulty is None


def test_evaluate_graph_passes_accident_counts_to_compute_edge_cost():
    edge = DirectedEdge(
        edge_id="edge-1", from_node_id="node-1", to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]], distance_m=1000.0,
    )
    graph = _make_graph(edge)
    elevation_attributes = {"edge-1": ElevationAttribute(edge_id="edge-1", average_grade=0.0, data_source="t", calculated_at="t")}
    surface_attributes = {"edge-1": "asphalt"}

    service = EvaluationService(load_route_preference())
    no_accidents = service.evaluate_graph(
        graph, elevation_attributes, surface_attributes, load_route_preference()
    )["edge-1"]
    many_accidents = service.evaluate_graph(
        graph, elevation_attributes, surface_attributes, load_route_preference(),
        accident_counts={"edge-1": 10}, accident_years_covered=3,
    )["edge-1"]

    assert many_accidents.difficulty > no_accidents.difficulty


def test_evaluate_graph_missing_accident_counts_entry_is_none():
    edge = DirectedEdge(
        edge_id="edge-1", from_node_id="node-1", to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]], distance_m=50.0,
    )
    graph = _make_graph(edge)

    service = EvaluationService(load_route_preference())
    results = service.evaluate_graph(
        graph, {}, {}, load_route_preference(), accident_counts={}, accident_years_covered=3
    )

    assert results["edge-1"].difficulty is None


def test_evaluate_graph_uses_custom_route_preference():
    # デッドコード監査（改善計画）でEvaluationService.__init__/evaluate_graphの
    # `preference or ...`フォールバックを削除した（唯一の呼び出し元RoadGraphEngineは
    # 必ず明示的にpreferenceを渡すため到達不能だった）。preferenceは今はevaluate_graph
    # 呼び出しごとに明示するのが実際の使われ方のため、テストもそれに合わせる
    # （コンストラクタへ渡すpreferenceは、evaluate_graphが必ず引数で上書きされるため
    # 現状は使われないが、__init__のシグネチャ上必須のためload_route_preference()を渡す）。
    from app.domain.evaluation import RoutePreference

    edge = DirectedEdge(
        edge_id="edge-1", from_node_id="node-1", to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]], distance_m=100.0,
    )
    graph = _make_graph(edge)
    elevation_attributes = {"edge-1": ElevationAttribute(edge_id="edge-1", average_grade=10.0, data_source="t", calculated_at="t")}
    surface_attributes = {"edge-1": "asphalt"}

    service = EvaluationService(load_route_preference())
    default_preference = load_route_preference()
    elevation_only_preference = RoutePreference(weights={"gradient": 1.0, "surface_q": 0.0})

    default_result = service.evaluate_graph(graph, elevation_attributes, surface_attributes, default_preference)["edge-1"]
    elevation_only_result = service.evaluate_graph(
        graph, elevation_attributes, surface_attributes, elevation_only_preference
    )["edge-1"]

    # 舗装路のroad_difficulty(0)を無視する分、勾配のみ考慮する方が難易度が高くなる
    assert elevation_only_result.difficulty > default_result.difficulty


def test_load_route_preference_matches_axis_definitions_defaults():
    # 改善計画T316回帰テスト: 以前はroute_preference.yaml（axis_id 7件固定の手書き
    # ミラー）から読んでいたため、軸スタジオで公開軸の集合が変わるとバリデーション
    # エラーで500になる実障害があった。既定値は常にAXIS_DEFINITIONS（軸スタジオが
    # 唯一の情報源）由来になり、公開軸の増減に自動追従することを確認する。
    preference = load_route_preference()

    assert preference.weights == default_axis_weights()


def test_evaluation_service_config_file_defaults_match_explicit_matching_weights():
    # 改称: 以前は`EvaluationService()`/`evaluate_graph()`の両方でpreference省略時に
    # load_route_preference()へフォールバックする挙動を検証していたが、デッドコード監査で
    # そのフォールバックを削除した（唯一の呼び出し元RoadGraphEngineは必ずpreferenceを
    # 明示的に渡すため到達不能だった）。本テストの本来の意図（load_route_preference()の
    # 重みが、公開軸の既定weightsを手で書き下したRoutePreferenceと一致すること）自体は
    # 両者にload_route_preference()/明示的な重みをそれぞれ渡して維持する。
    edge = DirectedEdge(
        edge_id="edge-1", from_node_id="node-1", to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]], distance_m=100.0,
    )
    graph = _make_graph(edge)
    elevation_attributes = {"edge-1": ElevationAttribute(edge_id="edge-1", average_grade=6.0, data_source="t", calculated_at="t")}
    surface_attributes = {"edge-1": "gravel"}

    from app.domain.evaluation import RoutePreference

    default_preference = load_route_preference()
    explicit_matching_preference = RoutePreference(
        weights={"gradient": 0.15, "surface_q": 0.19, "wind": 0.26, "stop_density": 0.20, "car_stress": 0.20}
    )

    default_via_config = EvaluationService(default_preference).evaluate_graph(
        graph, elevation_attributes, surface_attributes, default_preference
    )["edge-1"]
    explicit_matching_weights = EvaluationService(explicit_matching_preference).evaluate_graph(
        graph, elevation_attributes, surface_attributes, explicit_matching_preference
    )["edge-1"]

    assert default_via_config.difficulty == explicit_matching_weights.difficulty
