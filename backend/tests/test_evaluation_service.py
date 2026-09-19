from app.domain.axis_definitions import default_axis_weights
from app.domain.graph import DirectedEdge, Node, RoadGraph
from app.domain.route_preference import RoutePreference
from app.services.evaluation_service import load_route_preference
from tests.live_evaluation import edge_costs
from tests.material_arrays import material_arrays

# 改善計画T350: 本番相当の軸（実軸id前提のロジック用）はtests/conftest.pyのセッション
# スコープautouseフィクスチャが全テスト共通で用意する（tests/realistic_axis_fixtures.py参照）。


def _make_graph(*edges: DirectedEdge) -> RoadGraph:
    node = Node(node_id="node-1", latitude=35.7, longitude=139.7)
    return RoadGraph(graph_version="v1", nodes={"node-1": node}, edges={e.edge_id: e for e in edges})


def _edge(edge_id: str, distance_m: float, highway: str | None = None) -> DirectedEdge:
    return DirectedEdge(
        edge_id=edge_id, from_node_id="node-1", to_node_id="node-1",
        geometry=[[35.7, 139.7], [35.701, 139.701]], distance_m=distance_m, highway=highway,
    )


def _costs(graph, materials, preference=None):
    return edge_costs(
        graph,
        material_arrays(graph, list(graph.edges), materials),
        preference if preference is not None else load_route_preference(),
    )


def test_returns_result_per_edge():
    graph = _make_graph(_edge("edge-1", 100.0, "residential"), _edge("edge-2", 200.0, "motorway"))

    results = _costs(graph, {"edge-1": {"gradient_percent": 2.0, "surface_good": True}})

    assert set(results.keys()) == {"edge-1", "edge-2"}
    assert results["edge-1"].allowed is True
    assert results["edge-1"].cost is not None
    assert results["edge-2"].allowed is False  # motorwayは0次フィルタで除外
    assert results["edge-2"].cost is None


def test_edge_without_any_material_has_no_difficulty():
    """材料が1つも無ければ、difficultyは求まらず割増もかからない。"""
    graph = _make_graph(_edge("edge-1", 50.0))

    results = _costs(graph, {})

    assert results["edge-1"].allowed is True
    assert results["edge-1"].difficulty is None
    assert results["edge-1"].cost == 50.0


def test_empty_graph_returns_empty_dict():
    graph = RoadGraph(graph_version="v1", nodes={}, edges={})

    assert _costs(graph, {}) == {}


def test_stop_density_materials_raise_the_difficulty():
    graph = _make_graph(_edge("edge-1", 1000.0))
    base = {"gradient_percent": 0.0, "surface_good": True}

    no_stops = _costs(graph, {"edge-1": base})["edge-1"]
    # 停止密度は停止要因POIの種別別密度で評価する。
    many_stops = _costs(graph, {"edge-1": {**base, "poi_signal_per_km": 4.0}})["edge-1"]

    assert many_stops.difficulty > no_stops.difficulty


def test_accident_material_raises_the_difficulty():
    graph = _make_graph(_edge("edge-1", 1000.0))
    base = {"gradient_percent": 0.0, "surface_good": True}

    no_accidents = _costs(graph, {"edge-1": base})["edge-1"]
    many_accidents = _costs(
        graph, {"edge-1": {**base, "accident_count_per_km_year": 10 / 3}}
    )["edge-1"]

    assert many_accidents.difficulty > no_accidents.difficulty


def test_custom_route_preference_changes_the_difficulty():
    graph = _make_graph(_edge("edge-1", 100.0))
    materials = {"edge-1": {"gradient_percent": 10.0, "surface_good": True}}

    default_result = _costs(graph, materials)["edge-1"]
    gradient_only = _costs(
        graph, materials, RoutePreference(weights={"gradient": 1.0, "surface_q": 0.0})
    )["edge-1"]

    # 舗装路のsurface_q(0)を無視する分、勾配のみ考慮する方が難易度が高くなる
    assert gradient_only.difficulty > default_result.difficulty


def test_load_route_preference_matches_axis_definitions_defaults():
    # 改善計画T316回帰テスト: 以前はroute_preference.yaml（axis_idの手書きミラー）から
    # 読んでいたため、軸スタジオで公開軸の集合が変わるとバリデーションエラーで500になる
    # 実障害があった。既定値は常にAXIS_DEFINITIONS（軸スタジオが唯一の情報源）由来になり、
    # 公開軸の増減に自動追従することを確認する。
    assert load_route_preference().weights == default_axis_weights()


def test_config_file_defaults_match_explicit_matching_weights():
    # 「load_route_preference()の重みが、公開軸の既定weightsを手で書き下した
    # RoutePreferenceと一致すること」を、評価結果の一致で確かめる。
    graph = _make_graph(_edge("edge-1", 100.0))
    materials = {"edge-1": {"gradient_percent": 6.0, "surface_good": False}}
    explicit = RoutePreference(
        weights={"gradient": 0.15, "surface_q": 0.19, "wind": 0.26, "stop_density": 0.20, "car_stress": 0.20}
    )

    via_config = _costs(graph, materials)["edge-1"]
    via_explicit = _costs(graph, materials, explicit)["edge-1"]

    assert via_config.difficulty == via_explicit.difficulty
