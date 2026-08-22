"""RoadGraphEngine（Road Graph + NetworkX Dijkstraエンジン）のテスト。

RouteGenerator（戦略層）を通したエンドツーエンドで、エンジン固有の責務
（Road Graph取得が1回のみ・Dijkstra経路・標高がパス上のEdgeだけに絞られること・
Edge単位の集計とsegments構築）を検証する。戦略側の責務（距離フィルタ・失敗スキップ等）は
test_route_generator.pyで検証済み。
"""

from datetime import datetime, timezone

import pytest

from app.domain import evaluation
from app.domain.attributes import EdgeAttributeCounts, ElevationAttribute
from app.domain.evaluation import RoutePreference
from app.domain.geo import bearing_between, destination_point, haversine_distance_km
from app.domain.graph import DirectedEdge, Node, RoadGraph
from app.domain.route import Coordinates
from app.domain.weather import WeatherConditions
from app.services import road_graph_engine
from app.services.evaluation_service import EvaluationService
from app.services.road_graph_engine import RoadGraphEngine
from app.services.route_generator import DIRECTIONS_DEG, RADIUS_RATIO, RouteGenerator
from app.services.route_scorer import RouteScorer

ORIGIN = Coordinates(latitude=35.7597, longitude=139.7387)
SCORING_WEIGHTS = {"distance_weight": 0.30, "elevation_weight": 0.15, "wind_weight": 0.30, "road_weight": 0.25}


def make_route_scorer() -> RouteScorer:
    return RouteScorer(SCORING_WEIGHTS)


def _edge(edge_id: str, from_id: str, to_id: str, from_coord: Coordinates, to_coord: Coordinates, **overrides) -> DirectedEdge:
    # 改善計画T218: bearing_degはbuild_road_graphと同じくfrom_coord→to_coordの実際の
    # 方位角から算出する（compute_wind_penaltyがgeometryではなくこの値を直接使うため、
    # テスト用Edgeでも実データと同じ計算式で埋めておく必要がある）。
    defaults = dict(
        edge_id=edge_id,
        from_node_id=from_id,
        to_node_id=to_id,
        geometry=[[from_coord.latitude, from_coord.longitude], [to_coord.latitude, to_coord.longitude]],
        distance_m=haversine_distance_km(from_coord, to_coord) * 1000,
        bearing_deg=bearing_between(from_coord, to_coord),
    )
    defaults.update(overrides)
    return DirectedEdge(**defaults)


def build_loop_graph(origin: Coordinates, distance_km: float, *, skip_bearings: set[int] = frozenset()) -> RoadGraph:
    """route_generator.pyが実際に使うのと同じdestination_point/RADIUS_RATIOで、
    起点を中心とした「車輪」状のRoad Graphを構築する: 各方位（DIRECTIONS_DEG）の
    半径radius_km地点をスポーク（起点↔各点）で結び、隣り合う地点同士をアーク
    （bearing地点↔bearing+45地点）で結ぶ。

    ある方位bearingの周回候補は「起点→bearing地点→(bearing+45)地点→起点」という
    経路になる。これはwaypoint_a(bearing)とwaypoint_b(bearing)がそれぞれ
    「bearing地点」「(bearing+45)地点」に対応し、かつ隣接するbearingの
    waypoint_bとwaypoint_aが同一の実座標（同じ地点を指す）になるという、
    destination_pointの性質と一致させるための構造。座標が同じ地点に別々のNodeを
    重複して作ると、最近接ノード探索が別方位のNodeへ誤ってスナップしうる
    （実データでは実在の交差点1つに収束するため起きない問題）。

    `skip_bearings`に含めた方位は、その方位専用のアーク・起点側スポークを作らない
    （＝その方位に限って経路探索が失敗する状況を再現する）。
    """
    radius_km = distance_km * RADIUS_RATIO
    nodes = {"origin": Node(node_id="origin", latitude=origin.latitude, longitude=origin.longitude)}
    edges: dict[str, DirectedEdge] = {}

    spoke_coords = {bearing: destination_point(origin, bearing, radius_km) for bearing in DIRECTIONS_DEG}
    for bearing, coord in spoke_coords.items():
        nodes[f"p-{bearing}"] = Node(node_id=f"p-{bearing}", latitude=coord.latitude, longitude=coord.longitude)

    for bearing in DIRECTIONS_DEG:
        if bearing in skip_bearings:
            continue  # このWayをつながないことで、経路探索が失敗する方位を作る

        next_bearing = (bearing + 45) % 360
        node_a_id, node_b_id = f"p-{bearing}", f"p-{next_bearing}"
        coord_a, coord_b = spoke_coords[bearing], spoke_coords[next_bearing]

        edges[f"e-{bearing}-spoke1"] = _edge(f"e-{bearing}-spoke1", "origin", node_a_id, origin, coord_a)
        edges[f"e-{bearing}-arc"] = _edge(f"e-{bearing}-arc", node_a_id, node_b_id, coord_a, coord_b)
        edges[f"e-{bearing}-spoke2"] = _edge(f"e-{bearing}-spoke2", node_b_id, "origin", coord_b, origin)

    return RoadGraph(graph_version="test", nodes=nodes, edges=edges)


class FakeGraphService:
    def __init__(
        self,
        graph: RoadGraph | None,
        surface_attributes: dict | None = None,
        stop_counts: dict | None = None,
        stop_data_available: bool = True,
        way_tags: dict | None = None,
        intersection_counts: dict | None = None,
        accident_counts: dict | None = None,
        accident_years_covered: int = 0,
        designated_edge_ids: set | None = None,
        elevation_attributes_for_search: dict | None = None,
    ):
        self._graph = graph
        self._surface_attributes = surface_attributes or {}
        self._stop_counts = stop_counts or {}
        self._way_tags = way_tags or {}
        self._intersection_counts = intersection_counts or {}
        self._accident_counts = accident_counts or {}
        self._accident_years_covered = accident_years_covered
        self._designated_edge_ids = designated_edge_ids or set()
        # 改善計画T218a: 探索コスト（prepare）が読む事前計算済みgradient。既定{}は
        # 「バッチ未実行のEdge」を模す（gradient軸のみデータ無し扱い、他軸の評価は継続）。
        self._elevation_attributes_for_search = elevation_attributes_for_search or {}
        # 静的道路属性P1。Falseは「repository未注入でデータ自体を取得できない」を模す
        # （GraphService.get_stop_poi_counts(repository=None)と同じ{}を返す）。Trueは
        # 「repository注入済み、指定edge_idは（0件含め）必ず実測値を持つ」を模す
        # （AttributeRepository.get_stop_poi_countsの実挙動、テストで未設定のedge_idは0扱い）。
        self._stop_data_available = stop_data_available
        self.call_count = 0

    async def get_or_build_graph_with_attributes(self, bbox, *, lean: bool = False):
        # 改善計画T218: lean引数はテストのfakeでは無視してよい（フェイクグラフは
        # 元々geometryを持つ実体をそのまま返すため、lean=Trueでも挙動は変わらない）。
        self.call_count += 1
        if self._graph is None:
            return None
        return self._graph, self._surface_attributes

    async def get_edges_with_geometry(self, edge_ids):
        # 改善計画T218: フェイクグラフのEdgeは元々実ジオメトリを持つため、常に空辞書を
        # 返す（呼び出し元trace_loopはcontext.graph.edges[edge_id]へフォールバックする、
        # Overpass経由構築時と同じ挙動）。
        return {}

    async def get_edge_attribute_counts(self, edge_ids):
        # 改善計画T218: get_stop_poi_counts（旧実装）と同じ「stop_data_available=Falseは
        # repository未注入を模す」規約を踏襲する。edge_attribute_countsは一度バックフィル
        # されれば対象の全Edgeに行を持つ（0件はゼロとして明示的に持つ、行自体が
        # 欠けることはない）ため、get_stop_poi_countsと同じ「指定edge_idは全件存在」の形。
        if not self._stop_data_available:
            return {}
        return {
            edge_id: EdgeAttributeCounts(
                accident_count=self._accident_counts.get(edge_id, 0),
                stop_count=self._stop_counts.get(edge_id, 0),
                intersection_count=self._intersection_counts.get(edge_id, 0),
            )
            for edge_id in edge_ids
        }

    async def get_stop_poi_counts(self, edge_ids):
        if not self._stop_data_available:
            return {}
        return {edge_id: self._stop_counts.get(edge_id, 0) for edge_id in edge_ids}

    async def get_way_tags(self, edge_ids):
        # 静的道路属性P1残り。既定は{}（未設定時は「repository未注入」相当で既存
        # アサーションに影響しない）。way_tagsに指定されたedge_idのみ実値を返す。
        return {edge_id: self._way_tags[edge_id] for edge_id in edge_ids if edge_id in self._way_tags}

    async def get_intersection_counts(self, edge_ids):
        # 同上（intersectionDensity）。
        return {edge_id: self._intersection_counts[edge_id] for edge_id in edge_ids if edge_id in self._intersection_counts}

    async def get_accident_counts(self, edge_ids):
        # 同上（事故密度、外部静的データソース T50残作業）。
        return {edge_id: self._accident_counts[edge_id] for edge_id in edge_ids if edge_id in self._accident_counts}

    async def get_accident_years_covered(self):
        return self._accident_years_covered

    async def get_designated_edge_ids(self, edge_ids):
        # 指定路線コンフレーション機構（外部静的データソース T51）。
        return {edge_id for edge_id in edge_ids if edge_id in self._designated_edge_ids}

    async def get_elevation_attributes(self, edge_ids):
        # 改善計画T218a: 探索コストが読む事前計算済みgradient（get_stop_poi_counts等と
        # 同じ「指定edge_idのうち持っているものだけ返す」パターン）。
        return {
            edge_id: self._elevation_attributes_for_search[edge_id]
            for edge_id in edge_ids
            if edge_id in self._elevation_attributes_for_search
        }


class FakeElevationAttributeService:
    def __init__(self, attributes: dict | None = None):
        self._attributes = attributes or {}
        self.graphs_queried: list[RoadGraph] = []

    async def get_attributes_for_graph(self, graph: RoadGraph):
        self.graphs_queried.append(graph)
        return self._attributes


class FakeWeatherService:
    def __init__(self, conditions: WeatherConditions | None = None):
        self._conditions = conditions

    async def get_conditions(self, point: Coordinates, at=None):
        return self._conditions


def make_generator(
    graph: RoadGraph | None,
    *,
    elevation_attributes: dict | None = None,
    surface_attributes: dict | None = None,
    stop_counts: dict | None = None,
    stop_data_available: bool = True,
    way_tags: dict | None = None,
    intersection_counts: dict | None = None,
    accident_counts: dict | None = None,
    accident_years_covered: int = 0,
    designated_edge_ids: set | None = None,
    wind: WeatherConditions | None = None,
    route_preference: RoutePreference | None = None,
    elevation_attributes_for_search: dict | None = None,
    penalty_strength: float = 1.0,
    max_average_grade_percent: float | None = None,
) -> tuple[RouteGenerator, FakeGraphService, FakeElevationAttributeService]:
    graph_service = FakeGraphService(
        graph, surface_attributes, stop_counts, stop_data_available, way_tags, intersection_counts,
        accident_counts, accident_years_covered, designated_edge_ids, elevation_attributes_for_search,
    )
    elevation_service = FakeElevationAttributeService(elevation_attributes)
    preference = route_preference or RoutePreference()
    engine = RoadGraphEngine(
        graph_service=graph_service,
        elevation_attribute_service=elevation_service,
        evaluation_service=EvaluationService(preference),
        weather_service=FakeWeatherService(wind),
        route_preference=preference,
        penalty_strength=penalty_strength,
        max_average_grade_percent=max_average_grade_percent,
    )
    generator = RouteGenerator(engine, make_route_scorer())
    return generator, graph_service, elevation_service


async def test_generate_loops_returns_one_candidate_per_reachable_direction():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert len(candidates) == len(DIRECTIONS_DEG)
    assert {c.id for c in candidates} == {f"route-{b:03d}" for b in DIRECTIONS_DEG}
    assert all(c.distance_km > 0 for c in candidates)
    assert all(c.geometry["type"] == "LineString" for c in candidates)


async def test_generate_loops_skips_directions_with_no_path():
    graph = build_loop_graph(ORIGIN, distance_km=30.0, skip_bearings={0, 180})
    generator, _, _ = make_generator(graph)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert len(candidates) == len(DIRECTIONS_DEG) - 2
    assert "route-000" not in [c.id for c in candidates]
    assert "route-180" not in [c.id for c in candidates]


async def test_generate_loops_returns_empty_list_when_no_road_graph():
    generator, graph_service, _ = make_generator(graph=None)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert candidates == []


async def test_generate_loops_fetches_road_graph_only_once_for_all_directions():
    # 実機検証で、方位ごとに個別にOverpassへ問い合わせる設計が公開インスタンスに
    # よって拒否される事象を確認したため、8方位分をまとめた単一のbboxで1回だけ取得する
    # 設計に変更した（road_graph_engine.pyのモジュールdocstring参照）。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, graph_service, _ = make_generator(graph)

    await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert graph_service.call_count == 1


async def test_generate_loops_filters_candidates_outside_distance_tolerance():
    # bearing=0の起点→p-0スポークだけを、大きく迂回するdetourノード経由に置き換えて距離を伸ばす。
    # 他の方位のスポーク・アークはp-0を終点として参照するのみ（origin→p-0とは別のEdge）
    # なので、この置き換えの影響はbearing=0だけに閉じる。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    detour_point = destination_point(ORIGIN, 0, 50.0)  # 大きく迂回する経由地
    node_a_id = "p-0"
    origin_node = graph.nodes["origin"]
    a_node = graph.nodes[node_a_id]
    origin_coord = Coordinates(latitude=origin_node.latitude, longitude=origin_node.longitude)
    a_coord = Coordinates(latitude=a_node.latitude, longitude=a_node.longitude)

    new_nodes = dict(graph.nodes)
    new_nodes["detour"] = Node(node_id="detour", latitude=detour_point.latitude, longitude=detour_point.longitude)
    new_edges = dict(graph.edges)
    del new_edges["e-0-spoke1"]  # 直行するorigin→p-0を消し、大回りするorigin→detour→p-0へ置き換える
    new_edges["detour-1"] = _edge("detour-1", "origin", "detour", origin_coord, detour_point)
    new_edges["detour-2"] = _edge("detour-2", "detour", node_a_id, detour_point, a_coord)
    graph = RoadGraph(graph_version="test", nodes=new_nodes, edges=new_edges)

    generator, _, _ = make_generator(graph)
    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert "route-000" not in [c.id for c in candidates]
    assert len(candidates) == len(DIRECTIONS_DEG) - 1


async def test_candidate_aggregates_elevation_from_path_edges():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    edge_ids = [eid for eid in graph.edges if eid.startswith("e-0-")]
    elevation_attributes = {
        edge_ids[0]: ElevationAttribute(
            edge_id=edge_ids[0], start_elevation_m=10.0, end_elevation_m=30.0,
            elevation_gain_m=20.0, elevation_loss_m=0.0, average_grade=2.0, max_grade=3.0, min_grade=1.0,
            data_source="test", calculated_at="t",
        ),
        edge_ids[1]: ElevationAttribute(
            edge_id=edge_ids[1], start_elevation_m=30.0, end_elevation_m=15.0,
            elevation_gain_m=0.0, elevation_loss_m=15.0, average_grade=-4.0, max_grade=-1.0, min_grade=-5.0,
            data_source="test", calculated_at="t",
        ),
    }
    generator, _, elevation_service = make_generator(graph, elevation_attributes=elevation_attributes)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)
    candidate = next(c for c in candidates if c.id == "route-000")

    assert candidate.elevation_gain_m == 20.0
    assert candidate.min_elevation_m == 10.0
    assert candidate.max_elevation_m == 30.0
    assert candidate.max_gradient_percent == 5.0  # abs(min_grade)=5.0が最大


async def test_elevation_attribute_service_is_queried_only_with_path_edges_not_whole_graph():
    # 実機検証で、経路確定前のRoad Graph全体に対して標高を取得しようとすると
    # 非現実的な所要時間になることが判明したため、経路確定後・距離フィルタ通過後に
    # そのEdgeだけへ絞って取得する設計にした（road_graph_engine.pyのモジュールdocstring参照）。
    # ここでは「渡されるgraphがフルグラフより明らかに小さい（＝1候補分の経路程度）」
    # ことを確認する回帰テスト。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, elevation_service = make_generator(graph)

    await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert len(elevation_service.graphs_queried) == len(DIRECTIONS_DEG)  # 方位ごとに1回ずつ
    for queried_graph in elevation_service.graphs_queried:
        assert len(queried_graph.edges) == 3  # 1候補=3区間分のみ（フルグラフの24区間ではない）
        assert len(queried_graph.edges) < len(graph.edges)


async def test_elevation_is_not_fetched_for_candidates_rejected_by_distance_filter():
    # 距離フィルタで棄却された候補にはGSI問い合わせ（標高取得）を行わない
    # （評価は距離フィルタ通過後の候補だけに行う、RouteGenerator/evaluate_loopsの分割参照）。
    graph = build_loop_graph(ORIGIN, distance_km=30.0, skip_bearings=set())
    generator, _, elevation_service = make_generator(graph)

    # 許容差を極端に狭くして全候補を棄却させる
    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=0.001)

    assert candidates == []
    assert elevation_service.graphs_queried == []


async def test_candidate_aggregates_road_score_from_path_edges():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    edge_ids = sorted(eid for eid in graph.edges if eid.startswith("e-0-"))
    surface_attributes = {edge_ids[0]: "asphalt", edge_ids[1]: "gravel"}
    generator, _, _ = make_generator(graph, surface_attributes=surface_attributes)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)
    candidate = next(c for c in candidates if c.id == "route-000")

    assert candidate.road_score is not None
    assert 0.0 <= candidate.road_score <= 100.0


async def test_candidate_aggregates_stop_density_from_path_edges():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    edge_ids = sorted(eid for eid in graph.edges if eid.startswith("e-0-"))
    stop_counts = {edge_ids[0]: 3}
    generator, _, _ = make_generator(graph, stop_counts=stop_counts)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)
    candidate = next(c for c in candidates if c.id == "route-000")

    assert candidate.stop_density is not None
    assert candidate.stop_density > 0.0
    segment_with_stops = next(s for s in candidate.segments if s.stop_difficulty is not None and s.stop_difficulty > 0)
    assert segment_with_stops.difficulty is not None


async def test_candidate_stop_density_is_zero_without_any_stop_pois():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph)  # stop_counts未指定（=repository注入済み・実測0件）

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)
    candidate = next(c for c in candidates if c.id == "route-000")

    assert candidate.stop_density == 0.0


async def test_candidate_stop_density_is_none_when_data_unavailable():
    # repository未注入等でstop_poiデータ自体を取得できない場合は「実測0件」とは区別してNone
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph, stop_data_available=False)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)
    candidate = next(c for c in candidates if c.id == "route-000")

    assert candidate.stop_density is None
    assert all(s.stop_difficulty is None for s in candidate.segments)


async def test_candidate_reflects_bicycle_infra_from_way_tags():
    # 静的道路属性P1残り。way_tagsが取得できた区間は自転車インフラの生値・ルート集約値
    # （bicycle_infra_score、一次属性由来の表示用統計）が反映される（このテストの
    # build_loop_graphはEdge.highwayを持たないため、highway必須の車ストレスはNoneのまま。
    # highway非依存のbicycle_infraだけ検証する）。改善計画T138で自転車インフラの
    # 独立難易度軸（infra_difficulty）は廃止し車ストレス側へ統合済みのため、ここでは検証しない。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    edge_ids = sorted(eid for eid in graph.edges if eid.startswith("e-0-"))
    way_tags = {edge_ids[0]: {"cycleway": "track"}}
    generator, _, _ = make_generator(graph, way_tags=way_tags)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)
    candidate = next(c for c in candidates if c.id == "route-000")

    assert candidate.bicycle_infra_score is not None
    segment_with_track = next(s for s in candidate.segments if s.bicycle_infra == "separated")
    assert segment_with_track is not None


async def test_candidate_aggregates_intersection_density_from_path_edges():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    edge_ids = sorted(eid for eid in graph.edges if eid.startswith("e-0-"))
    intersection_counts = {edge_ids[0]: 2}
    generator, _, _ = make_generator(graph, intersection_counts=intersection_counts)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)
    candidate = next(c for c in candidates if c.id == "route-000")

    assert candidate.intersection_density is not None
    assert candidate.intersection_density > 0.0
    # 改善計画T149: 交差点密度は独立軸を持たずstop_difficulty側へ低い重みで吸収される
    # （旧intersection_difficultyは廃止）。
    segment_with_intersections = next(
        s for s in candidate.segments if s.stop_difficulty is not None and s.stop_difficulty > 0
    )
    assert segment_with_intersections.difficulty is not None


async def test_candidate_aggregates_accident_density_from_path_edges():
    # 外部静的データソース T50残作業（8軸目）。事故密度は件/(km・年)のため
    # accident_years_coveredも指定する。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    edge_ids = sorted(eid for eid in graph.edges if eid.startswith("e-0-"))
    accident_counts = {edge_ids[0]: 2}
    generator, _, _ = make_generator(graph, accident_counts=accident_counts, accident_years_covered=2)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)
    candidate = next(c for c in candidates if c.id == "route-000")

    assert candidate.accident_density is not None
    assert candidate.accident_density > 0.0
    segment_with_accidents = next(
        s for s in candidate.segments if s.accident_difficulty is not None and s.accident_difficulty > 0
    )
    assert segment_with_accidents.difficulty is not None


async def test_candidate_accident_density_is_none_when_years_covered_is_zero():
    # accident_years_covered=0（事故データ未取込）は、件数があっても密度を算出できないためNone。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    edge_ids = sorted(eid for eid in graph.edges if eid.startswith("e-0-"))
    accident_counts = {edge_ids[0]: 2}
    generator, _, _ = make_generator(graph, accident_counts=accident_counts, accident_years_covered=0)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)
    candidate = next(c for c in candidates if c.id == "route-000")

    assert candidate.accident_density is None


async def test_candidate_aggregates_wind_score_when_weather_available():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    wind = WeatherConditions(
        temperature_c=20.0, apparent_temperature_c=None, wind_speed_ms=5.0, wind_direction_deg=0.0,
        wind_direction_label="北", wind_gusts_ms=None, precipitation_probability_percent=None,
        precipitation_mm=None, uv_index=None, observed_at="t",
    )
    generator, _, _ = make_generator(graph, wind=wind)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert all(c.wind_score is not None for c in candidates)


async def test_candidate_wind_score_is_none_without_weather():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph, wind=None)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert all(c.wind_score is None for c in candidates)


async def test_candidate_segments_cover_every_edge_on_the_path():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)
    candidate = next(c for c in candidates if c.id == "route-000")

    assert candidate.segments is not None
    assert len(candidate.segments) == 3  # origin→a→b→originの3区間
    assert candidate.segments[0].cumulative_distance_km == 0.0
    total_segment_distance = sum(s.distance_km for s in candidate.segments)
    assert abs(total_segment_distance - candidate.distance_km) < 0.1


async def test_candidate_segments_carry_edge_geometry_for_map_drawing():
    # 区間の色分けを道路形状に沿って描くため、各区間はEdgeの形状点列をGeoJSON
    # LineString（[lon, lat]順）として持つ（研究IF改善: 区間表示の道なり化）。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)
    candidate = next(c for c in candidates if c.id == "route-000")

    for seg in candidate.segments:
        assert seg.geometry is not None
        assert seg.geometry["type"] == "LineString"
        coordinates = seg.geometry["coordinates"]
        assert len(coordinates) >= 2
        # 形状の端点はstart/endフィールドと一致する（GeoJSONは[lon, lat]順）
        assert coordinates[0] == [seg.start_longitude, seg.start_latitude]
        assert coordinates[-1] == [seg.end_longitude, seg.end_latitude]


async def test_total_score_is_populated_and_candidates_sorted_descending():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert all(c.total_score is not None for c in candidates)
    scores = [c.total_score for c in candidates]
    assert scores == sorted(scores, reverse=True)


async def test_engine_name_is_road_graph():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph)

    assert generator.engine_name == "road_graph"


async def test_build_segment_details_uses_compute_edge_axis_scores(monkeypatch):
    # 改善計画T143: 区間表示（_build_segment_details）は、探索コスト
    # （EvaluationService.evaluate_graph経由のcompute_edge_cost）と同じ
    # compute_edge_axis_scores（T142）を通る。以前はevaluate_axis_difficultiesを
    # 独立に再計算しており、二次の計算式が表示・探索コストの2箇所に別実装されていた
    # （非DRY構造）。本物へ委譲しつつ呼び出しを検知するスパイで、_build_segment_details
    # が実際にこの共通関数を経由することを確認する。
    calls = []
    original = road_graph_engine.compute_edge_axis_scores

    def spy(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(road_graph_engine, "compute_edge_axis_scores", spy)

    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert len(calls) > 0


async def test_build_segment_details_calls_car_stress_level_once_per_edge(monkeypatch):
    # 改善計画T153（統合レビュー2026-08-19 overall F-1）: _build_segment_detailsは表示用の
    # 生値car_stressをcar_stress_level()で計算したうえで、同じ値をcompute_edge_axis_scores
    # （T143で導入）へcar_stress_level_valueとして渡す設計になっている。以前はこの受け渡しが
    # 無く、compute_edge_axis_scores内部でcar_stress_level()が再計算されていた
    # （road_graph_engine.car_stress_levelとevaluation.car_stress_levelは
    # `from ... import car_stress_level`によりモジュールごとに別々の名前束縛を持つため、
    # 片方だけをmonkeypatchする回帰テストでは検知できない死角があった——本テストは
    # 両方の束縛にスパイを仕込むことでこの死角を塞ぐ）。
    #
    # _build_segment_detailsを直接呼ぶ（generate_loops経由だとRoadGraphEngine.prepareが
    # 探索コスト用にグラフ全Edgeへevaluate_graph→car_stress_levelを呼ぶため、区間数との
    # 単純な1:1比較ができなくなる）。
    calls = []
    original = road_graph_engine.car_stress_level

    def spy(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(road_graph_engine, "car_stress_level", spy)
    monkeypatch.setattr(evaluation, "car_stress_level", spy)

    node_a = Node(node_id="a", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude)
    node_b = Node(node_id="b", latitude=ORIGIN.latitude + 0.01, longitude=ORIGIN.longitude)
    node_c = Node(node_id="c", latitude=ORIGIN.latitude + 0.02, longitude=ORIGIN.longitude)
    edges = [
        _edge("e1", "a", "b", Coordinates(latitude=node_a.latitude, longitude=node_a.longitude),
              Coordinates(latitude=node_b.latitude, longitude=node_b.longitude), highway="residential"),
        _edge("e2", "b", "c", Coordinates(latitude=node_b.latitude, longitude=node_b.longitude),
              Coordinates(latitude=node_c.latitude, longitude=node_c.longitude), highway="residential"),
    ]
    way_tags = {edge.edge_id: {"highway": "residential"} for edge in edges}
    # graph=Noneでもmake_generatorは(Fake)GraphService付きのRoadGraphEngineを構築できる
    # （prepare()は呼ばず_build_segment_detailsを直接使うため、実際のgraph探索は不要）。
    generator, _, _ = make_generator(graph=None, way_tags=way_tags)
    engine = generator._engine
    context = road_graph_engine._RoadGraphContext(
        graph=RoadGraph(graph_version="test", nodes={n.node_id: n for n in (node_a, node_b, node_c)},
                         edges={e.edge_id: e for e in edges}),
        nx_graph=None,
        surface_attributes={},
        stop_counts={},
        way_tags=way_tags,
        intersection_counts={},
        accident_counts={},
        accident_years_covered=0,
        designated_edge_ids=set(),
        wind=None,
        origin_node="a",
        night_active=False,
    )

    segments = engine._build_segment_details(edges, {}, context, datetime.now(timezone.utc))

    assert len(segments) == len(edges)
    assert len(calls) == len(edges)




# 改善計画T173: night軸の動的化（prepare実行時点の起点が市民薄明の外かどうかで、
# 探索コスト全体へ適用するnight_weightを0/そのままに切り替える）。RoadGraphEngineは
# wind同様、探索中は到達時刻が未確定のためprepare実行時点を出発時刻の近似とする簡略化。
async def test_prepare_applies_night_weight_when_origin_is_in_civil_twilight_darkness():
    node_a = Node(node_id="a", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude)
    node_b = Node(node_id="b", latitude=ORIGIN.latitude + 0.01, longitude=ORIGIN.longitude)
    coord_b = Coordinates(latitude=node_b.latitude, longitude=node_b.longitude)
    edge = _edge("e1", "a", "b", ORIGIN, coord_b, highway="residential")
    graph = RoadGraph(graph_version="test", nodes={"a": node_a, "b": node_b}, edges={"e1": edge})
    # way_tags={}（litタグ無し）はnight_difficulty=50.0（test_night.py参照）。他の軸の重みを
    # 0にし、night_weightだけが探索コストへ効くようにする（差分をnight軸だけに起因させる）。
    preference = RoutePreference(
        elevation_weight=0.0, wind_weight=0.0, road_weight=0.0, stop_weight=0.0,
        car_stress_weight=0.0, accident_weight=0.0, night_weight=1.0,
    )
    generator, _, _ = make_generator(graph, way_tags={"e1": {}}, route_preference=preference)
    engine = generator._engine

    # 東京、2024-06-21 12:00 JST（明らかに昼）= UTC 03:00
    daytime = datetime(2024, 6, 21, 3, 0, tzinfo=timezone.utc)
    # 東京、2024-06-21 02:00 JST（明らかに夜）= UTC 2024-06-20 17:00
    nighttime = datetime(2024, 6, 20, 17, 0, tzinfo=timezone.utc)

    day_context = await engine.prepare(ORIGIN, radius_km=1.0, now=daytime)
    night_context = await engine.prepare(ORIGIN, radius_km=1.0, now=nighttime)

    assert day_context.night_active is False
    assert night_context.night_active is True

    day_cost = day_context.nx_graph["a"]["b"]["weight"]
    night_cost = night_context.nx_graph["a"]["b"]["weight"]
    # 日中はnight_weightが0倍されるため、他の軸の重みも全て0の本ケースではdistance_mそのもの
    # （難易度による割増なし）になるはず。夜間はnight_difficulty分の割増が乗る。
    assert night_cost > day_cost
    assert day_cost == pytest.approx(edge.distance_m, abs=0.1)


async def test_prepare_applies_precomputed_gradient_to_search_cost():
    # 改善計画T218a（T12 Stage 0.5）: prepareが事前計算済みのelevation_attributes
    # （GraphService.get_elevation_attributes、バッチ`precompute_elevation_attributes`が
    # 埋める想定）を探索コストへ組み込むことを確認する。
    node_a = Node(node_id="a", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude)
    node_b = Node(node_id="b", latitude=ORIGIN.latitude + 0.01, longitude=ORIGIN.longitude)
    coord_b = Coordinates(latitude=node_b.latitude, longitude=node_b.longitude)
    edge = _edge("e1", "a", "b", ORIGIN, coord_b, highway="residential")
    graph = RoadGraph(graph_version="test", nodes={"a": node_a, "b": node_b}, edges={"e1": edge})
    preference = RoutePreference(
        elevation_weight=1.0, wind_weight=0.0, road_weight=0.0, stop_weight=0.0,
        car_stress_weight=0.0, accident_weight=0.0, night_weight=0.0,
    )
    steep_climb = ElevationAttribute(
        edge_id="e1", average_grade=10.0, data_source="test", calculated_at="t"
    )

    flat_generator, _, _ = make_generator(graph, way_tags={"e1": {}}, route_preference=preference)
    steep_generator, _, _ = make_generator(
        graph, way_tags={"e1": {}}, route_preference=preference,
        elevation_attributes_for_search={"e1": steep_climb},
    )

    flat_context = await flat_generator._engine.prepare(ORIGIN, radius_km=1.0)
    steep_context = await steep_generator._engine.prepare(ORIGIN, radius_km=1.0)

    flat_cost = flat_context.nx_graph["a"]["b"]["weight"]
    steep_cost = steep_context.nx_graph["a"]["b"]["weight"]
    # 事前計算データが無い（{}のまま=バッチ未実行を模す）場合はgradient軸がデータ無し扱いで
    # 割増が乗らない。事前計算済みの急勾配が渡されるとgradient軸の割増がコストへ反映される。
    assert flat_cost == pytest.approx(edge.distance_m, abs=0.1)
    assert steep_cost > flat_cost


async def test_prepare_excludes_edge_exceeding_max_average_grade_percent_from_search_graph():
    # 改善計画T218a: 0次ハードフィルタの勾配しきい値がprepareの探索グラフ構築にも
    # 反映されることを確認する（nx_graphに該当Edgeが含まれなくなる）。
    node_a = Node(node_id="a", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude)
    node_b = Node(node_id="b", latitude=ORIGIN.latitude + 0.01, longitude=ORIGIN.longitude)
    coord_b = Coordinates(latitude=node_b.latitude, longitude=node_b.longitude)
    edge = _edge("e1", "a", "b", ORIGIN, coord_b, highway="residential")
    graph = RoadGraph(graph_version="test", nodes={"a": node_a, "b": node_b}, edges={"e1": edge})
    steep_climb = ElevationAttribute(edge_id="e1", average_grade=15.0, data_source="test", calculated_at="t")

    generator, _, _ = make_generator(
        graph, way_tags={"e1": {}},
        elevation_attributes_for_search={"e1": steep_climb},
        max_average_grade_percent=8.0,
    )

    context = await generator._engine.prepare(ORIGIN, radius_km=1.0)

    assert not context.nx_graph.has_edge("a", "b")


async def test_build_segment_details_night_difficulty_follows_context_night_active():
    node_a = Node(node_id="a", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude)
    node_b = Node(node_id="b", latitude=ORIGIN.latitude + 0.01, longitude=ORIGIN.longitude)
    coord_b = Coordinates(latitude=node_b.latitude, longitude=node_b.longitude)
    edge = _edge("e1", "a", "b", ORIGIN, coord_b, highway="residential")
    way_tags = {"e1": {}}
    preference = RoutePreference(
        elevation_weight=0.0, wind_weight=0.0, road_weight=0.0, stop_weight=0.0,
        car_stress_weight=0.0, accident_weight=0.0, night_weight=1.0,
    )
    generator, _, _ = make_generator(None, way_tags=way_tags, route_preference=preference)
    engine = generator._engine

    base_kwargs = dict(
        graph=RoadGraph(graph_version="test", nodes={"a": node_a, "b": node_b}, edges={"e1": edge}),
        nx_graph=None, surface_attributes={}, stop_counts={}, way_tags=way_tags,
        intersection_counts={}, accident_counts={}, accident_years_covered=0,
        designated_edge_ids=set(), wind=None, origin_node="a",
    )
    day_context = road_graph_engine._RoadGraphContext(**base_kwargs, night_active=False)
    night_context = road_graph_engine._RoadGraphContext(**base_kwargs, night_active=True)

    day_segments = engine._build_segment_details([edge], {}, day_context, datetime.now(timezone.utc))
    night_segments = engine._build_segment_details([edge], {}, night_context, datetime.now(timezone.utc))

    # night_weight=1.0のみ有効な本ケースでは、日中はcompositeを合成できる重みが1つも
    # 無くなり（他の軸は重み0）Noneに、夜間はnight_difficulty(50.0)そのものになる。
    assert day_segments[0].difficulty is None
    assert night_segments[0].difficulty == 50.0
