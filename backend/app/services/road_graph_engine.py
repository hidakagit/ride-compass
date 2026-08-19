"""Road Graph + NetworkX（Dijkstra）の自前ルーティングエンジン（試験実装）。

`RouteGenerator`（services/route_generator.py）の`LoopRoutingEngine`契約を実装する。
Road Graph・Evaluation Engine・Route Engine（domain/routing.py）を使って経由地点間の
経路を自前で計算する。ルーティング自体（経路探索の品質・速度）は将来拡張として
引き続き開発中で、`config.py`の`routing_engine`設定で既定のopenrouteservice委譲
（openrouteservice_engine.py）と切り替えて使う。

設計上の重要な決定（実機検証で判明した問題への対応）:
- **Overpassへの問い合わせは1回だけ**: 8方位が個別にbboxを計算して並列問い合わせすると
  公開インスタンスに拒否され全滅することを実機確認したため、起点を中心とした単一の円
  （8方位分の経由地点をすべて覆う半径）でRoad Graphを`prepare`で1回だけ取得し、
  全方位で共有する。
- **標高はパス確定後・距離フィルタ通過後の候補だけへ絞って取得する**: Road Graph全体
  （数万Edge）への標高取得は非現実的に遅いことを実機確認したため、経路探索は標高を
  使わないCost（distance・路面・風）で行い、`evaluate_loops`（距離フィルタ通過後）で
  その経路上のEdgeだけに標高を取得する。**この結果、標高（勾配）は経路選択には影響せず、
  確定後の表示・スコアリングにのみ使われる**（PostGISキャッシュ有効化後に探索コストへ
  戻すことを検討、docs/architecture.md参照）。
- 風は出発時点の起点付近の風をルート全体に一様適用する（探索中は到達時刻が未確定のため。
  OpenRouteServiceEngineの「区間ごとの推定到達時刻の風」とは意味が異なる点に注意。
  レスポンスの`engine`フィールドで識別できる）。
- NetworkXの`DiGraph`は同一ノード間の並行Edgeを1本しか保持しない（`MultiDiGraph`ではない）。
  稀なケースでは最安のEdgeが選ばれない可能性がある。
"""

import asyncio
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import networkx as nx

from app.domain.accident import distance_weighted_accident_density
from app.domain.difficulty import distance_weighted_difficulty
from app.domain.errors import RoutingError
from app.domain.evaluation import (
    RoutePreference,
    compute_cost_from_axis_scores,
    compute_edge_axis_scores,
    compute_wind_penalty,
    preference_to_axis_weights,
)
from app.domain.graph import DirectedEdge, RoadGraph
from app.domain.recipe import MotorVehicleDensityRecipe, RoadSuitabilityRecipe
from app.domain.region import BoundingBox
from app.domain.road import classify_osm_surface, distance_weighted_road_score
from app.domain.route import Coordinates, RouteCandidate, RouteSegmentDetail
from app.domain.traffic import (
    CarStressRecipe,
    classify_bicycle_infrastructure,
    distance_weighted_bicycle_infra_score,
    distance_weighted_intersection_density,
    distance_weighted_stop_density,
    is_dedicated_bicycle_infra,
    car_stress_level,
)
from app.domain.routing import build_networkx_graph, concat_node_paths, find_nearest_node, path_to_edge_ids, shortest_path_node_ids
from app.domain.weather import WeatherConditions
from app.domain.wind import ASSUMED_SPEED_KMH
from app.services.elevation_attribute_service import ElevationAttributeService
from app.services.evaluation_service import EvaluationService
from app.services.graph_service import GraphService
from app.services.route_generator import TracedLoop, candidate_identity
from app.services.weather_service import WeatherService

# Road Graphを取得するbboxは、起点・経由地2点の外接矩形にこのマージンを足したもの。
# 実際の道なりは直線距離の外接矩形からはみ出ることが多い（川・線路等を迂回する等）ため、
# 探索が失敗しない程度の余裕を持たせる。半径に比例させつつ最低値を設ける暫定値であり、
# 実データでの検証結果次第で見直す（docs/architecture.md参照）。
BBOX_MARGIN_RATIO = 0.3
BBOX_MARGIN_MIN_KM = 2.0


@dataclass
class _RoadGraphContext:
    """prepareで構築し、全方位のtrace_loop/evaluate_loopsで共有するリクエスト単位の状態。"""

    graph: RoadGraph
    nx_graph: nx.DiGraph
    surface_attributes: dict[str, str | None]
    stop_counts: dict[str, int]
    way_tags: dict[str, dict[str, str]]
    intersection_counts: dict[str, int]
    accident_counts: dict[str, int]
    accident_years_covered: int
    designated_edge_ids: set[str]
    wind: WeatherConditions | None
    origin_node: str


class RoadGraphEngine:
    engine_name = "road_graph"

    def __init__(
        self,
        graph_service: GraphService,
        elevation_attribute_service: ElevationAttributeService,
        evaluation_service: EvaluationService,
        weather_service: WeatherService,
        route_preference: RoutePreference,
        car_stress_recipe: CarStressRecipe | None = None,
        road_suitability_recipe: RoadSuitabilityRecipe | None = None,
        motor_vehicle_density_recipe: MotorVehicleDensityRecipe | None = None,
    ):
        self._graph_service = graph_service
        self._elevation_attribute_service = elevation_attribute_service
        self._evaluation_service = evaluation_service
        self._weather_service = weather_service
        self._route_preference = route_preference
        self._car_stress_recipe = car_stress_recipe
        self._road_suitability_recipe = road_suitability_recipe
        self._motor_vehicle_density_recipe = motor_vehicle_density_recipe

    async def prepare(self, origin: Coordinates, radius_km: float) -> _RoadGraphContext | None:
        margin_km = max(BBOX_MARGIN_MIN_KM, radius_km * BBOX_MARGIN_RATIO)
        bbox = _bbox_around_point(origin, radius_km + margin_km)

        built = await self._graph_service.get_or_build_graph_with_attributes(bbox)
        if built is None or not built[0].edges:
            return None
        graph, surface_attributes = built
        # 静的道路属性P1（信号・横断歩道・一時停止・踏切）。探索コスト自体にも反映されるよう
        # ここで取得する（surface_attributesと同じくprepareで1回だけ・全方位で共有）。
        stop_counts = await self._graph_service.get_stop_poi_counts(list(graph.edges.keys()))
        # 静的道路属性P1残り（車ストレス・自転車インフラ・交差点密度）。同じくprepareで
        # 1回だけ取得し全方位で共有する。way_tagsはEdgeのosm_way_id経由のタグ、
        # intersection_countsはこのローカルグラフ内で計算した交差点件数（次数3以上のNode）。
        way_tags = await self._graph_service.get_way_tags(list(graph.edges.keys()))
        intersection_counts = await self._graph_service.get_intersection_counts(list(graph.edges.keys()))
        # 外部静的データソース T50残作業（事故密度、8軸目）。同じくprepareで1回だけ取得し
        # 全方位で共有する。accident_years_coveredは密度の「件/(km・年)」正規化に使う。
        accident_counts = await self._graph_service.get_accident_counts(list(graph.edges.keys()))
        accident_years_covered = await self._graph_service.get_accident_years_covered()
        # 指定路線コンフレーション機構（外部静的データソース T51）。KSJ N10/N12該当エッジの
        # 集合を同じくprepareで1回だけ取得し全方位で共有する。
        designated_edge_ids = await self._graph_service.get_designated_edge_ids(list(graph.edges.keys()))

        origin_node = find_nearest_node(graph, origin)
        if origin_node is None:
            return None

        wind = await self._weather_service.get_conditions(origin)
        # 探索用Costは標高を含めない（理由はモジュールdocstring参照）。
        search_edge_costs = self._evaluation_service.evaluate_graph(
            graph, {}, surface_attributes, wind=wind, stop_counts=stop_counts,
            way_tags=way_tags, intersection_counts=intersection_counts,
            accident_counts=accident_counts, accident_years_covered=accident_years_covered,
            designated_edge_ids=designated_edge_ids,
        )
        nx_graph = build_networkx_graph(graph, search_edge_costs)

        return _RoadGraphContext(
            graph=graph,
            nx_graph=nx_graph,
            surface_attributes=surface_attributes,
            stop_counts=stop_counts,
            way_tags=way_tags,
            intersection_counts=intersection_counts,
            accident_counts=accident_counts,
            accident_years_covered=accident_years_covered,
            designated_edge_ids=designated_edge_ids,
            wind=wind,
            origin_node=origin_node,
        )

    async def trace_loop(
        self, context: _RoadGraphContext, waypoints: list[Coordinates], bearing: int
    ) -> TracedLoop:
        # waypoints = [起点, 経由地A, 経由地B, 起点]（RouteGenerator._loop_waypoints）。
        # 起点は最近接NodeをprepareでスナップしたNodeを使い、経由地2点をここでスナップする。
        node_a = find_nearest_node(context.graph, waypoints[1])
        node_b = find_nearest_node(context.graph, waypoints[2])
        if node_a is None or node_b is None:
            raise RoutingError(f"direction {bearing}: could not snap waypoints to road graph")

        path_1 = shortest_path_node_ids(context.nx_graph, context.origin_node, node_a)
        path_2 = shortest_path_node_ids(context.nx_graph, node_a, node_b)
        path_3 = shortest_path_node_ids(context.nx_graph, node_b, context.origin_node)
        if path_1 is None or path_2 is None or path_3 is None:
            raise RoutingError(f"direction {bearing}: no path found between waypoints")

        full_path = concat_node_paths([path_1, path_2, path_3])
        edge_ids = path_to_edge_ids(context.nx_graph, full_path)
        if not edge_ids:
            raise RoutingError(f"direction {bearing}: resulting path has no edges")
        edges_in_path = [context.graph.edges[edge_id] for edge_id in edge_ids]

        distance_km = round(sum(edge.distance_m for edge in edges_in_path) / 1000, 2)
        return TracedLoop(bearing=bearing, distance_km=distance_km, data=edges_in_path)

    async def evaluate_loops(
        self, context: _RoadGraphContext, traced: list[TracedLoop], start_time: datetime
    ) -> list[RouteCandidate]:
        # 標高は経路確定後・距離フィルタ通過後の候補だけに絞って取得する
        # （モジュールdocstring参照。棄却済み候補へのGSI問い合わせを避ける）。
        return list(
            await asyncio.gather(*(self._build_candidate(context, t, start_time) for t in traced))
        )

    async def _build_candidate(
        self, context: _RoadGraphContext, traced: TracedLoop, start_time: datetime
    ) -> RouteCandidate:
        edges_in_path: list[DirectedEdge] = traced.data

        path_graph = RoadGraph(
            graph_version=context.graph.graph_version,
            nodes=context.graph.nodes,
            edges={edge.edge_id: edge for edge in edges_in_path},
        )
        elevation_attributes = await self._elevation_attribute_service.get_attributes_for_graph(path_graph)

        geometry = _concat_edge_geometries(edges_in_path)
        elevation_stats = _aggregate_elevation(edges_in_path, elevation_attributes)
        road_score = _aggregate_road_score(edges_in_path, context.surface_attributes)
        wind_score = _aggregate_wind_score(edges_in_path, context.wind)
        stop_density = _aggregate_stop_density(edges_in_path, context.stop_counts)
        intersection_density = _aggregate_intersection_density(edges_in_path, context.intersection_counts)
        accident_density = _aggregate_accident_density(
            edges_in_path, context.accident_counts, context.accident_years_covered
        )
        segments = self._build_segment_details(edges_in_path, elevation_attributes, context, start_time)
        car_stress_score = distance_weighted_difficulty(
            [(s.car_stress, s.distance_km) for s in segments]
        )
        bicycle_infra_score = distance_weighted_bicycle_infra_score(
            [(s.distance_km, is_dedicated_bicycle_infra(s.bicycle_infra)) for s in segments]
        )

        return RouteCandidate(
            **candidate_identity(traced.bearing),
            distance_km=traced.distance_km,
            geometry=geometry,
            wind_score=wind_score,
            road_score=road_score,
            stop_density=stop_density,
            car_stress_score=car_stress_score,
            bicycle_infra_score=bicycle_infra_score,
            intersection_density=intersection_density,
            accident_density=accident_density,
            segments=segments,
            **elevation_stats,
        )

    def _build_segment_details(
        self,
        edges: list[DirectedEdge],
        elevation_attributes: dict,
        context: _RoadGraphContext,
        start_time: datetime,
    ) -> list[RouteSegmentDetail]:
        # 改善計画T79: 以前は11個の位置引数を取り、うち8個はcontextフィールドの単純展開
        # だった（同型dict[str, int]が3つ並び、順序取り違えが検知されない構造）。
        # edges・elevation_attributes・start_timeはcontextに無いリクエスト単位の値
        # （edges=方位ごとの経路、elevation_attributes=経路確定後に取得、start_time=呼び出し元
        # 引数）のため、これらだけを個別引数として残しcontextを1引数で渡す。
        preference = self._route_preference
        segments = []
        cumulative_km = 0.0

        for edge in edges:
            distance_km = edge.distance_m / 1000
            elevation_attr = elevation_attributes.get(edge.edge_id)
            surface_type = context.surface_attributes.get(edge.edge_id)
            stop_count = context.stop_counts.get(edge.edge_id)
            edge_way_tags = context.way_tags.get(edge.edge_id)
            intersection_count = context.intersection_counts.get(edge.edge_id)
            accident_count = context.accident_counts.get(edge.edge_id)

            gradient_percent = elevation_attr.average_grade if elevation_attr else None
            wind_penalty = compute_wind_penalty(edge, context.wind)
            road_surface_good = classify_osm_surface(surface_type)
            stop_count_per_km = stop_count / distance_km if stop_count is not None and distance_km > 0 else None
            is_designated = edge.edge_id in context.designated_edge_ids
            car_stress = (
                car_stress_level(
                    edge.highway,
                    edge_way_tags,
                    is_designated,
                    self._car_stress_recipe,
                    road_suitability_recipe=self._road_suitability_recipe,
                    motor_vehicle_density_recipe=self._motor_vehicle_density_recipe,
                )
                if edge_way_tags is not None
                else None
            )
            bicycle_infra = (
                classify_bicycle_infrastructure(edge_way_tags, edge.highway) if edge_way_tags is not None else None
            )

            # 改善計画T143: 区間表示の軸別スコアは、コスト計算（compute_edge_cost、
            # EvaluationService.evaluate_graph経由）と同じcompute_edge_axis_scores（T142）を
            # 通す。設計プロンプトの完了条件「地図表示とルーティングコストが同一のレシピ定義
            # から生成される」に対応し、二次の計算式が表示・探索コストの2箇所に独立実装される
            # 非DRY構造（現状把握C.で判明）を解消する。
            axis_scores = compute_edge_axis_scores(
                edge, elevation_attr, surface_type,
                wind=context.wind, stop_count=stop_count, way_tags=edge_way_tags,
                intersection_count=intersection_count, accident_count=accident_count,
                accident_years_covered=context.accident_years_covered, is_designated=is_designated,
                car_stress_recipe=self._car_stress_recipe,
                road_suitability_recipe=self._road_suitability_recipe,
                motor_vehicle_density_recipe=self._motor_vehicle_density_recipe,
            )
            weights = preference_to_axis_weights(preference)
            _, composite_difficulty_value = compute_cost_from_axis_scores(edge.distance_m, axis_scores, weights)

            # 区間ごとの推定到達時刻の表示にのみ使う（風の評価は出発時点の風をルート全体に
            # 一様適用する簡略化のため、到達時刻そのものはwindのfetchには使わない。
            # domain/evaluation.py: compute_wind_penaltyのdocstring参照）。
            elapsed_hours = cumulative_km / ASSUMED_SPEED_KMH
            arrival_time = start_time + timedelta(hours=elapsed_hours)

            start_lat, start_lon = edge.geometry[0]
            end_lat, end_lon = edge.geometry[-1]
            # 区間の道なり形状はEdgeの形状点列そのもの（追加取得なし）。2点未満のEdgeは
            # 形状にならないためNone（フロントは始点・終点の直線で代替描画する）。
            segment_coordinates = [[lon, lat] for lat, lon in edge.geometry]

            segments.append(
                RouteSegmentDetail(
                    geometry=(
                        {"type": "LineString", "coordinates": segment_coordinates}
                        if len(segment_coordinates) >= 2
                        else None
                    ),
                    start_latitude=start_lat,
                    start_longitude=start_lon,
                    end_latitude=end_lat,
                    end_longitude=end_lon,
                    cumulative_distance_km=round(cumulative_km, 2),
                    distance_km=round(distance_km, 2),
                    estimated_arrival_time=arrival_time.isoformat(),
                    gradient_percent=round(gradient_percent, 1) if gradient_percent is not None else None,
                    wind_penalty=round(wind_penalty, 2) if wind_penalty is not None else None,
                    road_surface_good=road_surface_good,
                    car_stress=car_stress,
                    bicycle_infra=bicycle_infra,
                    elevation_difficulty=axis_scores.get("gradient"),
                    wind_difficulty=axis_scores.get("wind"),
                    road_difficulty=axis_scores.get("surface_q"),
                    stop_difficulty=axis_scores.get("stop_density"),
                    car_stress_difficulty=axis_scores.get("car_stress"),
                    accident_difficulty=axis_scores.get("accident"),
                    night_difficulty=axis_scores.get("night"),
                    difficulty=composite_difficulty_value,
                )
            )
            cumulative_km += distance_km

        return segments


def _bbox_around_point(center: Coordinates, radius_km: float) -> BoundingBox:
    """centerを中心とした半径radius_kmの円を覆う矩形bboxを求める（1回のOverpass問い合わせで
    8方位全ての経由地点をカバーするため、方位ごとではなく起点1つに対して1回だけ計算する）。"""
    lat_margin_deg = radius_km / 111.0
    lon_margin_deg = radius_km / (111.0 * max(math.cos(math.radians(center.latitude)), 1e-6))
    return BoundingBox(
        min_latitude=center.latitude - lat_margin_deg,
        max_latitude=center.latitude + lat_margin_deg,
        min_longitude=center.longitude - lon_margin_deg,
        max_longitude=center.longitude + lon_margin_deg,
    )


def _concat_edge_geometries(edges: list[DirectedEdge]) -> dict:
    """経路上のEdge群をひとつながりのGeoJSON LineStringへ変換する。隣接するEdgeの
    境界点（前Edgeの終端＝次Edgeの始端）は重複させない。"""
    coordinates: list[list[float]] = []
    for edge in edges:
        points = [[lon, lat] for lat, lon in edge.geometry]
        if coordinates and points and coordinates[-1] == points[0]:
            points = points[1:]
        coordinates.extend(points)
    return {"type": "LineString", "coordinates": coordinates}


def _aggregate_elevation(edges: list[DirectedEdge], elevation_attributes: dict) -> dict:
    attrs = [elevation_attributes.get(edge.edge_id) for edge in edges]
    valid = [a for a in attrs if a is not None]

    gains = [a.elevation_gain_m for a in valid if a.elevation_gain_m is not None]
    elevations: list[float] = []
    for a in valid:
        if a.start_elevation_m is not None:
            elevations.append(a.start_elevation_m)
        if a.end_elevation_m is not None:
            elevations.append(a.end_elevation_m)
    grades = [abs(a.max_grade) for a in valid if a.max_grade is not None]
    grades += [abs(a.min_grade) for a in valid if a.min_grade is not None]

    return {
        "elevation_gain_m": round(sum(gains), 1) if gains else None,
        "min_elevation_m": round(min(elevations), 1) if elevations else None,
        "max_elevation_m": round(max(elevations), 1) if elevations else None,
        "max_gradient_percent": round(max(grades), 1) if grades else None,
    }


def _aggregate_road_score(edges: list[DirectedEdge], surface_attributes: dict[str, str | None]) -> float | None:
    """経路の総距離に対する「走行しやすい舗装路面」の割合(%)を算出する。Edge単位のsurfaceタグを
    domain/road.py: distance_weighted_road_score（両エンジン共通の集約定義、改善計画T21）へ渡す薄いラッパー。
    """
    return distance_weighted_road_score(
        [(edge.distance_m, classify_osm_surface(surface_attributes.get(edge.edge_id))) for edge in edges]
    )


def _aggregate_stop_density(edges: list[DirectedEdge], stop_counts: dict[str, int]) -> float | None:
    """経路全体の信号・横断歩道・一時停止・踏切の合計密度(回/km)。Edge単位のカウントを
    domain/traffic.py: distance_weighted_stop_density（両エンジン共通の集約定義、
    静的道路属性P1）へ渡す薄いラッパー。stop_countsに無いEdge（repository未注入等で
    データ自体を取得していない）はNone扱いとし、distance_weighted_stop_density側で
    「実測0件」と区別して除外される（road_score等の「不明はNone」と同じ方針）。
    """
    return distance_weighted_stop_density(
        [(edge.distance_m / 1000, stop_counts.get(edge.edge_id)) for edge in edges]
    )


def _aggregate_intersection_density(edges: list[DirectedEdge], intersection_counts: dict[str, int]) -> float | None:
    """経路全体の交差点（次数3以上のNode）の合計密度(回/km)。_aggregate_stop_densityと
    同じ薄いラッパー（静的道路属性P1残り、intersectionDensity）。
    """
    return distance_weighted_intersection_density(
        [(edge.distance_m / 1000, intersection_counts.get(edge.edge_id)) for edge in edges]
    )


def _aggregate_accident_density(
    edges: list[DirectedEdge], accident_counts: dict[str, int], accident_years_covered: int
) -> float | None:
    """経路全体の事故密度(件/(km・年))。_aggregate_stop_density/_aggregate_intersection_density
    と同じ薄いラッパー（外部静的データソース T50残作業、8軸目）。
    """
    return distance_weighted_accident_density(
        [(edge.distance_m / 1000, accident_counts.get(edge.edge_id)) for edge in edges], accident_years_covered
    )


def _aggregate_wind_score(edges: list[DirectedEdge], wind: WeatherConditions | None) -> float | None:
    """経路全体の距離加重平均wind_penalty（符号付きm/s、正=正味向かい風）。
    OpenRouteServiceEngine（WindService）と同じ加重平均の考え方だが、風は区間ごとの
    推定到達時刻ではなく出発時点の値をルート全体に一様適用する
    （domain/evaluation.py: compute_wind_penalty参照）。
    """
    weighted_total = 0.0
    total_weight = 0.0
    for edge in edges:
        penalty = compute_wind_penalty(edge, wind)
        if penalty is None:
            continue
        distance_km = edge.distance_m / 1000
        if distance_km > 0:
            weighted_total += penalty * distance_km
            total_weight += distance_km

    if total_weight == 0:
        return None
    return round(weighted_total / total_weight, 2)
