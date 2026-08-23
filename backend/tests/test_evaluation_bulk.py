"""compute_edge_costs_bulk（numpyベクトル化版、改善計画T221/T240）の回帰テスト。

`compute_edge_cost`を1件ずつ呼んだ結果（スカラー版、既存の実装）と`compute_edge_costs_bulk`
（配列版、新実装）が、多様なEdge（highway種別・タグ組み合わせ・欠損データパターンを
網羅する合成グラフ）に対して完全に一致することを確認する。スカラー版は削除しておらず、
本テストのオラクルとして使い続ける。
"""

import itertools

import pytest

from app.domain.attributes import ElevationAttribute
from app.domain.evaluation import (
    RoutePreference,
    compute_edge_cost,
    compute_edge_costs_bulk,
)
from app.domain.graph import DirectedEdge, Node, RoadGraph
from app.domain.recipe import DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE, DEFAULT_ROAD_SUITABILITY_RECIPE
from app.domain.traffic import DEFAULT_CAR_STRESS_RECIPE
from app.domain.weather import WeatherConditions

# 全軸の重みを非ゼロにし、compositeが「一部の軸だけ」で決まらないようにする
# （デフォルトのnight重み0.0だと夜間軸のバグが合成結果に現れず見逃しうるため）。
PREFERENCE = RoutePreference(
    weights={
        "gradient": 1.0,
        "wind": 1.0,
        "surface_q": 1.0,
        "stop_density": 1.0,
        "car_stress": 1.0,
        "accident": 1.0,
        "night": 1.0,
    }
)

WIND = WeatherConditions(
    temperature_c=20.0,
    apparent_temperature_c=None,
    wind_speed_ms=5.0,
    wind_direction_deg=45.0,
    wind_direction_label="北東",
    wind_gusts_ms=None,
    precipitation_probability_percent=None,
    precipitation_mm=None,
    uv_index=None,
    observed_at="2026-01-01T00:00",
)


def _build_diverse_graph() -> tuple[RoadGraph, dict]:
    """highway種別・cycleway・maxspeed・lanes・motor_vehicle・designation・lit/tunnel・
    欠損データパターンの組み合わせで多数のEdgeを作る。materials（way_tags等）も併せて返す。
    """
    highways = ["residential", "primary", "trunk", "motorway", "cycleway", None, "unknown_highway"]
    cycleways = [None, "track", "lane", "shared_lane"]
    maxspeeds = [None, "20", "50", "not_a_number"]
    lanes_variants = [None, "1", "2", "6"]
    bicycle_no = [False, True]
    motor_vehicle_no = [False, True]
    lit = [None, "yes", "no"]
    tunnel = [None, "yes"]

    nodes: dict[str, Node] = {}
    edges: dict[str, DirectedEdge] = {}
    elevation_attributes: dict[str, ElevationAttribute] = {}
    surface_attributes: dict[str, str | None] = {}
    stop_counts: dict[str, int] = {}
    way_tags: dict[str, dict[str, str]] = {}
    intersection_counts: dict[str, int] = {}
    accident_counts: dict[str, int] = {}
    designated_edge_ids: set[str] = set()

    combos = list(
        itertools.product(highways, cycleways, maxspeeds, lanes_variants, bicycle_no, motor_vehicle_no, lit, tunnel)
    )
    # 全組み合わせは大きすぎるため、間引いて代表サンプルを取る（それでも数百件规模）。
    combos = combos[::7]

    lat = 35.0
    for idx, (highway, cycleway, maxspeed, lanes, bike_no, mv_no, lit_val, tunnel_val) in enumerate(combos):
        edge_id = f"e{idx}"
        from_id = f"n{idx}a"
        to_id = f"n{idx}b"
        lat += 0.001
        nodes[from_id] = Node(node_id=from_id, latitude=lat, longitude=139.0)
        nodes[to_id] = Node(node_id=to_id, latitude=lat, longitude=139.001)

        tags: dict[str, str] = {}
        if cycleway is not None:
            tags["cycleway"] = cycleway
        if maxspeed is not None:
            tags["maxspeed"] = maxspeed
        if lanes is not None:
            tags["lanes"] = lanes
        if bike_no:
            tags["bicycle"] = "no"
        if mv_no:
            tags["motor_vehicle"] = "no"
        if lit_val is not None:
            tags["lit"] = lit_val
        if tunnel_val is not None:
            tags["tunnel"] = tunnel_val

        bearing_deg = float(idx % 360) if idx % 5 != 0 else None
        distance_m = 50.0 + (idx % 20) * 37.3
        edges[edge_id] = DirectedEdge(
            edge_id=edge_id,
            from_node_id=from_id,
            to_node_id=to_id,
            geometry=[[lat, 139.0], [lat, 139.001]],
            distance_m=distance_m,
            osm_way_id=idx,
            highway=highway,
            bearing_deg=bearing_deg,
        )

        # データ欠損パターンを織り交ぜる（3件に1件は各材料を欠損させる）。
        if idx % 3 != 0:
            elevation_attributes[edge_id] = ElevationAttribute(
                edge_id=edge_id,
                average_grade=((idx % 40) - 20) * 0.7,
                data_source="test",
                calculated_at="t",
            )
        if idx % 4 != 0:
            surface_attributes[edge_id] = ["asphalt", "paved", "gravel", "unknown_surface", None][idx % 5]
        if idx % 3 != 1:
            stop_counts[edge_id] = idx % 5
        if idx % 5 != 2:
            intersection_counts[edge_id] = idx % 3
        if idx % 6 != 3:
            accident_counts[edge_id] = idx % 4
        way_tags[edge_id] = tags
        if idx % 9 == 0:
            designated_edge_ids.add(edge_id)

    graph = RoadGraph(graph_version="test", nodes=nodes, edges=edges)
    materials = dict(
        elevation_attributes=elevation_attributes,
        surface_attributes=surface_attributes,
        stop_counts=stop_counts,
        way_tags=way_tags,
        intersection_counts=intersection_counts,
        accident_counts=accident_counts,
        designated_edge_ids=designated_edge_ids,
    )
    return graph, materials


@pytest.mark.parametrize("wind", [None, WIND])
@pytest.mark.parametrize("max_average_grade_percent", [None, 8.0])
@pytest.mark.parametrize("penalty_strength", [1.0, 2.5])
def test_bulk_matches_scalar_for_every_edge(wind, max_average_grade_percent, penalty_strength):
    graph, materials = _build_diverse_graph()
    weights = PREFERENCE.weights

    scalar_results = {
        edge_id: compute_edge_cost(
            edge,
            materials["elevation_attributes"].get(edge_id),
            materials["surface_attributes"].get(edge_id),
            PREFERENCE,
            weights=weights,
            wind=wind,
            stop_count=materials["stop_counts"].get(edge_id),
            way_tags=materials["way_tags"].get(edge_id),
            intersection_count=materials["intersection_counts"].get(edge_id),
            accident_count=materials["accident_counts"].get(edge_id),
            accident_years_covered=3,
            is_designated=edge_id in materials["designated_edge_ids"],
            car_stress_recipe=DEFAULT_CAR_STRESS_RECIPE,
            road_suitability_recipe=DEFAULT_ROAD_SUITABILITY_RECIPE,
            motor_vehicle_density_recipe=DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
            penalty_strength=penalty_strength,
            max_average_grade_percent=max_average_grade_percent,
        )
        for edge_id, edge in graph.edges.items()
    }

    bulk_results = compute_edge_costs_bulk(
        graph,
        materials["elevation_attributes"],
        materials["surface_attributes"],
        PREFERENCE,
        car_stress_recipe=DEFAULT_CAR_STRESS_RECIPE,
        road_suitability_recipe=DEFAULT_ROAD_SUITABILITY_RECIPE,
        motor_vehicle_density_recipe=DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
        wind=wind,
        stop_counts=materials["stop_counts"],
        way_tags=materials["way_tags"],
        intersection_counts=materials["intersection_counts"],
        accident_counts=materials["accident_counts"],
        accident_years_covered=3,
        designated_edge_ids=materials["designated_edge_ids"],
        penalty_strength=penalty_strength,
        max_average_grade_percent=max_average_grade_percent,
        weights=weights,
    )

    assert set(bulk_results.keys()) == set(scalar_results.keys())
    mismatches = []
    for edge_id, scalar in scalar_results.items():
        bulk = bulk_results[edge_id]
        if (bulk.allowed, bulk.cost, bulk.difficulty) != (scalar.allowed, scalar.cost, scalar.difficulty):
            mismatches.append((edge_id, scalar, bulk))
    assert not mismatches, f"{len(mismatches)}件不一致: {mismatches[:5]}"


def test_bulk_returns_empty_dict_for_empty_graph():
    graph = RoadGraph(graph_version="test", nodes={}, edges={})
    result = compute_edge_costs_bulk(graph, {}, {}, PREFERENCE)
    assert result == {}
