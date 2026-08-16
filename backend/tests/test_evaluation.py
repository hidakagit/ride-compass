import pytest

from app.domain.attributes import ElevationAttribute
from app.domain.evaluation import RoutePreference, compute_edge_cost, compute_wind_penalty, is_edge_allowed
from app.domain.graph import DirectedEdge
from app.domain.weather import WeatherConditions


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


def test_is_edge_allowed_excludes_motorway():
    assert is_edge_allowed(_edge(highway="motorway")) is False
    assert is_edge_allowed(_edge(highway="motorway_link")) is False


def test_is_edge_allowed_allows_residential():
    assert is_edge_allowed(_edge(highway="residential")) is True


def test_is_edge_allowed_allows_unknown_highway():
    assert is_edge_allowed(_edge(highway=None)) is True


def test_is_edge_allowed_excludes_bicycle_no():
    # 改善計画T100: bicycle=noのHard Constraint化。highway自体は許可種別でも除外する。
    assert is_edge_allowed(_edge(highway="residential"), {"bicycle": "no"}) is False


def test_is_edge_allowed_bicycle_no_is_case_and_whitespace_insensitive():
    assert is_edge_allowed(_edge(highway="residential"), {"bicycle": " NO "}) is False


def test_is_edge_allowed_allows_bicycle_yes():
    assert is_edge_allowed(_edge(highway="residential"), {"bicycle": "yes"}) is True


def test_is_edge_allowed_allows_missing_way_tags():
    # way_tags=None（未取得）は判断材料が無いため除外しない（highway不明時と同じ方針）。
    assert is_edge_allowed(_edge(highway="residential"), None) is True


def test_is_edge_allowed_allows_way_tags_without_bicycle_key():
    assert is_edge_allowed(_edge(highway="residential"), {"lanes": "2"}) is True


def test_compute_edge_cost_excludes_disallowed_edge():
    edge = _edge(highway="motorway")
    result = compute_edge_cost(edge, None, None, RoutePreference())

    assert result.allowed is False
    assert result.cost is None


def test_compute_edge_cost_excludes_bicycle_no_edge():
    # 改善計画T100: way_tags経由でbicycle=noが渡るとcompute_edge_cost全体がHard Constraintで
    # 除外される（is_edge_allowedのテストと同じ判定を、実際の呼び出し経路で確認）。
    edge = _edge(highway="residential")
    result = compute_edge_cost(edge, None, None, RoutePreference(), way_tags={"bicycle": "no"})

    assert result.allowed is False
    assert result.cost is None
    assert result.difficulty is None
    assert result.difficulty is None
    assert result.edge_id == "edge-1"


def test_compute_edge_cost_flat_and_paved_has_low_difficulty_and_cost_near_distance():
    edge = _edge(distance_m=100.0)
    elevation = _elevation_attr(average_grade=0.0)
    surface = "asphalt"

    result = compute_edge_cost(edge, elevation, surface, RoutePreference())

    assert result.allowed is True
    assert result.difficulty == 0.0
    assert result.cost == 100.0  # ペナルティ倍率1.0


def test_compute_edge_cost_steep_and_unpaved_costs_more_than_flat_and_paved():
    edge = _edge(distance_m=100.0)

    easy_result = compute_edge_cost(edge, _elevation_attr(0.0), "asphalt", RoutePreference())
    hard_result = compute_edge_cost(edge, _elevation_attr(12.0), "gravel", RoutePreference())

    assert hard_result.difficulty > easy_result.difficulty
    assert hard_result.cost > easy_result.cost
    assert hard_result.cost > edge.distance_m  # ペナルティが加算されている


def test_compute_edge_cost_missing_attributes_falls_back_to_distance_only():
    edge = _edge(distance_m=250.0)

    result = compute_edge_cost(edge, None, None, RoutePreference())

    assert result.allowed is True
    assert result.difficulty is None
    assert result.cost == 250.0


def _wind(wind_speed_ms: float, wind_direction_deg: float) -> WeatherConditions:
    return WeatherConditions(
        temperature_c=20.0,
        wind_speed_ms=wind_speed_ms,
        wind_direction_deg=wind_direction_deg,
        wind_direction_label="北",
        precipitation_probability_percent=None,
        observed_at="2026-01-01T00:00",
    )


def test_compute_wind_penalty_headwind_is_positive():
    # Edgeは北向き（bearing=0）に進む。北から吹いてくる風（wind_direction_deg=0）は正面からの
    # 向かい風になるはず（domain/wind.py: WindCalculatorの規約と同じ）。
    edge = _edge(geometry=[[35.700, 139.700], [35.701, 139.700]])
    wind = _wind(wind_speed_ms=5.0, wind_direction_deg=0.0)

    penalty = compute_wind_penalty(edge, wind)

    assert penalty == pytest.approx(5.0, abs=0.1)


def test_compute_wind_penalty_tailwind_is_negative():
    edge = _edge(geometry=[[35.700, 139.700], [35.701, 139.700]])
    wind = _wind(wind_speed_ms=5.0, wind_direction_deg=180.0)  # 南から北へ吹く=追い風

    penalty = compute_wind_penalty(edge, wind)

    assert penalty == pytest.approx(-5.0, abs=0.1)


def test_compute_wind_penalty_returns_none_without_wind():
    edge = _edge()

    assert compute_wind_penalty(edge, None) is None


def test_compute_edge_cost_headwind_costs_more_than_tailwind():
    edge = _edge(distance_m=100.0, geometry=[[35.700, 139.700], [35.701, 139.700]])
    elevation = _elevation_attr(0.0)
    surface = "asphalt"

    headwind_result = compute_edge_cost(edge, elevation, surface, RoutePreference(), wind=_wind(8.0, 0.0))
    tailwind_result = compute_edge_cost(edge, elevation, surface, RoutePreference(), wind=_wind(8.0, 180.0))

    assert headwind_result.difficulty > tailwind_result.difficulty
    assert headwind_result.cost > tailwind_result.cost


def test_compute_edge_cost_without_wind_ignores_wind_weight():
    edge = _edge(distance_m=100.0)
    elevation = _elevation_attr(0.0)
    surface = "asphalt"

    result = compute_edge_cost(edge, elevation, surface, RoutePreference())  # windを渡さない

    # 標高・路面がどちらも「易しい」なら、風が無視される限りdifficultyは0のはず
    assert result.difficulty == 0.0


def test_compute_edge_cost_without_stop_count_ignores_stop_weight():
    edge = _edge(distance_m=100.0)
    elevation = _elevation_attr(0.0)
    surface = "asphalt"

    result = compute_edge_cost(edge, elevation, surface, RoutePreference())  # stop_countを渡さない

    assert result.difficulty == 0.0


def test_compute_edge_cost_more_stops_costs_more():
    edge = _edge(distance_m=1000.0)
    elevation = _elevation_attr(0.0)
    surface = "asphalt"

    no_stops = compute_edge_cost(edge, elevation, surface, RoutePreference(), stop_count=0)
    many_stops = compute_edge_cost(edge, elevation, surface, RoutePreference(), stop_count=4)

    assert many_stops.difficulty > no_stops.difficulty
    assert many_stops.cost > no_stops.cost


def test_compute_edge_cost_respects_custom_weights():
    edge = _edge(distance_m=100.0)
    elevation = _elevation_attr(average_grade=12.0)  # 激坂
    surface = "asphalt"  # 舗装路（易しい）

    elevation_focused = compute_edge_cost(
        edge, elevation, surface, RoutePreference(elevation_weight=1.0, road_weight=0.0)
    )
    road_focused = compute_edge_cost(edge, elevation, surface, RoutePreference(elevation_weight=0.0, road_weight=1.0))

    # 勾配を全く考慮しない重みなら、舗装路のroad_difficulty(0)がそのままdifficultyになる
    assert road_focused.difficulty == 0.0
    # 勾配だけを考慮する重みなら、激坂のgradient_difficultyがそのままdifficultyになる
    assert elevation_focused.difficulty > road_focused.difficulty
