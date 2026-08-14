from app.domain.attributes import ElevationAttribute, SurfaceAttribute
from app.domain.evaluation import RoutePreference, compute_edge_cost, is_edge_allowed
from app.domain.graph import DirectedEdge


def _edge(**overrides) -> DirectedEdge:
    defaults = dict(
        edge_id="edge-1",
        from_node_id="node-1",
        to_node_id="node-2",
        geometry=[[35.700, 139.700], [35.701, 139.700]],
        distance_m=100.0,
        osm_way_id=1,
        highway="residential",
    )
    defaults.update(overrides)
    return DirectedEdge(**defaults)


def _elevation_attr(average_grade: float | None) -> ElevationAttribute:
    return ElevationAttribute(edge_id="edge-1", average_grade=average_grade, data_source="test", calculated_at="t")


def _surface_attr(surface_type: str | None) -> SurfaceAttribute:
    return SurfaceAttribute(edge_id="edge-1", surface_type=surface_type, data_source="test", calculated_at="t")


def test_is_edge_allowed_excludes_motorway():
    assert is_edge_allowed(_edge(highway="motorway")) is False
    assert is_edge_allowed(_edge(highway="motorway_link")) is False


def test_is_edge_allowed_allows_residential():
    assert is_edge_allowed(_edge(highway="residential")) is True


def test_is_edge_allowed_allows_unknown_highway():
    assert is_edge_allowed(_edge(highway=None)) is True


def test_compute_edge_cost_excludes_disallowed_edge():
    edge = _edge(highway="motorway")
    result = compute_edge_cost(edge, None, None, RoutePreference())

    assert result.allowed is False
    assert result.cost is None
    assert result.difficulty is None
    assert result.edge_id == "edge-1"


def test_compute_edge_cost_flat_and_paved_has_low_difficulty_and_cost_near_distance():
    edge = _edge(distance_m=100.0)
    elevation = _elevation_attr(average_grade=0.0)
    surface = _surface_attr("asphalt")

    result = compute_edge_cost(edge, elevation, surface, RoutePreference())

    assert result.allowed is True
    assert result.difficulty == 0.0
    assert result.cost == 100.0  # ペナルティ倍率1.0


def test_compute_edge_cost_steep_and_unpaved_costs_more_than_flat_and_paved():
    edge = _edge(distance_m=100.0)

    easy_result = compute_edge_cost(edge, _elevation_attr(0.0), _surface_attr("asphalt"), RoutePreference())
    hard_result = compute_edge_cost(edge, _elevation_attr(12.0), _surface_attr("gravel"), RoutePreference())

    assert hard_result.difficulty > easy_result.difficulty
    assert hard_result.cost > easy_result.cost
    assert hard_result.cost > edge.distance_m  # ペナルティが加算されている


def test_compute_edge_cost_missing_attributes_falls_back_to_distance_only():
    edge = _edge(distance_m=250.0)

    result = compute_edge_cost(edge, None, None, RoutePreference())

    assert result.allowed is True
    assert result.difficulty is None
    assert result.cost == 250.0


def test_compute_edge_cost_respects_custom_weights():
    edge = _edge(distance_m=100.0)
    elevation = _elevation_attr(average_grade=12.0)  # 激坂
    surface = _surface_attr("asphalt")  # 舗装路（易しい）

    elevation_focused = compute_edge_cost(
        edge, elevation, surface, RoutePreference(elevation_weight=1.0, road_weight=0.0)
    )
    road_focused = compute_edge_cost(edge, elevation, surface, RoutePreference(elevation_weight=0.0, road_weight=1.0))

    # 勾配を全く考慮しない重みなら、舗装路のroad_difficulty(0)がそのままdifficultyになる
    assert road_focused.difficulty == 0.0
    # 勾配だけを考慮する重みなら、激坂のgradient_difficultyがそのままdifficultyになる
    assert elevation_focused.difficulty > road_focused.difficulty
