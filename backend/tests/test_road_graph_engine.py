"""RoadGraphEngine（Road Graph + rustworkx A*/Dijkstraエンジン、改善計画T529）のテスト。

RouteGenerator（戦略層）を通したエンドツーエンドで、エンジン固有の責務
（Road Graph取得が1回のみ・A*/Dijkstra経路・標高がパス上のEdgeだけに絞られること・
Edge単位の集計とsegments構築）を検証する。戦略側の責務（距離フィルタ・失敗スキップ等）は
test_route_generator.pyで検証済み。
"""

import math
from datetime import datetime, timezone

import numpy as np
import pytest

from app.domain.attributes import EdgeAttributeCounts, EdgeMaterialBundle, ElevationAttribute, SearchMaterials
from app.domain.errors import RoutingError
from app.domain.evaluation import (
    DynamicAxisRequestContext,
    RoutePreference,
    build_static_edge_score_matrix,
    compose_costs_from_axis_matrix,
    compute_hard_filter_excluded,
    evaluate_dynamic_axis_arrays,
)
from app.domain.geo import bearing_between, compass_label, haversine_distance_km
from app.domain.graph import DirectedEdge, LeanEdge, Node, RoadGraph
from app.domain.route import Coordinates, RouteCandidate, RouteSegmentDetail
from app.domain.routing import build_node_spatial_index
from app.domain.weather import WeatherConditions
from app.domain.wind import ASSUMED_SPEED_KMH, WindForecastSeries, kmh_to_ms
from app.infrastructure import search_graph_cache
from app.services import road_graph_engine
from app.services.road_graph_engine import RoadGraphEngine
from tests.geo_fixtures import destination_point
from app.services.route_generator import TURNAROUND_RADIUS_RATIO, RouteGenerator

# 改善計画T350: AXIS_DEFINITIONSのPython literal撤去に伴い、本ファイルが暗黙に前提とする
# 「car_stress/night等の実在axis_idを持つ一貫した軸システム」が必要（DBの現在値の検証が
# 目的ではない）。tests/conftest.pyのセッションスコープautouseフィクスチャが全テスト共通で
# 用意する（tests/realistic_axis_fixtures.py参照）。


@pytest.fixture(autouse=True)
def _clear_search_graph_cache():
    # 改善計画T537: search_graph_cache（探索用グラフ・索引のタイル集合キーLRU）は
    # プロセス内メモリのモジュールグローバルのため、テスト間で漏れないよう明示的に
    # クリアする（test_graph_service.pyのgraph_material_cacheクリアと同じ規約）。
    search_graph_cache.clear()
    yield
    search_graph_cache.clear()


ORIGIN = Coordinates(latitude=35.7597, longitude=139.7387)
# テスト用フィクスチャ（build_loop_graph）が折返し点を置く方位。方位は生成機構ではなく
# 候補を区別するラベルにしか使わない（改善計画T531）。
BEARINGS = [0, 45, 90, 135, 180, 225, 270, 315]


def _lazy_edge_cost(engine, context, from_node_id: str, to_node_id: str) -> float:
    """改善計画T529→T536: 旧`_sparse_edge_weight`（scipy版、事前計算済みcostを行列から
    直接読む）の置き換え。T536以降はコストが`prepare()`実行時点で`context.cost_list`
    （`context.lazy_graph.edge_ids`と同じ行順）へbbox全体ぶん既に合成済みのため、
    そのままlistインデックスで読む（`engine`引数は旧シグネチャとの互換のため残すが
    未使用）。
    """
    i = context.lazy_graph.node_id_to_index[from_node_id]
    j = context.lazy_graph.node_id_to_index[to_node_id]
    edge_index = context.lazy_graph.edge_index_by_node_pair[(i, j)]
    return context.legs[0].cost_list[edge_index]


def _lazy_edge_is_allowed(engine, context, from_node_id: str, to_node_id: str) -> bool:
    """改善計画T529→T536: 旧`_sparse_has_edge`（scipy版、Hard Constraint除外Edgeは
    グラフ構造自体から除外されていた）の置き換え。lazy評価の`LazyRoadGraph`はトポロジ
    のみでHard Constraintを知らないため全Edgeを含む——除外は`context.cost_list`が
    `math.inf`を持つことで表現される。そのため「Edgeが存在し、かつコストが有限」を
    「除外されていない」の判定条件にする。
    """
    i = context.lazy_graph.node_id_to_index.get(from_node_id)
    j = context.lazy_graph.node_id_to_index.get(to_node_id)
    if i is None or j is None:
        return False
    edge_index = context.lazy_graph.edge_index_by_node_pair.get((i, j))
    if edge_index is None:
        return False
    return math.isfinite(context.legs[0].cost_list[edge_index])


def _edge(edge_id: str, from_id: str, to_id: str, from_coord: Coordinates, to_coord: Coordinates, **overrides) -> DirectedEdge:
    # 改善計画T218: bearing_degはbuild_road_graphと同じくfrom_coord→to_coordの実際の
    # 方位角から算出する（compute_dynamic_edge_materialsがgeometryではなくこの値を直接使うため、
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


def build_loop_graph(
    origin: Coordinates, distance_km: float, *, skip_bearings: set[int] = frozenset(), highway: str | None = None
) -> RoadGraph:
    """フロンティア方式（改善計画T531）向けの「車輪」状Road Graph。各方位bearingについて、
    起点から目標距離の半分（R）の位置に折返し点`p-{bearing}`を置き、起点と`p-{bearing}`を
    結ぶ道を2本用意する（いずれも双方向）:

    - スポーク `e-{b}-spoke1`（起点→p、長さR）と逆方向 `e-{b}-spoke1-rev`
    - 迂回路 `e-{b}-alt1`（p→`m-{b}`）・`e-{b}-alt2`（m→起点）と各逆方向（`-rev`）。
      `m-{b}`は方位b+12°・距離R/2の点で、迂回路の全長はRよりわずかに長い（約1.02R）

    一対全木では`p-{b}`への往路は最短のスポークになり、往路の実距離RはリングD/2±tol/2に
    入る（`m-{b}`は約R/2で入らない）。復路はretraceペナルティによりスポークの逆走ではなく
    迂回路を選ぶため、各方位の周回は「spoke1→alt1→alt2」の3Edge・約2.02R（≒目標距離）になる。
    `skip_bearings`の方位は道を作らない（折返し点に到達できない）。`highway`を指定すると
    全Edgeへ同じhighway種別を付ける（材料の欠損ではなく「インフラ無し」として評価させたい
    テスト向け）。
    """
    radius_km = distance_km / 2
    nodes: dict[str, Node] = {"origin": Node(node_id="origin", latitude=origin.latitude, longitude=origin.longitude)}
    edges: dict[str, DirectedEdge] = {}
    overrides = {"highway": highway} if highway is not None else {}
    for bearing in BEARINGS:
        tip = destination_point(origin, bearing, radius_km)
        mid = destination_point(origin, (bearing + 12) % 360, radius_km / 2)
        nodes[f"p-{bearing}"] = Node(node_id=f"p-{bearing}", latitude=tip.latitude, longitude=tip.longitude)
        nodes[f"m-{bearing}"] = Node(node_id=f"m-{bearing}", latitude=mid.latitude, longitude=mid.longitude)
        if bearing in skip_bearings:
            continue
        tip_id, mid_id = f"p-{bearing}", f"m-{bearing}"
        forward = [
            (f"e-{bearing}-spoke1", "origin", tip_id, origin, tip),
            (f"e-{bearing}-alt1", tip_id, mid_id, tip, mid),
            (f"e-{bearing}-alt2", mid_id, "origin", mid, origin),
        ]
        for edge_id, from_id, to_id, from_coord, to_coord in forward:
            edges[edge_id] = _edge(edge_id, from_id, to_id, from_coord, to_coord, **overrides)
        for edge_id, from_id, to_id, from_coord, to_coord in forward:
            edges[f"{edge_id}-rev"] = _edge(f"{edge_id}-rev", to_id, from_id, to_coord, from_coord, **overrides)
    return RoadGraph(graph_version="test", nodes=nodes, edges=edges)


def _candidate_for_bearing(candidates: list[RouteCandidate], bearing: int) -> RouteCandidate:
    """方位ラベルで候補を引く（改善計画T531: idは最終順位で振り直されるため方位からは引けない）。"""
    return next(c for c in candidates if c.direction_label == compass_label(bearing))

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
        edges_with_geometry: dict | None = None,
        tile_set: frozenset[tuple[int, int, int]] | None = None,
    ):
        self._graph = graph
        # 改善計画T537: search_graph_cache（探索用グラフ・索引のタイル集合キーLRU）の
        # 挙動を検証するテスト専用。既定None（このfake自体はタイルキャッシュを持たない、
        # 通常のテストは従来どおりキャッシュを経由せず毎回構築する）で、指定した場合のみ
        # get_search_materials_for_bboxの戻り値3つ目に使う。
        self._tile_set = tile_set
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
        # 改善計画T218の主経路（hydrated優先）を検証するためのフェイクDB取得結果。既定{}は
        # 従来どおり「常に空辞書」（呼び出し元trace_loop/preview_segmentがcontext.graph.edges
        # ［or search.graph.edges］へフォールバックする、防御的フォールバック側のみが動く）。
        # テスト側でedge_idごとにDirectedEdgeをセットした場合のみ、そのedge_idに対して
        # 非空の結果を返す（主経路＝hydrated優先を検証できるようにする）。
        self._edges_with_geometry = edges_with_geometry or {}
        # 静的道路属性P1。Falseは「repository未注入でデータ自体を取得できない」を模す
        # （get_edge_attribute_counts(repository=None)と同じ{}を返す）。Trueは
        # 「repository注入済み、指定edge_idは（0件含め）必ず実測値を持つ」を模す
        # （AttributeRepository.get_edge_attribute_countsの実挙動、テストで未設定のedge_idは0扱い）。
        self._stop_data_available = stop_data_available
        self.call_count = 0
        self.last_bbox = None
        # 改善計画T531: get_edges_with_geometryへ渡されたedge_id列の記録（距離フィルタ通過後の
        # 候補ぶんだけを1回で取得することの検証用）。
        self.geometry_requests: list[list[str]] = []

    async def get_or_build_graph_with_attributes(self, bbox):
        self.call_count += 1
        if self._graph is None:
            return None
        return self._graph, self._surface_attributes

    async def get_search_materials_for_bbox(self, bbox):
        # 改善計画T219→T536→T537: prepareが呼ぶ統合メソッドのfake。既存の個別fakeメソッド
        # （get_edge_attribute_counts等）を素材の出所として使い、二重にロジックを
        # 持たない（本物のGraphServiceがタイルキャッシュ経由で組み立てるのと同じ
        # 中身になることをテストの他アサーション側は期待していないため、call_count計測
        # 目的のget_or_build_graph_with_attributesを呼ぶだけでよい）。T536以降は
        # `StaticEdgeScoreMatrix`（build_static_edge_score_matrix、本物と同じ実装）も
        # あわせて返す——このfake自体はタイル単位キャッシュを持たない（呼ばれるたびに
        # 実データから新規構築する）。改善計画T537: 戻り値3つ目のタイル集合は常にNone
        # （このfakeは「タイルキャッシュをそのまま結合したgraph」という前提を満たさない
        # ため、search_graph_cache経由のキャッシュは常にバイパスされる。タイル集合を
        # 実際に持つ経路の検証はtest_graph_service.py・本ファイルのFakeGraphServiceWithTileSet
        # [search_graph_cache関連テスト]で行う）。
        self.last_bbox = bbox
        built = await self.get_or_build_graph_with_attributes(bbox)
        if built is None:
            return None
        graph, surface_attributes = built
        edge_ids = list(graph.edges.keys())
        edge_attribute_counts = await self.get_edge_attribute_counts(edge_ids)
        way_tags = await self.get_way_tags(edge_ids)
        elevation_attributes = await self.get_elevation_attributes(edge_ids)
        designated_edge_ids = await self.get_designated_edge_ids(edge_ids)
        materials = {
            edge_id: EdgeMaterialBundle(
                surface=surface_attributes.get(edge_id),
                way_tags=way_tags.get(edge_id, {}),
                attribute_counts=edge_attribute_counts.get(edge_id),
                elevation_attribute=elevation_attributes.get(edge_id),
                is_designated=edge_id in designated_edge_ids,
            )
            for edge_id in edge_ids
        }
        score_matrix = build_static_edge_score_matrix(graph, materials, self._accident_years_covered)
        return SearchMaterials(graph=graph, materials=materials), score_matrix, self._tile_set

    async def get_edges_with_geometry(self, edge_ids):
        # 主経路（hydrated優先、road_graph_engine.py:341,386の`hydrated.get(edge_id) or
        # context.graph.edges[edge_id]`のor左辺）。既定{}は「未セット」を模し、これまでどおり
        # 空辞書を返す（呼び出し元trace_loopはcontext.graph.edges[edge_id]へフォールバックする、
        # Overpass経由構築時と同じ挙動＝or右辺のみが動く防御的フォールバック）。
        # edges_with_geometryにセットされたedge_idのみ、その値を返す（本物のRoadGraphRepository
        # と同じ「指定edge_idのうち持っているものだけ返す」規約）。
        self.geometry_requests.append(list(edge_ids))
        return {edge_id: self._edges_with_geometry[edge_id] for edge_id in edge_ids if edge_id in self._edges_with_geometry}

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

    async def get_way_tags(self, edge_ids):
        # 静的道路属性P1残り。既定は{}（未設定時は「repository未注入」相当で既存
        # アサーションに影響しない）。way_tagsに指定されたedge_idのみ実値を返す。
        return {edge_id: self._way_tags[edge_id] for edge_id in edge_ids if edge_id in self._way_tags}

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
    def __init__(self, conditions: WeatherConditions | None = None, wind_series: WindForecastSeries | None = None):
        self._conditions = conditions
        self._wind_series = wind_series

    async def get_conditions(self, point: Coordinates, at=None):
        return self._conditions

    async def get_wind_forecast_series(self, point: Coordinates):
        return self._wind_series


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
    weather: WeatherConditions | None = None,
    route_preference: RoutePreference | None = None,
    elevation_attributes_for_search: dict | None = None,
    penalty_strength: float = 1.0,
    max_average_grade_percent: float | None = None,
    hard_filters: frozenset[str] | None = None,
    edges_with_geometry: dict | None = None,
    tile_set: frozenset[tuple[int, int, int]] | None = None,
    wind_series: WindForecastSeries | None = None,
    assumed_speed_kmh: float = ASSUMED_SPEED_KMH,
    lens_axis_id: str | None = None,
) -> tuple[RouteGenerator, FakeGraphService, FakeElevationAttributeService]:
    graph_service = FakeGraphService(
        graph, surface_attributes, stop_counts, stop_data_available, way_tags, intersection_counts,
        accident_counts, accident_years_covered, designated_edge_ids, elevation_attributes_for_search,
        edges_with_geometry, tile_set,
    )
    elevation_service = FakeElevationAttributeService(elevation_attributes)
    preference = route_preference or RoutePreference()
    engine = RoadGraphEngine(
        graph_service=graph_service,
        elevation_attribute_service=elevation_service,
        weather_service=FakeWeatherService(weather, wind_series),
        route_preference=preference,
        penalty_strength=penalty_strength,
        max_average_grade_percent=max_average_grade_percent,
        hard_filters=hard_filters,
        assumed_speed_kmh=assumed_speed_kmh,
        lens_axis_id=lens_axis_id,
    )
    generator = RouteGenerator(engine)
    return generator, graph_service, elevation_service


async def test_generate_loops_returns_one_candidate_per_reachable_direction():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert len(candidates) == len(BEARINGS)
    assert [c.id for c in candidates] == [f"route-{i:02d}" for i in range(len(BEARINGS))]
    assert {c.direction_label for c in candidates} == {compass_label(b) for b in BEARINGS}
    assert all(c.distance_km > 0 for c in candidates)
    assert all(c.geometry["type"] == "LineString" for c in candidates)


async def test_generate_loops_skips_directions_with_no_path():
    graph = build_loop_graph(ORIGIN, distance_km=30.0, skip_bearings={0, 180})
    generator, _, _ = make_generator(graph)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert len(candidates) == len(BEARINGS) - 2
    assert compass_label(0) not in [c.direction_label for c in candidates]
    # 改善計画T557（P2、項目7）: idは最終順位で振り直される（"route-00"..."route-NN"）ため
    # "route-180"という文字列は候補数に関わらず絶対に現れず、この行は何も検証していない
    # 死んだassertだった（改善計画T531でidがbearingベースからランクベースへ変わった際の
    # 取り残し）。bearing=180が実際に除外されたかはdirection_labelで検証する。
    assert compass_label(180) not in [c.direction_label for c in candidates]


async def test_generate_loops_returns_empty_list_when_no_road_graph():
    generator, graph_service, _ = make_generator(graph=None)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert candidates == []


async def test_trace_loop_uses_hydrated_geometry_over_context_graph_edge():
    # 全リクエスト・全方位が通る主経路の検証（road_graph_engine.py:341,386の
    # `hydrated.get(edge_id) or context.graph.edges[edge_id]`のor左辺）。従来は
    # FakeGraphService.get_edges_with_geometryが常に{}を返す実装だったため、or右辺
    # （実DBアクセスが何らかの理由で失敗した場合の防御的フォールバック）だけがテストされ、
    # hydrated（実DBジオメトリ相当）優先の主経路が一度も検証されていなかった。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    target_edge_id = "e-0-spoke1"  # bearing=0の周回の往路Edge
    original_edge = graph.edges[target_edge_id]
    # 実DBから取得し直した想定のhydrated版: 元のgeometryにはない中間点を挟み、
    # context.graph.edges側にフォールバックした場合と区別できるようにする。
    midpoint = destination_point(ORIGIN, 0, 1.0)
    hydrated_edge = original_edge.model_copy(
        update={
            "geometry": [
                original_edge.geometry[0],
                [midpoint.latitude, midpoint.longitude],
                original_edge.geometry[-1],
            ],
        }
    )
    generator, graph_service, _ = make_generator(
        graph, edges_with_geometry={target_edge_id: hydrated_edge}
    )

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)
    candidate = _candidate_for_bearing(candidates, 0)

    # hydrated側の中間点（GeoJSONは[lon, lat]順）が候補のgeometryへ反映されている
    # ＝context.graph.edges側（フォールバック、中間点を持たない）ではなくhydratedが使われた。
    assert [midpoint.longitude, midpoint.latitude] in candidate.geometry["coordinates"]


async def test_generate_loops_fetches_road_graph_only_once_for_all_directions():
    # 実機検証で、方位ごとに個別にOverpassへ問い合わせる設計が公開インスタンスに
    # よって拒否される事象を確認したため、8方位分をまとめた単一のbboxで1回だけ取得する
    # 設計に変更した（road_graph_engine.pyのモジュールdocstring参照）。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, graph_service, _ = make_generator(graph)

    await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert graph_service.call_count == 1


async def test_generate_loops_filters_candidates_outside_distance_tolerance():
    # bearing=0の迂回路（復路の候補）を50km先を回る大回りへ置き換える。往路（スポーク、15km）は
    # リングに入るため折返し候補にはなるが、復路がretraceペナルティ付きスポーク逆走
    # （コスト15km×8）より安い大回り（約100km）を選ぶため周回は約115kmになり、距離フィルタで
    # 棄却される。他の方位は影響を受けない。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    far_point = destination_point(ORIGIN, 12, 50.0)
    tip = graph.nodes["p-0"]
    tip_coord = Coordinates(latitude=tip.latitude, longitude=tip.longitude)
    new_nodes = dict(graph.nodes)
    new_nodes["far"] = Node(node_id="far", latitude=far_point.latitude, longitude=far_point.longitude)
    new_edges = {eid: e for eid, e in graph.edges.items() if not eid.startswith("e-0-alt")}
    new_edges["e-0-far1"] = _edge("e-0-far1", "p-0", "far", tip_coord, far_point)
    new_edges["e-0-far2"] = _edge("e-0-far2", "far", "origin", far_point, ORIGIN)
    graph = RoadGraph(graph_version="test", nodes=new_nodes, edges=new_edges)

    generator, _, _ = make_generator(graph)
    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)

    assert compass_label(0) not in [c.direction_label for c in candidates]
    assert len(candidates) == len(BEARINGS) - 1


# --- 改善計画T531: フロンティア方式（折返し点選定・復路探索） ---


async def _prepare_context(generator: RouteGenerator, distance_km: float = 30.0):
    context = await generator._engine.prepare(ORIGIN, radius_km=distance_km * TURNAROUND_RADIUS_RATIO)
    assert context is not None
    return context


async def test_select_turnarounds_returns_ring_nodes_with_outbound_from_tree():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph)
    engine = generator._engine
    context = await _prepare_context(generator)

    turnarounds = await engine.select_loop_turnarounds(context, 30.0, 5.0, pool_size=24)

    # 各方位の折返し点p-{b}（往路15km=目標の半分、リング内）だけが候補になる。
    # m-{b}（約7.7km）はリングに入らない。
    assert sorted(t.bearing for t in turnarounds) == sorted(BEARINGS)
    assert {t.data.node_id for t in turnarounds} == {f"p-{b}" for b in BEARINGS}
    for turnaround in turnarounds:
        assert turnaround.data.outbound_length_m == pytest.approx(15000.0, abs=100)
        assert [turnaround.data.outbound_edge_indices] and len(turnaround.data.outbound_edge_indices) == 1


async def test_select_turnarounds_ring_lower_bound_clamped_when_tolerance_exceeds_target():
    # 改善計画T557（P1）: 許容distance_tolerance_kmが目標distance_kmを超えると
    # `ring_lower_m = (target_m - tolerance_m) / LOOP_TO_OUTBOUND_RATIO_MIN`が負になる。
    # 修正前は0でクランプしておらず、リング中心（`(ring_lower_m + ring_upper_m) / 2`）も
    # 負・0付近まで引き下げられ、極端に短い往路（起点のすぐ近く）が「リング中心に近い順」の
    # タイブレークで不当に上位へ来ていた。ここでは目標0.5km・許容20km（許容≥目標を大きく
    # 超える）という極端な設定で、リング中心付近（新しいRING_CENTER_RATIO=2.15による
    # 中心≈232.6m）の候補が、起点のすぐ近く（20m）の候補より上位に来ることを検証する。
    origin = ORIGIN
    near_origin = destination_point(origin, 0, 0.02)  # 20m
    near_center = destination_point(origin, 180, 0.2326)  # ≈232.6m（0.5km/2.15付近）
    nodes = {
        "origin": Node(node_id="origin", latitude=origin.latitude, longitude=origin.longitude),
        "p-near": Node(node_id="p-near", latitude=near_origin.latitude, longitude=near_origin.longitude),
        "p-center": Node(node_id="p-center", latitude=near_center.latitude, longitude=near_center.longitude),
    }
    edges = {
        "e-near": _edge("e-near", "origin", "p-near", origin, near_origin),
        "e-near-rev": _edge("e-near-rev", "p-near", "origin", near_origin, origin),
        "e-center": _edge("e-center", "origin", "p-center", origin, near_center),
        "e-center-rev": _edge("e-center-rev", "p-center", "origin", near_center, origin),
    }
    graph = RoadGraph(graph_version="test", nodes=nodes, edges=edges)
    generator, _, _ = make_generator(graph)
    engine = generator._engine
    context = await engine.prepare(origin, radius_km=5.0)
    assert context is not None

    turnarounds = await engine.select_loop_turnarounds(context, 0.5, 20.0, pool_size=1)

    assert len(turnarounds) == 1
    assert turnarounds[0].data.node_id == "p-center"


async def test_is_loop_too_similar_rejects_exact_reverse_and_keeps_partial_overlap():
    # 改善計画T557（項目8）→T553: 「同じ周回の逆回り」（進行方向が違うだけで物理的には
    # 同一の周回）を検知して棄却し、閾値未満の部分重複は残すことを検証する。
    # 距離は全Edge等しく1000mへ揃え、比率の計算をシンプルにする。
    node_a = Node(node_id="a", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude)
    node_b = Node(node_id="b", latitude=ORIGIN.latitude + 0.01, longitude=ORIGIN.longitude)
    node_c = Node(node_id="c", latitude=ORIGIN.latitude + 0.02, longitude=ORIGIN.longitude)
    node_d = Node(node_id="d", latitude=ORIGIN.latitude + 0.03, longitude=ORIGIN.longitude)
    coord_a = Coordinates(latitude=node_a.latitude, longitude=node_a.longitude)
    coord_b = Coordinates(latitude=node_b.latitude, longitude=node_b.longitude)
    coord_c = Coordinates(latitude=node_c.latitude, longitude=node_c.longitude)
    coord_d = Coordinates(latitude=node_d.latitude, longitude=node_d.longitude)
    edges = {
        "e1": _edge("e1", "a", "b", coord_a, coord_b, distance_m=1000.0),
        "e1-rev": _edge("e1-rev", "b", "a", coord_b, coord_a, distance_m=1000.0),
        "e2": _edge("e2", "b", "c", coord_b, coord_c, distance_m=1000.0),
        "e2-rev": _edge("e2-rev", "c", "b", coord_c, coord_b, distance_m=1000.0),
        "e4": _edge("e4", "c", "a", coord_c, coord_a, distance_m=1000.0),
        "e4-rev": _edge("e4-rev", "a", "c", coord_a, coord_c, distance_m=1000.0),
        "e5": _edge("e5", "c", "d", coord_c, coord_d, distance_m=1000.0),
    }
    graph = RoadGraph(graph_version="test", nodes={"a": node_a, "b": node_b, "c": node_c, "d": node_d}, edges=edges)
    generator, _, _ = make_generator(graph)
    engine = generator._engine
    context = await engine.prepare(ORIGIN, radius_km=5.0)
    assert context is not None

    accepted = road_graph_engine.TracedLoop(bearing=0, distance_km=3.0, data=["e1", "e2", "e4"])
    # 完全な逆回り（同じ3区間を逆方向に辿るだけ、重複率100%）→ 棄却される。
    exact_reverse = road_graph_engine.TracedLoop(bearing=180, distance_km=3.0, data=["e4-rev", "e2-rev", "e1-rev"])
    assert engine.is_loop_too_similar(context, exact_reverse, [accepted]) is True

    # 3区間中2区間だけ共有（重複率2/3≈0.67 < LOOP_MAX_OVERLAP_RATIO=0.7）→ 残る。
    partial_overlap = road_graph_engine.TracedLoop(bearing=90, distance_km=3.0, data=["e1-rev", "e2-rev", "e5"])
    assert engine.is_loop_too_similar(context, partial_overlap, [accepted]) is False


async def test_return_leg_avoids_outbound_road_when_alternative_exists():
    # 復路探索の間だけ往路Edge（＋逆方向Edge）のコストをRETRACE_PENALTY_MULTIPLIER倍に
    # するため、スポークの逆走（15km）より迂回路（約15.3km）が選ばれる。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph)
    engine = generator._engine
    context = await _prepare_context(generator)
    turnarounds = await engine.select_loop_turnarounds(context, 30.0, 5.0, pool_size=24)
    turnaround = next(t for t in turnarounds if t.bearing == 0)

    traced = await engine.trace_loop_from_turnaround(context, turnaround)

    assert traced.bearing == 0
    assert traced.data == ["e-0-spoke1", "e-0-alt1", "e-0-alt2"]
    assert traced.distance_km == pytest.approx(15.0 * (1 + 1.0215), abs=0.2)


async def test_return_leg_retraces_outbound_when_no_alternative_exists():
    # 倍率は有限のため、復路が往路を戻る以外に道が無ければそのまま逆走して周回を閉じる。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    graph = RoadGraph(
        graph_version="test", nodes=graph.nodes,
        edges={eid: e for eid, e in graph.edges.items() if not eid.startswith("e-0-alt")},
    )
    generator, _, _ = make_generator(graph)
    engine = generator._engine
    context = await _prepare_context(generator)
    turnarounds = await engine.select_loop_turnarounds(context, 30.0, 5.0, pool_size=24)
    turnaround = next(t for t in turnarounds if t.bearing == 0)

    traced = await engine.trace_loop_from_turnaround(context, turnaround)

    assert traced.data == ["e-0-spoke1", "e-0-spoke1-rev"]
    assert traced.distance_km == pytest.approx(30.0, abs=0.1)


async def test_return_leg_search_restores_shared_cost_list():
    # 復路探索のコスト差し替えは探索後に必ず元へ戻す（共有cost_listを汚さない）。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph)
    engine = generator._engine
    context = await _prepare_context(generator)
    turnarounds = await engine.select_loop_turnarounds(context, 30.0, 5.0, pool_size=24)
    before = list(context.legs[-1].cost_list)

    for turnaround in turnarounds:
        await engine.trace_loop_from_turnaround(context, turnaround)

    assert context.legs[-1].cost_list == before


async def test_return_leg_search_restores_cost_list_even_when_no_path_found():
    # 復路が見つからない（折返し点から起点へ戻る道が無い）場合もコストを復元してから
    # RoutingErrorになる。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    graph = RoadGraph(
        graph_version="test", nodes=graph.nodes,
        edges={eid: e for eid, e in graph.edges.items() if not (eid.startswith("e-0-") and eid != "e-0-spoke1")},
    )
    generator, _, _ = make_generator(graph)
    engine = generator._engine
    context = await _prepare_context(generator)
    turnarounds = await engine.select_loop_turnarounds(context, 30.0, 5.0, pool_size=24)
    turnaround = next(t for t in turnarounds if t.bearing == 0)
    before = list(context.legs[-1].cost_list)

    with pytest.raises(RoutingError):
        await engine.trace_loop_from_turnaround(context, turnaround)

    assert context.legs[-1].cost_list == before


async def test_turnarounds_are_ranked_by_outbound_axis_difficulty():
    # 自転車インフラの重みを100%にすると、往路（スポーク）が分離自転車道である方位が先頭になる。
    # 他の方位はインフラ無し（difficulty 100）で同点→往路実距離が目標の半分に近い順→node index順。
    graph = build_loop_graph(ORIGIN, distance_km=30.0, highway="residential")
    preference = RoutePreference(
        weights={"gradient": 0.0, "wind": 0.0, "surface_q": 0.0, "stop_density": 0.0,
                 "car_stress": 0.0, "accident": 0.0, "night": 0.0, "bicycle_infra_quality": 1.0}
    )
    generator, _, _ = make_generator(
        graph, way_tags={"e-90-spoke1": {"cycleway": "track"}}, route_preference=preference,
    )
    engine = generator._engine
    context = await _prepare_context(generator)

    turnarounds = await engine.select_loop_turnarounds(context, 30.0, 5.0, pool_size=24)

    assert turnarounds[0].bearing == 90
    assert turnarounds[0].outbound_difficulty == 0.0
    assert all(t.outbound_difficulty == 100.0 for t in turnarounds[1:])


async def test_select_turnarounds_spreads_bearing_when_all_difficulty_tied():
    # 改善計画T554: 全方位が同一difficulty（highway無指定、材料データ無し→全Edge同点）の
    # とき、pool_sizeで打ち切っても選ばれた候補の方位が隣接象限へ固まらず全4象限へ広がる
    # （車輪状フィクスチャは全8方位が起点から等距離・同一難易度で完全に対称なため、
    # 最遠点貪欲法は必ず対蹠点→残り2象限の順で選ぶ）。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph)
    engine = generator._engine
    context = await _prepare_context(generator)

    turnarounds = await engine.select_loop_turnarounds(context, 30.0, 5.0, pool_size=4)

    assert len(turnarounds) == 4
    quadrants = {t.bearing // 90 for t in turnarounds}
    assert quadrants == {0, 1, 2, 3}


async def test_select_turnarounds_skips_node_sharing_outbound_corridor():
    # bearing=0のスポークを起点→p-0a（13.5km）→p-0（1.5km）の2Edgeへ分割する。p-0a・p-0は
    # どちらもリング（目標30km±5km→往路12.5〜15.2km）に入り、1.5km離れている（近接間引きの
    # 下限ちょうど）が、p-0の往路の90%（13.5/15）はp-0aの往路と同じEdgeのため、重複率の
    # 間引きで片方だけが残る（同じコリドー上の候補が並ばない）。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    split_point = destination_point(ORIGIN, 0, 13.5)
    tip = graph.nodes["p-0"]
    tip_coord = Coordinates(latitude=tip.latitude, longitude=tip.longitude)
    new_nodes = dict(graph.nodes)
    new_nodes["p-0a"] = Node(node_id="p-0a", latitude=split_point.latitude, longitude=split_point.longitude)
    new_edges = {eid: e for eid, e in graph.edges.items() if not eid.startswith("e-0-spoke1")}
    new_edges["e-0-spoke1a"] = _edge("e-0-spoke1a", "origin", "p-0a", ORIGIN, split_point)
    new_edges["e-0-spoke1b"] = _edge("e-0-spoke1b", "p-0a", "p-0", split_point, tip_coord)
    new_edges["e-0-spoke1a-rev"] = _edge("e-0-spoke1a-rev", "p-0a", "origin", split_point, ORIGIN)
    new_edges["e-0-spoke1b-rev"] = _edge("e-0-spoke1b-rev", "p-0", "p-0a", tip_coord, split_point)
    graph = RoadGraph(graph_version="test", nodes=new_nodes, edges=new_edges)
    generator, _, _ = make_generator(graph)
    engine = generator._engine
    context = await _prepare_context(generator)

    turnarounds = await engine.select_loop_turnarounds(context, 30.0, 5.0, pool_size=24)

    selected = {t.data.node_id for t in turnarounds}
    assert len(turnarounds) == len(BEARINGS)
    assert len(selected & {"p-0a", "p-0"}) == 1


async def test_generate_loops_returns_at_most_max_routes_and_stops_tracing_early():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph)
    engine = generator._engine
    calls = []
    original = engine.trace_loop_from_turnaround

    async def counting(context, turnaround):
        calls.append(turnaround.bearing)
        return await original(context, turnaround)

    engine.trace_loop_from_turnaround = counting

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0, max_routes=3)

    assert [c.id for c in candidates] == ["route-00", "route-01", "route-02"]
    assert len(calls) == 3


async def test_generate_loops_returns_empty_when_no_node_reaches_ring():
    # 目標距離100kmに対し道路網は半径15kmしか無く、往路実距離がリング（45〜55km）に入る
    # Nodeが存在しない→折返し候補0件。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, elevation_service = make_generator(graph)

    candidates = await generator.generate_loops(ORIGIN, distance_km=100.0, distance_tolerance_km=10.0)

    assert candidates == []
    assert elevation_service.graphs_queried == []
    assert generator.last_no_candidates_reason is not None
    assert "折返し" in generator.last_no_candidates_reason


async def test_geometry_is_fetched_once_for_all_survivors_after_distance_filter():
    # 改善計画T531: 実ジオメトリのDB取得は距離フィルタ通過後の候補ぶんをまとめて1回だけ
    # 行う（棄却候補のぶんは取得しない）。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, graph_service, _ = make_generator(graph)

    await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=5.0)
    assert len(graph_service.geometry_requests) == 1
    assert len(graph_service.geometry_requests[0]) == 3 * len(BEARINGS)

    graph_service.geometry_requests.clear()
    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=0.001)
    assert candidates == []
    assert graph_service.geometry_requests == []


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
    candidate = _candidate_for_bearing(candidates, 0)

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

    assert len(elevation_service.graphs_queried) == len(BEARINGS)  # 方位ごとに1回ずつ
    for queried_graph in elevation_service.graphs_queried:
        assert len(queried_graph.edges) == 3  # 1候補=3区間分のみ（フルグラフの48区間ではない）
        assert len(queried_graph.edges) < len(graph.edges)


async def test_elevation_attribute_service_is_not_queried_when_materials_already_has_precomputed_data():
    # 改善計画T522派生（評価ロジックの入口〜出口見直し）: context.materials
    # （探索フェーズで既に取得済みのEdgeMaterialBundle）が経路上の全Edgeの標高を
    # 既に持っていれば、ElevationAttributeServiceへは一切問い合わせない
    # （同じelevation_attributesテーブルを候補確定後にもう一度読み直す重複DB往復の解消）。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    elevation_attributes_for_search = {
        edge_id: ElevationAttribute(edge_id=edge_id, average_grade=0.0, data_source="test", calculated_at="t")
        for edge_id in graph.edges
    }
    generator, _, elevation_service = make_generator(
        graph, elevation_attributes_for_search=elevation_attributes_for_search
    )

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert len(candidates) == len(BEARINGS)
    assert elevation_service.graphs_queried == []


async def test_elevation_attribute_service_is_queried_only_for_edges_missing_from_materials():
    # 改善計画T522派生: 経路上の一部のEdgeだけmaterialsに標高が無い（事前計算バッチ未実行）
    # 場合、ElevationAttributeServiceへはその欠けている分だけを問い合わせる
    # （materials側に既にある分を含めて丸ごと問い合わせ直したりはしない）。
    # bearing=0の復路（e-0-alt1/e-0-alt2）だけ事前計算が無い状態にする（他の全Edgeは
    # 事前計算済み。往路・復路の選択がgradient軸のデータ有無で偏らないよう、往路と
    # その逆方向Edgeには同じ値を持たせる）。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    elevation_attributes_for_search = {
        edge_id: ElevationAttribute(edge_id=edge_id, average_grade=1.0, data_source="test", calculated_at="t")
        for edge_id in graph.edges
        if edge_id not in ("e-0-alt1", "e-0-alt2")
    }
    fetched_on_demand = {
        "e-0-alt1": ElevationAttribute(edge_id="e-0-alt1", average_grade=2.0, data_source="test", calculated_at="t"),
        "e-0-alt2": ElevationAttribute(
            edge_id="e-0-alt2", average_grade=3.0, data_source="test", calculated_at="t"
        ),
    }
    generator, _, elevation_service = make_generator(
        graph, elevation_attributes=fetched_on_demand,
        elevation_attributes_for_search=elevation_attributes_for_search,
    )

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert len(candidates) == len(BEARINGS)
    bearing_0_query = next(g for g in elevation_service.graphs_queried if "e-0-alt1" in g.edges)
    assert set(bearing_0_query.edges.keys()) == {"e-0-alt1", "e-0-alt2"}


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
    candidate = _candidate_for_bearing(candidates, 0)

    assert candidate.road_score is not None
    assert 0.0 <= candidate.road_score <= 100.0


async def test_candidate_aggregates_stop_density_from_path_edges():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    edge_ids = sorted(eid for eid in graph.edges if eid.startswith("e-0-"))
    stop_counts = {edge_ids[0]: 3, f"{edge_ids[0]}-rev": 3}
    generator, _, _ = make_generator(graph, stop_counts=stop_counts)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)
    candidate = _candidate_for_bearing(candidates, 0)

    segment_with_stops = next(s for s in candidate.segments if s.axis_difficulties.get("stop_density", 0) > 0)
    assert segment_with_stops.difficulty is not None


async def test_candidate_stop_density_axis_is_zero_without_any_stop_pois():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph)  # stop_counts未指定（=repository注入済み・実測0件）

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)
    candidate = _candidate_for_bearing(candidates, 0)

    assert all(s.axis_difficulties.get("stop_density") == 0.0 for s in candidate.segments)


async def test_candidate_stop_density_axis_is_absent_when_data_unavailable():
    # repository未注入等でstop_poiデータ自体を取得できない場合は「実測0件」とは区別して
    # axis_difficulties自体にキーを持たない。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph, stop_data_available=False)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)
    candidate = _candidate_for_bearing(candidates, 0)

    assert all("stop_density" not in s.axis_difficulties for s in candidate.segments)


async def test_candidate_reflects_bicycle_infra_from_way_tags():
    # 静的道路属性P1残り。way_tagsが取得できた区間は自転車インフラが評価軸へ反映される
    # （このテストのbuild_loop_graphはEdge.highwayを持たないため、highway必須の車ストレスは
    # Noneのまま。highway非依存のbicycle_infraだけ検証する）。改善計画T138で自転車インフラの
    # 独立難易度軸（infra_difficulty）は廃止し車ストレス側へ統合済みのため、ここでは検証しない。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    edge_ids = sorted(eid for eid in graph.edges if eid.startswith("e-0-"))
    way_tags = {edge_ids[0]: {"cycleway": "track"}, f"{edge_ids[0]}-rev": {"cycleway": "track"}}
    generator, _, _ = make_generator(graph, way_tags=way_tags)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)
    candidate = _candidate_for_bearing(candidates, 0)

    # 改善計画T347: RouteSegmentDetail.bicycle_infra（生値の分類文字列）は削除済みのため、
    # cycleway=track区間が正しく認識されたことは評価軸bicycle_infra_quality（分離自転車道は
    # 最良値0.0）で確認する。
    segment_with_track = next(s for s in candidate.segments if s.axis_difficulties.get("bicycle_infra_quality") == 0.0)
    assert segment_with_track is not None


async def test_candidate_aggregates_intersection_density_from_path_edges():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    edge_ids = sorted(eid for eid in graph.edges if eid.startswith("e-0-"))
    intersection_counts = {edge_ids[0]: 2, f"{edge_ids[0]}-rev": 2}
    generator, _, _ = make_generator(graph, intersection_counts=intersection_counts)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)
    candidate = _candidate_for_bearing(candidates, 0)

    # 改善計画T149: 交差点密度は独立軸を持たずstop_density側へ低い重みで吸収される
    # （旧intersection_difficultyは廃止）。
    segment_with_intersections = next(
        s for s in candidate.segments if s.axis_difficulties.get("stop_density", 0) > 0
    )
    assert segment_with_intersections.difficulty is not None


async def test_candidate_aggregates_accident_density_from_path_edges():
    # 外部静的データソース T50残作業（8軸目）。事故密度は件/(km・年)のため
    # accident_years_coveredも指定する。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    edge_ids = sorted(eid for eid in graph.edges if eid.startswith("e-0-"))
    accident_counts = {edge_ids[0]: 2, f"{edge_ids[0]}-rev": 2}
    generator, _, _ = make_generator(graph, accident_counts=accident_counts, accident_years_covered=2)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)
    candidate = _candidate_for_bearing(candidates, 0)

    segment_with_accidents = next(
        s for s in candidate.segments if s.axis_difficulties.get("accident", 0) > 0
    )
    assert segment_with_accidents.difficulty is not None


async def test_candidate_accident_axis_is_absent_when_years_covered_is_zero():
    # accident_years_covered=0（事故データ未取込）は、件数があっても密度を算出できないため
    # axis_difficulties自体にaccidentキーを持たない。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    edge_ids = sorted(eid for eid in graph.edges if eid.startswith("e-0-"))
    accident_counts = {edge_ids[0]: 2, f"{edge_ids[0]}-rev": 2}
    generator, _, _ = make_generator(graph, accident_counts=accident_counts, accident_years_covered=0)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)
    candidate = _candidate_for_bearing(candidates, 0)

    assert all("accident" not in s.axis_difficulties for s in candidate.segments)


async def test_candidate_aggregates_wind_score_when_weather_available():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    weather = WeatherConditions(
        temperature_c=20.0, apparent_temperature_c=None, wind_speed_ms=5.0, wind_direction_deg=0.0,
        wind_direction_label="北", wind_gusts_ms=None, precipitation_probability_percent=None,
        precipitation_mm=None, uv_index=None, observed_at="t",
        weather_code=None, is_day=None,
        sunrise=None, sunset=None, precipitation_probability_max_percent=None, wind_speed_max_ms=None,
        temperature_max_c=None, temperature_min_c=None,
        uv_index_max=None, today_periods=[],
    )
    generator, _, _ = make_generator(graph, weather=weather)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert all(c.wind_score is not None for c in candidates)


async def test_candidate_wind_score_is_none_without_weather():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph, weather=None)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert all(c.wind_score is None for c in candidates)


async def test_candidate_segments_cover_every_edge_on_the_path():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)
    candidate = _candidate_for_bearing(candidates, 0)

    assert candidate.segments is not None
    assert len(candidate.segments) == 3  # spoke1→alt1→alt2の3区間
    assert candidate.segments[0].cumulative_distance_km == 0.0
    total_segment_distance = sum(s.distance_km for s in candidate.segments)
    assert abs(total_segment_distance - candidate.distance_km) < 0.1


async def test_candidate_segments_carry_edge_geometry_for_map_drawing():
    # 区間の色分けを道路形状に沿って描くため、各区間はEdgeの形状点列をGeoJSON
    # LineString（[lon, lat]順）として持つ（研究IF改善: 区間表示の道なり化）。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)
    candidate = _candidate_for_bearing(candidates, 0)

    for seg in candidate.segments:
        assert seg.geometry is not None
        assert seg.geometry["type"] == "LineString"
        coordinates = seg.geometry["coordinates"]
        assert len(coordinates) >= 2
        # 形状の端点はstart/endフィールドと一致する（GeoJSONは[lon, lat]順）
        assert coordinates[0] == [seg.start_longitude, seg.start_latitude]
        assert coordinates[-1] == [seg.end_longitude, seg.end_latitude]


async def test_candidate_segments_are_binned_into_approximately_500m_groups():
    # 改善計画T11（レビュー指摘M3）: bearing=0のorigin→p-0スポーク（実距離15km、
    # build_loop_graphの折返し点=目標距離の半分・distance_km=30より）を、約0.15km刻みの短い
    # Edge101本のチェーンへ置き換え、実データのEdge単位segments（交差点間、多くは
    # 500m未満）を模す。ビン化後のsegments件数がEdge本数より大幅に少なくなり、
    # かつ合計距離は保たれることを確認する（チェーンは一方通行のため復路はスポークの
    # 逆走`e-0-spoke1-rev`[往路のEdgeではないのでペナルティ対象外]になる）。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    origin_node = graph.nodes["origin"]
    p0_node = graph.nodes["p-0"]
    origin_coord = Coordinates(latitude=origin_node.latitude, longitude=origin_node.longitude)
    p0_coord = Coordinates(latitude=p0_node.latitude, longitude=p0_node.longitude)

    chain_node_count = 100
    new_nodes = dict(graph.nodes)
    new_edges = dict(graph.edges)
    del new_edges["e-0-spoke1"]

    previous_node_id = "origin"
    previous_coord = origin_coord
    for i in range(chain_node_count):
        fraction = (i + 1) / (chain_node_count + 1)
        lat = origin_coord.latitude + (p0_coord.latitude - origin_coord.latitude) * fraction
        lon = origin_coord.longitude + (p0_coord.longitude - origin_coord.longitude) * fraction
        node_id = f"chain-{i}"
        coord = Coordinates(latitude=lat, longitude=lon)
        new_nodes[node_id] = Node(node_id=node_id, latitude=lat, longitude=lon)
        new_edges[f"chain-edge-{i}"] = _edge(f"chain-edge-{i}", previous_node_id, node_id, previous_coord, coord)
        previous_node_id, previous_coord = node_id, coord
    new_edges["chain-edge-final"] = _edge("chain-edge-final", previous_node_id, "p-0", previous_coord, p0_coord)

    graph = RoadGraph(graph_version="test", nodes=new_nodes, edges=new_edges)
    generator, _, _ = make_generator(graph)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)
    candidate = _candidate_for_bearing(candidates, 0)

    # 元のEdge数: チェーン101本 + 復路1本 = 102本。ビン化後は500m単位に集約され
    # 大幅に少なくなるはず（チェーン部分は約15km÷0.5km=30ビン程度が目安）。
    assert candidate.segments is not None
    assert len(candidate.segments) < 40
    total_segment_distance = sum(s.distance_km for s in candidate.segments)
    # 各Edge単位segmentのdistance_kmは個別に2桁丸め済み（_build_segment_details）のため、
    # 100本超のチェーンでは累積の丸め誤差が既存テスト（Edge2-3本）より目立つ。
    # ビン化自体が誤差を増やしているわけではないため、許容差はEdge本数に応じて広めに取る。
    assert abs(total_segment_distance - candidate.distance_km) < 0.5


async def test_candidates_are_sorted_by_overall_difficulty_ascending():
    # 改善計画T548: 候補タブの並び順はoverall_difficulty（絶対基準0-100）昇順。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph)

    candidates = await generator.generate_loops(ORIGIN, distance_km=30.0, distance_tolerance_km=10.0)

    assert all(c.overall_difficulty is not None for c in candidates)
    difficulties = [c.overall_difficulty for c in candidates]
    assert difficulties == sorted(difficulties)


async def test_engine_name_is_road_graph():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph)

    assert generator.engine_name == "road_graph"


async def test_build_segment_details_axis_difficulties_match_scalar_oracle():
    # 改善計画T536: 区間表示（_build_segment_details）は、探索コスト算出時に
    # StaticEdgeScoreMatrix経由でbbox全体ぶん合成済みの軸別スコア配列・合成difficulty
    # 配列（context.axis_arrays/context.difficulty_array）からそのまま読む（探索と表示の
    # 二重計算を解消、docs/tasks/T536.md参照）。以前（T143）は非キャッシュの
    # compute_edge_axis_scoresを区間ごとに再計算しており、本テストはそれを呼ぶことだけを
    # 検証していたが、T536でその呼び出し自体が無くなったため、代わりに
    # _build_segment_detailsの出力が非キャッシュのスカラー版オラクル
    # （compute_edge_axis_scores/compute_cost_from_axis_scores）とビット単位で一致する
    # ことを確認する（T536完了条件「新方式が現行compute_edge_cost経路とビット単位で
    # 一致する回帰テスト」の、区間表示レイヤーでの確認）。
    from app.domain.evaluation import compute_cost_from_axis_scores, compute_edge_axis_scores

    node_a = Node(node_id="a", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude)
    node_b = Node(node_id="b", latitude=ORIGIN.latitude + 0.01, longitude=ORIGIN.longitude)
    coord_b = Coordinates(latitude=node_b.latitude, longitude=node_b.longitude)
    edge = _edge("e1", "a", "b", ORIGIN, coord_b, highway="residential")
    graph = RoadGraph(graph_version="test", nodes={"a": node_a, "b": node_b}, edges={"e1": edge})
    way_tags = {"e1": {"highway": "residential", "lit": "yes", "surface": "gravel"}}
    elevation_attr = ElevationAttribute(
        edge_id="e1", average_grade=6.0, data_source="test", calculated_at="t"
    )
    counts = EdgeAttributeCounts(accident_count=1.0, stop_count=3, intersection_count=2)
    materials = {
        "e1": EdgeMaterialBundle(
            surface="gravel", way_tags=way_tags["e1"], attribute_counts=counts,
            elevation_attribute=elevation_attr, is_designated=True,
        )
    }
    weather = WeatherConditions(
        temperature_c=20.0, apparent_temperature_c=None, wind_speed_ms=5.0, wind_direction_deg=90.0,
        wind_direction_label="東", wind_gusts_ms=None, precipitation_probability_percent=None,
        precipitation_mm=None, uv_index=None, observed_at="t",
        weather_code=None, is_day=None,
        sunrise=None, sunset=None, precipitation_probability_max_percent=None, wind_speed_max_ms=None,
        temperature_max_c=None, temperature_min_c=None,
        uv_index_max=None, today_periods=[],
    )
    preference = RoutePreference()

    generator, _, _ = make_generator(None, route_preference=preference)
    engine = generator._engine

    context = road_graph_engine._RoadGraphContext(
        graph=graph, materials=materials, accident_years_covered=5,
        weather=weather, origin_node="a",
        node_index=build_node_spatial_index(graph), night_active=False,
        lazy_graph=None,
        **_build_context_score_fields(
            graph, materials, preference, weather=weather, night_active=False, accident_years_covered=5,
        ),
    )

    segments = engine._build_segment_details([edge], {"e1": elevation_attr}, context, datetime.now(timezone.utc), [0])
    assert len(segments) == 1
    segment = segments[0]

    oracle_axis_scores = compute_edge_axis_scores(
        edge, elevation_attr, "gravel", weather=weather, stop_count=3, way_tags=way_tags["e1"],
        intersection_count=2, accident_count=1.0, accident_years_covered=5, is_designated=True,
        travel_speed_ms=kmh_to_ms(ASSUMED_SPEED_KMH),
    )
    _, oracle_difficulty = compute_cost_from_axis_scores(
        edge.distance_m, oracle_axis_scores, preference.weights, 1.0
    )

    assert segment.axis_difficulties == oracle_axis_scores
    assert segment.difficulty == oracle_difficulty


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
    # 0にし、night重みだけが探索コストへ効くようにする（差分をnight軸だけに起因させる）。
    preference = RoutePreference(
        weights={"gradient": 0.0, "wind": 0.0, "surface_q": 0.0, "stop_density": 0.0,
                 "car_stress": 0.0, "accident": 0.0, "night": 1.0, "bicycle_infra_quality": 0.0}
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

    day_cost = _lazy_edge_cost(engine, day_context, "a", "b")
    night_cost = _lazy_edge_cost(engine, night_context, "a", "b")
    # 日中はnight_weightが0倍されるため、他の軸の重みも全て0の本ケースではdistance_mそのもの
    # （難易度による割増なし）になるはず。夜間はnight_difficulty分の割増が乗る。
    assert night_cost > day_cost
    assert day_cost == pytest.approx(edge.distance_m, abs=0.1)


async def test_prepare_does_not_crash_when_night_axis_is_unpublished(monkeypatch):
    # 改善計画T316フォローアップ回帰テスト: night軸が軸スタジオで非公開化されると
    # RoutePreference.weightsに"night"キーが存在しなくなる。修正前はwith_weight("night",
    # 0.0)が強制的に未知のaxis_idをweightsへ追加しようとしてValidationErrorになり、
    # デフォルトエンジン（road_graph）の日中の全リクエストが丸ごと500になっていた
    # （2026-08-25の実障害、domain/evaluation.py: RoutePreference.with_weight参照）。
    from app.domain.axis_definitions import AXIS_DEFINITIONS

    original_night = AXIS_DEFINITIONS["night"]
    monkeypatch.setitem(AXIS_DEFINITIONS, "night", original_night.model_copy(update={"is_published": False}))

    node_a = Node(node_id="a", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude)
    node_b = Node(node_id="b", latitude=ORIGIN.latitude + 0.01, longitude=ORIGIN.longitude)
    coord_b = Coordinates(latitude=node_b.latitude, longitude=node_b.longitude)
    edge = _edge("e1", "a", "b", ORIGIN, coord_b, highway="residential")
    graph = RoadGraph(graph_version="test", nodes={"a": node_a, "b": node_b}, edges={"e1": edge})

    preference = RoutePreference()
    assert "night" not in preference.weights  # night非公開のため既定値に含まれない前提の確認
    generator, _, _ = make_generator(graph, way_tags={"e1": {}}, route_preference=preference)
    engine = generator._engine

    daytime = datetime(2024, 6, 21, 3, 0, tzinfo=timezone.utc)
    day_context = await engine.prepare(ORIGIN, radius_km=1.0, now=daytime)  # 例外が出ないことを確認

    assert day_context.night_active is False


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
        weights={"gradient": 1.0, "wind": 0.0, "surface_q": 0.0, "stop_density": 0.0,
                 "car_stress": 0.0, "accident": 0.0, "night": 0.0, "bicycle_infra_quality": 0.0}
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
    flat_cost = _lazy_edge_cost(flat_generator._engine, flat_context, "a", "b")
    # 改善計画T536: 旧axis_score_cache（Edge単位のプロセス内グローバルキャッシュ、T534）は
    # 撤去済み。静的スコア行列はFakeGraphService.get_search_materials_for_bboxが呼ばれる
    # たびに新規構築される（fake自体がタイル単位キャッシュを持たないため）ため、
    # 同じedge_id"e1"を別シナリオへ使い回してもflat/steep間でキャッシュ汚染は起きない。
    steep_context = await steep_generator._engine.prepare(ORIGIN, radius_km=1.0)
    steep_cost = _lazy_edge_cost(steep_generator._engine, steep_context, "a", "b")
    # 事前計算データが無い（{}のまま=バッチ未実行を模す）場合はgradient軸がデータ無し扱いで
    # 割増が乗らない。事前計算済みの急勾配が渡されるとgradient軸の割増がコストへ反映される。
    assert flat_cost == pytest.approx(edge.distance_m, abs=0.1)
    assert steep_cost > flat_cost


async def test_prepare_excludes_edge_exceeding_max_average_grade_percent_from_search_graph():
    # 改善計画T218a: 0次ハードフィルタの勾配しきい値がprepareの探索グラフ構築にも
    # 反映されることを確認する（sparse_graphに該当Edgeが含まれなくなる）。
    # 改善計画T256: 起点(node "a")が孤立しない（＝node_indexの候補から除外されない）よう、
    # 除外されないEdge（a-c）も持たせておく（除外Edge1本だけの構成だと"a"自体が
    # 孤立点になりprepareがNoneを返してしまい、この後のsparse_graph検証に届かない）。
    node_a = Node(node_id="a", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude)
    node_b = Node(node_id="b", latitude=ORIGIN.latitude + 0.01, longitude=ORIGIN.longitude)
    node_c = Node(node_id="c", latitude=ORIGIN.latitude - 0.01, longitude=ORIGIN.longitude)
    coord_b = Coordinates(latitude=node_b.latitude, longitude=node_b.longitude)
    coord_c = Coordinates(latitude=node_c.latitude, longitude=node_c.longitude)
    edge_steep = _edge("e1", "a", "b", ORIGIN, coord_b, highway="residential")
    edge_flat = _edge("e2", "a", "c", ORIGIN, coord_c, highway="residential")
    graph = RoadGraph(
        graph_version="test",
        nodes={"a": node_a, "b": node_b, "c": node_c},
        edges={"e1": edge_steep, "e2": edge_flat},
    )
    steep_climb = ElevationAttribute(edge_id="e1", average_grade=15.0, data_source="test", calculated_at="t")

    generator, _, _ = make_generator(
        graph, way_tags={"e1": {}, "e2": {}},
        elevation_attributes_for_search={"e1": steep_climb},
        max_average_grade_percent=8.0,
    )

    context = await generator._engine.prepare(ORIGIN, radius_km=1.0)

    assert not _lazy_edge_is_allowed(generator._engine, context, "a", "b")
    assert _lazy_edge_is_allowed(generator._engine, context, "a", "c")


async def test_prepare_hard_filters_override_restricts_exclusion_to_specified_filters():
    # 改善計画T266: 0次ハードフィルタ名の個別ON/OFF上書き（コンストラクタの`hard_filters`）が
    # RoadGraphEngineのprepareが構築する探索用グラフ（sparse_graph）まで実際に配線されている
    # ことを確認する。DEFAULT_HARD_FILTERS（domain/evaluation.py）はmotorway/trunk/no_bicycleを
    # 全て除外するため、単に`hard_filters={"motorway"}`を渡してmotorwayが除外されることだけを
    # 見ても「既定のまま素通りしている」ケースと区別できない。ここでは意図的にtrunkを含めない
    # `hard_filters={"motorway"}`を渡し、motorwayは除外されるがtrunk（既定なら除外される）は
    # 除外されないことまで確認することで、コンストラクタ引数が実際に使われていることを示す。
    node_a = Node(node_id="a", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude)
    node_b = Node(node_id="b", latitude=ORIGIN.latitude + 0.01, longitude=ORIGIN.longitude)
    node_c = Node(node_id="c", latitude=ORIGIN.latitude - 0.01, longitude=ORIGIN.longitude)
    coord_b = Coordinates(latitude=node_b.latitude, longitude=node_b.longitude)
    coord_c = Coordinates(latitude=node_c.latitude, longitude=node_c.longitude)
    edge_motorway = _edge("e1", "a", "b", ORIGIN, coord_b, highway="motorway")
    edge_trunk = _edge("e2", "a", "c", ORIGIN, coord_c, highway="trunk")
    graph = RoadGraph(
        graph_version="test",
        nodes={"a": node_a, "b": node_b, "c": node_c},
        edges={"e1": edge_motorway, "e2": edge_trunk},
    )

    generator, _, _ = make_generator(
        graph, way_tags={"e1": {}, "e2": {}}, hard_filters=frozenset({"motorway"}),
    )

    context = await generator._engine.prepare(ORIGIN, radius_km=1.0)

    # motorwayはhard_filtersに含む＝除外
    assert not _lazy_edge_is_allowed(generator._engine, context, "a", "b")
    # trunkはhard_filtersに含めていない＝除外されない
    assert _lazy_edge_is_allowed(generator._engine, context, "a", "c")


async def test_prepare_snaps_origin_away_from_node_isolated_by_hard_constraint():
    # 改善計画T256回帰テスト: 起点に地理的に最も近いNodeが幹線道路（highway=trunk、
    # 既定のHard Constraintで除外対象）にしか接続していない場合（新宿駅・渋谷駅等、
    # 駅前が国道の交差点に直接面する場所で実機確認）、そのNodeはHard Constraint適用後の
    # sparse_graph上で孤立点になる。origin_nodeにこの孤立Nodeがそのまま選ばれると、
    # 半径・方位に関わらずDijkstra探索が常に失敗する（8方位全滅の原因だった）。
    # 修正後は、地理的最近傍ではなく「実際に経路探索可能な」最近傍Nodeへスナップする。
    trunk_hub = Node(node_id="trunk_hub", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude)
    b = Node(node_id="b", latitude=ORIGIN.latitude + 0.001, longitude=ORIGIN.longitude)
    c = Node(node_id="c", latitude=ORIGIN.latitude + 0.002, longitude=ORIGIN.longitude)
    b_coord = Coordinates(latitude=b.latitude, longitude=b.longitude)
    c_coord = Coordinates(latitude=c.latitude, longitude=c.longitude)
    graph = RoadGraph(
        graph_version="test",
        nodes={"trunk_hub": trunk_hub, "b": b, "c": c},
        edges={
            # 起点(ORIGIN)に厳密に一致する最近傍Nodeだが、接続Edgeはtrunkのみ
            # （Hard Constraintで除外＝sparse_graph上で孤立）。
            "e_trunk": _edge("e_trunk", "trunk_hub", "b", ORIGIN, b_coord, highway="trunk"),
            # 経路探索可能な唯一の経路（bは孤立していない）。
            "e_ok": _edge("e_ok", "b", "c", b_coord, c_coord, highway="residential"),
        },
    )
    generator, _, _ = make_generator(graph, way_tags={"e_trunk": {}, "e_ok": {}})

    context = await generator._engine.prepare(ORIGIN, radius_km=1.0)

    assert context.origin_node == "b"


# --- 改善計画T551: 目的地ルート（経由地無し）のvia-node方式代替経路 ---


DESTINATION_20KM = destination_point(ORIGIN, 90, 20.0)


def build_destination_graph(
    origin: Coordinates, destination: Coordinates, offsets_km: list[float], *, highway: str | None = None,
) -> RoadGraph:
    """目的地ルート（via-node方式、改善計画T551）向けの、起点oと目的地dを結ぶ互いに独立した
    経路群を持つRoad Graph。`offsets_km[i]`ごとに起点・目的地を結ぶ直線の中点から垂直方向へ
    その距離だけ外れた位置に折返し点`via-{i}`を置き、o→via-{i}→dの2Edge（片道のみ）で結ぶ
    （offsetが大きいほど迂回になり経路長が伸びる。offset=0はほぼ直線＝最短経路）。
    via-node方式は前向き木・後ろ向き木がそれぞれ順方向のEdgeしか辿らないため、経路の
    再現に復路（逆方向Edge）は不要。
    """
    nodes: dict[str, Node] = {
        "o": Node(node_id="o", latitude=origin.latitude, longitude=origin.longitude),
        "d": Node(node_id="d", latitude=destination.latitude, longitude=destination.longitude),
    }
    edges: dict[str, DirectedEdge] = {}
    overrides = {"highway": highway} if highway is not None else {}
    bearing = bearing_between(origin, destination)
    midpoint = destination_point(origin, bearing, haversine_distance_km(origin, destination) / 2)
    for i, offset_km in enumerate(offsets_km):
        via_point = destination_point(midpoint, (bearing + 90) % 360, offset_km) if offset_km else midpoint
        via_id = f"via-{i}"
        nodes[via_id] = Node(node_id=via_id, latitude=via_point.latitude, longitude=via_point.longitude)
        edges[f"e-{i}-out"] = _edge(f"e-{i}-out", "o", via_id, origin, via_point, **overrides)
        edges[f"e-{i}-in"] = _edge(f"e-{i}-in", via_id, "d", via_point, destination, **overrides)
    return RoadGraph(graph_version="test", nodes=nodes, edges=edges)


async def _prepare_destination_context(generator: RouteGenerator, destination: Coordinates, radius_km: float = 20.0):
    context = await generator._engine.prepare(ORIGIN, radius_km=radius_km, waypoints=[destination])
    assert context is not None
    return context


async def test_select_via_nodes_includes_shortest_route_as_top_candidate():
    graph = build_destination_graph(ORIGIN, DESTINATION_20KM, offsets_km=[0.0, 3.0, 6.0])
    generator, _, _ = make_generator(graph)
    engine = generator._engine
    context = await _prepare_destination_context(generator, DESTINATION_20KM)

    traced = await engine.select_via_nodes(context, DESTINATION_20KM, max_routes=3)

    assert traced
    assert traced[0].data == ["e-0-out", "e-0-in"]
    assert all(t.bearing is None for t in traced)


async def test_select_via_nodes_excludes_routes_beyond_stretch_ratio():
    # offset=12kmの経路は直線比で約1.56倍（>ALTERNATIVE_MAX_STRETCH=1.3）に伸びるため
    # 候補から除外される。offset=5km（約1.06倍）は残る。
    graph = build_destination_graph(ORIGIN, DESTINATION_20KM, offsets_km=[0.0, 5.0, 12.0])
    generator, _, _ = make_generator(graph)
    engine = generator._engine
    context = await _prepare_destination_context(generator, DESTINATION_20KM)

    traced = await engine.select_via_nodes(context, DESTINATION_20KM, max_routes=10)

    returned_edge_ids = {edge_id for t in traced for edge_id in t.data}
    assert "e-2-out" not in returned_edge_ids
    assert "e-2-in" not in returned_edge_ids
    assert any("e-0-out" in t.data for t in traced)
    assert any("e-1-out" in t.data for t in traced)


async def test_select_via_nodes_collapses_same_physical_route_to_one_candidate():
    # 1本の経路をo->via0a->via0b->dの3Edgeに分割しても、どのvia-node（via0a・via0b・
    # o自身・d自身）を起点にしても同一の経路[e1,e2,e3]に潰れるため、候補は1件になる。
    mid1 = destination_point(ORIGIN, 90, 7.0)
    mid2 = destination_point(ORIGIN, 90, 13.0)
    graph = RoadGraph(
        graph_version="test",
        nodes={
            "o": Node(node_id="o", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude),
            "via0a": Node(node_id="via0a", latitude=mid1.latitude, longitude=mid1.longitude),
            "via0b": Node(node_id="via0b", latitude=mid2.latitude, longitude=mid2.longitude),
            "d": Node(node_id="d", latitude=DESTINATION_20KM.latitude, longitude=DESTINATION_20KM.longitude),
        },
        edges={
            "e1": _edge("e1", "o", "via0a", ORIGIN, mid1),
            "e2": _edge("e2", "via0a", "via0b", mid1, mid2),
            "e3": _edge("e3", "via0b", "d", mid2, DESTINATION_20KM),
        },
    )
    generator, _, _ = make_generator(graph)
    engine = generator._engine
    context = await _prepare_destination_context(generator, DESTINATION_20KM)

    traced = await engine.select_via_nodes(context, DESTINATION_20KM, max_routes=5)

    assert len(traced) == 1
    assert traced[0].data == ["e1", "e2", "e3"]


async def test_select_via_nodes_excludes_there_and_back_via_node():
    # via-node "v" は o->a->v（前向き）・v->a->d（後ろ向き）としてのみ到達可能なため、
    # 前向き・後ろ向きの両経路が同じ物理区間{a,v}を共有する（行って戻る形）。
    point_a = destination_point(ORIGIN, 90, 1.0)
    point_v = destination_point(point_a, 90, 0.1)
    graph = RoadGraph(
        graph_version="test",
        nodes={
            "o": Node(node_id="o", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude),
            "a": Node(node_id="a", latitude=point_a.latitude, longitude=point_a.longitude),
            "v": Node(node_id="v", latitude=point_v.latitude, longitude=point_v.longitude),
            "d": Node(node_id="d", latitude=DESTINATION_20KM.latitude, longitude=DESTINATION_20KM.longitude),
        },
        edges={
            "e-oa": _edge("e-oa", "o", "a", ORIGIN, point_a),
            "e-av": _edge("e-av", "a", "v", point_a, point_v),
            "e-va": _edge("e-va", "v", "a", point_v, point_a),
            "e-ad": _edge("e-ad", "a", "d", point_a, DESTINATION_20KM),
        },
    )
    generator, _, _ = make_generator(graph)
    engine = generator._engine
    context = await _prepare_destination_context(generator, DESTINATION_20KM)

    traced = await engine.select_via_nodes(context, DESTINATION_20KM, max_routes=5)

    for t in traced:
        assert not ({"e-av", "e-va"} <= set(t.data))


async def test_select_via_nodes_is_deterministic_for_tied_candidates():
    graph = build_destination_graph(ORIGIN, DESTINATION_20KM, offsets_km=[0.0, 1.0, 2.0, 3.0])
    generator, _, _ = make_generator(graph)
    engine = generator._engine
    context = await _prepare_destination_context(generator, DESTINATION_20KM)

    first = await engine.select_via_nodes(context, DESTINATION_20KM, max_routes=4)
    second = await engine.select_via_nodes(context, DESTINATION_20KM, max_routes=4)

    assert [t.data for t in first] == [t.data for t in second]


async def test_select_via_nodes_caches_reverse_search_statics_by_tile_set():
    graph = build_destination_graph(ORIGIN, DESTINATION_20KM, offsets_km=[0.0])
    tile_set = frozenset({(12, 100, 200)})
    generator, _, _ = make_generator(graph, tile_set=tile_set)
    engine = generator._engine
    context = await _prepare_destination_context(generator, DESTINATION_20KM)

    assert search_graph_cache.reverse_search_statics_cache_size() == 0
    await engine.select_via_nodes(context, DESTINATION_20KM, max_routes=1)
    assert search_graph_cache.reverse_search_statics_cache_size() == 1


async def test_select_via_nodes_returns_empty_when_destination_is_unreachable():
    # 起点側("o"-"x")と目的地側("d"-"y")が互いに繋がっていない2つの連結成分。
    # 目的地はNode自体は存在する（スナップは成功する）が、起点から到達不能。
    x_point = destination_point(ORIGIN, 0, 1.0)
    y_point = destination_point(DESTINATION_20KM, 0, 1.0)
    graph = RoadGraph(
        graph_version="test",
        nodes={
            "o": Node(node_id="o", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude),
            "x": Node(node_id="x", latitude=x_point.latitude, longitude=x_point.longitude),
            "d": Node(node_id="d", latitude=DESTINATION_20KM.latitude, longitude=DESTINATION_20KM.longitude),
            "y": Node(node_id="y", latitude=y_point.latitude, longitude=y_point.longitude),
        },
        edges={
            "e-ox": _edge("e-ox", "o", "x", ORIGIN, x_point),
            "e-dy": _edge("e-dy", "d", "y", DESTINATION_20KM, y_point),
        },
    )
    generator, _, _ = make_generator(graph)
    engine = generator._engine
    context = await _prepare_destination_context(generator, DESTINATION_20KM)

    traced = await engine.select_via_nodes(context, DESTINATION_20KM, max_routes=3)

    assert traced == []


# --- 改善計画T537: search_graph_cache（探索用グラフ・索引のタイル集合キーLRU） ---
#
# GraphService.get_search_materials_for_bboxがタイル集合を返した場合のみ、prepare/
# preview_segmentがLazyRoadGraph・NodeSpatialIndexをタイル集合（＋0次フィルタ）キーで
# キャッシュする（road_graph_engine.py: _get_or_build_lazy_graph/_get_or_build_node_index
# 参照）。FakeGraphServiceのtile_set引数で「タイルキャッシュ経由の正規パス」を模す。

_TILE_SET_A = frozenset({(12, 100, 200)})
_TILE_SET_B = frozenset({(12, 101, 200)})


async def test_prepare_reuses_cached_lazy_graph_and_node_index_for_same_tile_set():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph, tile_set=_TILE_SET_A)

    first = await generator._engine.prepare(ORIGIN, radius_km=30.0)
    second = await generator._engine.prepare(ORIGIN, radius_km=30.0)

    assert first is not None and second is not None
    # 同一タイル集合への2回目のprepareは、LazyRoadGraph・NodeSpatialIndexいずれも
    # 新規構築せずキャッシュ済みの同一オブジェクトを再利用する（アイデンティティ確認）。
    assert first.lazy_graph is second.lazy_graph
    assert first.node_index is second.node_index
    assert search_graph_cache.lazy_graph_cache_size() == 1
    assert search_graph_cache.routable_index_cache_size() == 1


async def test_prepare_builds_separately_for_different_tile_sets():
    # 起点がタイル境界付近で0次フィルタ引数が変わらなくても、GraphServiceが返す
    # タイル集合そのものが異なれば（bboxが覆うタイルが1枚ずれる等）別エントリになる
    # ことを確認する（同一集合への誤ヒットが起きない回帰テスト）。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator_a, _, _ = make_generator(graph, tile_set=_TILE_SET_A)
    generator_b, _, _ = make_generator(graph, tile_set=_TILE_SET_B)

    context_a = await generator_a._engine.prepare(ORIGIN, radius_km=30.0)
    context_b = await generator_b._engine.prepare(ORIGIN, radius_km=30.0)

    assert context_a is not None and context_b is not None
    assert context_a.lazy_graph is not context_b.lazy_graph
    assert context_a.node_index is not context_b.node_index
    assert search_graph_cache.lazy_graph_cache_size() == 2
    assert search_graph_cache.routable_index_cache_size() == 2


async def test_prepare_shares_lazy_graph_but_separates_node_index_by_hard_filters():
    # LazyRoadGraph（トポロジのみ）はタイル集合だけで決まるためhard_filtersが変わっても
    # 共有できるが、NodeSpatialIndex（0次フィルタ通過後のroutable Nodeのみ）は
    # hard_filters込みのキーで別エントリになる。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator_default, _, _ = make_generator(graph, tile_set=_TILE_SET_A)
    generator_motorway_only, _, _ = make_generator(
        graph, tile_set=_TILE_SET_A, hard_filters=frozenset({"motorway"})
    )

    context_default = await generator_default._engine.prepare(ORIGIN, radius_km=30.0)
    context_motorway_only = await generator_motorway_only._engine.prepare(ORIGIN, radius_km=30.0)

    assert context_default is not None and context_motorway_only is not None
    assert context_default.lazy_graph is context_motorway_only.lazy_graph  # タイル集合だけで共有
    assert context_default.node_index is not context_motorway_only.node_index  # hard_filtersで別
    assert search_graph_cache.lazy_graph_cache_size() == 1
    assert search_graph_cache.routable_index_cache_size() == 2


async def test_prepare_does_not_cache_when_tile_set_is_none():
    # split鮮度が古くbbox限定で再構築した経路（GraphServiceがtile_set=Noneを返す場合、
    # 通常のmake_generatorの既定）は、search_graph_cacheを一切経由せず毎回構築する
    # （不完全な集合をキャッシュへ書き込んで後続の正規リクエストを壊さないための設計、
    # graph_service.py: get_search_materials_for_bboxのtile_set docstring参照）。
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, _, _ = make_generator(graph)  # tile_set未指定=None

    first = await generator._engine.prepare(ORIGIN, radius_km=30.0)
    second = await generator._engine.prepare(ORIGIN, radius_km=30.0)

    assert first is not None and second is not None
    assert first.lazy_graph is not second.lazy_graph
    assert first.node_index is not second.node_index
    assert search_graph_cache.lazy_graph_cache_size() == 0
    assert search_graph_cache.routable_index_cache_size() == 0


async def test_prepare_caches_empty_routable_index_when_hard_filter_excludes_all_edges(monkeypatch):
    # 境界ケース: 0次フィルタでbbox内の全Edgeが除外される場合、compute_routable_node_ids
    # は空集合を返し、NodeSpatialIndexはbucketsが空のまま構築される。この「空だが正当な
    # 結果」もキャッシュされ、2回目以降はcompute_routable_node_ids/build_node_spatial_index
    # 自体を呼ばずに済むことを確認する（cache.get()がNoneを返す条件と「空の索引が
    # キャッシュ済み」を取り違えていないかの回帰）。
    node_a = Node(node_id="a", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude)
    node_b = Node(node_id="b", latitude=ORIGIN.latitude + 0.01, longitude=ORIGIN.longitude)
    coord_b = Coordinates(latitude=node_b.latitude, longitude=node_b.longitude)
    edge = _edge("e1", "a", "b", ORIGIN, coord_b, highway="motorway")  # 既定Hard Constraintで除外
    graph = RoadGraph(graph_version="test", nodes={"a": node_a, "b": node_b}, edges={"e1": edge})
    generator, _, _ = make_generator(graph, way_tags={"e1": {}}, tile_set=_TILE_SET_A)

    build_index_calls = []
    original = road_graph_engine.build_node_spatial_index

    def _counting_build_node_spatial_index(*args, **kwargs):
        build_index_calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(road_graph_engine, "build_node_spatial_index", _counting_build_node_spatial_index)

    first = await generator._engine.prepare(ORIGIN, radius_km=1.0)
    second = await generator._engine.prepare(ORIGIN, radius_km=1.0)

    # 全Edgeがmotorwayで除外され、routable Nodeが1つも無いためorigin_nodeが見つからずNone。
    assert first is None
    assert second is None
    assert len(build_index_calls) == 1  # 2回目はキャッシュヒットのため呼ばれない
    assert search_graph_cache.routable_index_cache_size() == 1


async def test_prepare_returns_none_without_touching_cache_when_graph_has_no_edges():
    # 境界ケース: bboxを覆うタイルが全て空（Edge0件）の場合、_build_search_graphは
    # 「search_materials.graph.edges」が空である時点でNoneを返し、tile_setの値に
    # 関わらずsearch_graph_cacheへは一切触れない（キャッシュを汚さない）。
    empty_graph = RoadGraph(graph_version="test", nodes={}, edges={})
    generator, _, _ = make_generator(empty_graph, tile_set=_TILE_SET_A)

    context = await generator._engine.prepare(ORIGIN, radius_km=1.0)

    assert context is None
    assert search_graph_cache.lazy_graph_cache_size() == 0
    assert search_graph_cache.routable_index_cache_size() == 0


async def test_prepare_rebuilds_stale_lazy_graph_after_resplit_cache_desync():
    # 改善計画T557（P2、項目4）: _lazy_graph_cacheと_search_statics_cacheはLRU上限
    # （既定64件）に達すると独立にpopitem(last=False)で最古のエントリを追い出すため、
    # 同じtile_setがlazy_graph側には残りsearch_statics側からは既に消えている状態が
    # 起こりうる。この状態で再split（save_graphのedge_id再割当）が挟まると、キャッシュ
    # ヒットした古いlazy_graph.edge_idsが新しいgraph.edgesに存在せず、
    # build_search_graph_statics（domain/routing.py）がKeyError相当
    # （LazyGraphEdgeMismatchError）を起こしていた。ここでは同じ状況を、
    # 1回目のprepare完了後にsearch_statics_cacheだけを手動で追い出すことで再現し、
    # 2回目のprepareが例外を出さず、新しいgraphのedge_idと整合したlazy_graphで
    # 再構築されることを確認する。
    node_a = Node(node_id="a", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude)
    node_b = Node(node_id="b", latitude=ORIGIN.latitude + 0.01, longitude=ORIGIN.longitude)
    coord_a = Coordinates(latitude=node_a.latitude, longitude=node_a.longitude)
    coord_b = Coordinates(latitude=node_b.latitude, longitude=node_b.longitude)
    graph_v1 = RoadGraph(
        graph_version="test", nodes={"a": node_a, "b": node_b},
        edges={"e1-v1": _edge("e1-v1", "a", "b", coord_a, coord_b)},
    )
    generator_v1, _, _ = make_generator(graph_v1, tile_set=_TILE_SET_A)
    first = await generator_v1._engine.prepare(ORIGIN, radius_km=1.0)
    assert first is not None
    assert list(first.lazy_graph.edge_ids) == ["e1-v1"]
    assert search_graph_cache.lazy_graph_cache_size() == 1
    assert search_graph_cache.search_statics_cache_size() == 1

    # LRUの独立追い出しを模して、search_statics側だけをキャッシュから消す
    # （lazy_graph側は残したまま）。
    search_graph_cache._search_statics_cache.clear()
    assert search_graph_cache.lazy_graph_cache_size() == 1
    assert search_graph_cache.search_statics_cache_size() == 0

    # 再split後: 同じ道（a→b）だがedge_idが振り直され、GraphServiceが返すgraphは新しい
    # edge_idのみを持つ（旧"e1-v1"は存在しない）。tile_setは変わらないため、次のprepareは
    # 古い"e1-v1"を含むlazy_graphをキャッシュヒットで再利用しようとする。
    graph_v2 = RoadGraph(
        graph_version="test", nodes={"a": node_a, "b": node_b},
        edges={"e1-v2": _edge("e1-v2", "a", "b", coord_a, coord_b)},
    )
    generator_v2, _, _ = make_generator(graph_v2, tile_set=_TILE_SET_A)

    second = await generator_v2._engine.prepare(ORIGIN, radius_km=1.0)

    assert second is not None
    assert list(second.lazy_graph.edge_ids) == ["e1-v2"]
    # 破棄→再構築されたエントリが新たにキャッシュされている。
    assert search_graph_cache.lazy_graph_cache_size() == 1
    assert search_graph_cache.search_statics_cache_size() == 1


async def test_preview_segment_never_builds_or_caches_search_statics():
    # 改善計画T569: preview_segmentは2点間の直接A*のみで一対全木（SearchGraphStatics）を
    # 使わないため、lazy_graphはキャッシュされてもsearch_statics_cacheは0件のまま。
    node_a = Node(node_id="a", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude)
    node_b = Node(node_id="b", latitude=ORIGIN.latitude + 0.01, longitude=ORIGIN.longitude)
    coord_a = Coordinates(latitude=node_a.latitude, longitude=node_a.longitude)
    coord_b = Coordinates(latitude=node_b.latitude, longitude=node_b.longitude)
    graph = RoadGraph(
        graph_version="test", nodes={"a": node_a, "b": node_b},
        edges={"e1": _edge("e1", "a", "b", coord_a, coord_b, highway="residential")},
    )
    generator, _, _ = make_generator(graph, tile_set=_TILE_SET_A, way_tags={"e1": {"highway": "residential"}})

    segment = await generator._engine.preview_segment(coord_a, coord_b)

    assert segment is not None
    assert search_graph_cache.lazy_graph_cache_size() == 1
    assert search_graph_cache.search_statics_cache_size() == 0


async def test_preview_segment_rebuilds_stale_lazy_graph_after_resplit():
    # 改善計画T569: preview_segmentもprepareと同じ整合性検証（_ensure_lazy_graph_
    # consistent）を経由するため、再split後にキャッシュヒットした古いlazy_graphの
    # edge_idが新しいgraph.edgesに存在しなくても例外を出さず、新しいgraphのedge_idと
    # 整合したlazy_graphへ再構築されることを確認する
    # （test_prepare_rebuilds_stale_lazy_graph_after_resplit_cache_desyncのpreview_segment版）。
    node_a = Node(node_id="a", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude)
    node_b = Node(node_id="b", latitude=ORIGIN.latitude + 0.01, longitude=ORIGIN.longitude)
    coord_a = Coordinates(latitude=node_a.latitude, longitude=node_a.longitude)
    coord_b = Coordinates(latitude=node_b.latitude, longitude=node_b.longitude)
    graph_v1 = RoadGraph(
        graph_version="test", nodes={"a": node_a, "b": node_b},
        edges={"e1-v1": _edge("e1-v1", "a", "b", coord_a, coord_b, highway="residential")},
    )
    generator_v1, _, _ = make_generator(
        graph_v1, tile_set=_TILE_SET_A, way_tags={"e1-v1": {"highway": "residential"}}
    )
    first = await generator_v1._engine.preview_segment(coord_a, coord_b)
    assert first is not None
    assert search_graph_cache.lazy_graph_cache_size() == 1

    # 再split後: 同じ道（a→b）だがedge_idが振り直される。tile_setは変わらないため、
    # 次のpreview_segmentは古い"e1-v1"を含むlazy_graphをキャッシュヒットで再利用しようとする。
    graph_v2 = RoadGraph(
        graph_version="test", nodes={"a": node_a, "b": node_b},
        edges={"e1-v2": _edge("e1-v2", "a", "b", coord_a, coord_b, highway="residential")},
    )
    generator_v2, _, _ = make_generator(
        graph_v2, tile_set=_TILE_SET_A, way_tags={"e1-v2": {"highway": "residential"}}
    )

    second = await generator_v2._engine.preview_segment(coord_a, coord_b)

    assert second is not None
    assert search_graph_cache.lazy_graph_cache_size() == 1
    assert search_graph_cache.search_statics_cache_size() == 0


async def test_preview_segment_reuses_cached_node_index_across_calls(monkeypatch):
    node_a = Node(node_id="a", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude)
    node_b = Node(node_id="b", latitude=ORIGIN.latitude + 0.01, longitude=ORIGIN.longitude)
    coord_a = Coordinates(latitude=node_a.latitude, longitude=node_a.longitude)
    coord_b = Coordinates(latitude=node_b.latitude, longitude=node_b.longitude)
    edge = _edge("e1", "a", "b", coord_a, coord_b, highway="residential")
    graph = RoadGraph(graph_version="test", nodes={"a": node_a, "b": node_b}, edges={"e1": edge})
    generator, _, _ = make_generator(graph, way_tags={"e1": {}}, tile_set=_TILE_SET_A)

    build_index_calls = []
    original = road_graph_engine.build_node_spatial_index

    def _counting_build_node_spatial_index(*args, **kwargs):
        build_index_calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(road_graph_engine, "build_node_spatial_index", _counting_build_node_spatial_index)

    first = await generator._engine.preview_segment(coord_a, coord_b)
    second = await generator._engine.preview_segment(coord_a, coord_b)

    assert first is not None and second is not None
    assert len(build_index_calls) == 1
    assert search_graph_cache.routable_index_cache_size() == 1


def _build_context_score_fields(
    graph: RoadGraph,
    materials: dict,
    preference: RoutePreference,
    *,
    weather: WeatherConditions | None = None,
    night_active: bool = False,
    accident_years_covered: int = 0,
    penalty_strength: float = 1.0,
    wind_series: WindForecastSeries | None = None,
    origin: Coordinates = ORIGIN,
) -> dict:
    """`_RoadGraphContext`を`prepare()`を経由せず直接構築するテスト
    （`_build_segment_details`・`_build_best_candidate`の単体テスト）向けに、
    `composer`/`legs`/`full_edge_row`を`RoadGraphEngine._build_search_graph`と同じ計算経路
    （`build_static_edge_score_matrix`→`_LegCostComposer.compose`）で構築する。
    `node_lat`/`node_lon`はA*のestimate_cost_fn用で、これらのテストはA*探索本体を
    経由しないため空配列でよい（cost_listの行順も`score_matrix.edge_ids`と同じ恒等索引）。
    """
    score_matrix = build_static_edge_score_matrix(graph, materials, accident_years_covered)
    active_scopes = frozenset({"night_only"}) if night_active else frozenset()
    weights = preference.with_time_scope(active_scopes).weights
    hard_filter_excluded = compute_hard_filter_excluded(
        score_matrix.is_motorway, score_matrix.is_trunk, score_matrix.no_bicycle, score_matrix.gradient_percent,
    )
    composer = road_graph_engine._LegCostComposer(
        score_matrix, weights, penalty_strength, hard_filter_excluded, weather, wind_series,
        datetime(2026, 9, 5, 9, 0), ASSUMED_SPEED_KMH, np.arange(len(score_matrix.edge_ids)),
    )
    full_edge_row = {edge_id: i for i, edge_id in enumerate(score_matrix.edge_ids)}

    return dict(
        composer=composer,
        legs=[composer.compose("outbound", origin, 0.0, +1)],
        # 一対全木用（これらのテストはselect_loop_turnaroundsを経由しないため
        # statics=None・origin_index=0のダミーでよい）。tile_set=Noneも同じ理由。
        statics=None,
        origin_index=0,
        tile_set=None,
        full_edge_row=full_edge_row,
        origin=origin,
        node_lat=np.array([]),
        node_lon=np.array([]),
    )


async def test_build_segment_details_night_difficulty_follows_context_night_active():
    node_a = Node(node_id="a", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude)
    node_b = Node(node_id="b", latitude=ORIGIN.latitude + 0.01, longitude=ORIGIN.longitude)
    coord_b = Coordinates(latitude=node_b.latitude, longitude=node_b.longitude)
    edge = _edge("e1", "a", "b", ORIGIN, coord_b, highway="residential")
    way_tags = {"e1": {}}
    preference = RoutePreference(
        weights={"gradient": 0.0, "wind": 0.0, "surface_q": 0.0, "stop_density": 0.0,
                 "car_stress": 0.0, "accident": 0.0, "night": 1.0, "bicycle_infra_quality": 0.0}
    )
    generator, _, _ = make_generator(None, way_tags=way_tags, route_preference=preference)
    engine = generator._engine

    base_graph = RoadGraph(graph_version="test", nodes={"a": node_a, "b": node_b}, edges={"e1": edge})
    materials = {
        "e1": EdgeMaterialBundle(
            surface=None, way_tags=way_tags["e1"], attribute_counts=None,
            elevation_attribute=None, is_designated=False,
        )
    }
    base_kwargs = dict(
        graph=base_graph,
        materials=materials, accident_years_covered=0,
        weather=None, origin_node="a",
        node_index=build_node_spatial_index(base_graph),
        lazy_graph=None,
    )
    day_context = road_graph_engine._RoadGraphContext(
        **base_kwargs, night_active=False,
        **_build_context_score_fields(base_graph, materials, preference, night_active=False),
    )
    night_context = road_graph_engine._RoadGraphContext(
        **base_kwargs, night_active=True,
        **_build_context_score_fields(base_graph, materials, preference, night_active=True),
    )

    day_segments = engine._build_segment_details([edge], {}, day_context, datetime.now(timezone.utc), [0])
    night_segments = engine._build_segment_details([edge], {}, night_context, datetime.now(timezone.utc), [0])

    # night_weight=1.0のみ有効な本ケースでは、日中はcompositeを合成できる重みが1つも
    # 無くなり（他の軸は重み0）Noneに、夜間はnight_difficulty(50.0)そのものになる。
    assert day_segments[0].difficulty is None
    assert night_segments[0].difficulty == 50.0


# --- 改善計画T237: preview_segment（/api/routes/previewのroad_graphエンジン対応） ---


async def test_preview_segment_returns_route_segment_when_path_exists():
    node_a = Node(node_id="a", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude)
    node_b = Node(node_id="b", latitude=ORIGIN.latitude + 0.01, longitude=ORIGIN.longitude)
    node_c = Node(node_id="c", latitude=ORIGIN.latitude + 0.02, longitude=ORIGIN.longitude)
    coord_a = Coordinates(latitude=node_a.latitude, longitude=node_a.longitude)
    coord_b = Coordinates(latitude=node_b.latitude, longitude=node_b.longitude)
    coord_c = Coordinates(latitude=node_c.latitude, longitude=node_c.longitude)
    edge_ab = _edge("e-ab", "a", "b", coord_a, coord_b, highway="residential")
    edge_bc = _edge("e-bc", "b", "c", coord_b, coord_c, highway="residential")
    graph = RoadGraph(graph_version="test", nodes={"a": node_a, "b": node_b, "c": node_c}, edges={"e-ab": edge_ab, "e-bc": edge_bc})
    way_tags = {"e-ab": {"highway": "residential"}, "e-bc": {"highway": "residential"}}

    generator, _, _ = make_generator(graph, way_tags=way_tags)

    segment = await generator._engine.preview_segment(coord_a, coord_c)

    assert segment is not None
    expected_km = round((edge_ab.distance_m + edge_bc.distance_m) / 1000, 2)
    assert segment.distance_km == expected_km
    assert segment.duration_minutes > 0
    assert segment.geometry["type"] == "LineString"


async def test_preview_segment_returns_none_when_no_path_exists():
    node_a = Node(node_id="a", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude)
    node_b = Node(node_id="b", latitude=ORIGIN.latitude + 0.01, longitude=ORIGIN.longitude)
    # cは他のどのEdgeとも繋がっていない孤立Node（destinationが到達不能なケースを再現）。
    node_c = Node(node_id="c", latitude=ORIGIN.latitude + 1.0, longitude=ORIGIN.longitude + 1.0)
    coord_a = Coordinates(latitude=node_a.latitude, longitude=node_a.longitude)
    coord_b = Coordinates(latitude=node_b.latitude, longitude=node_b.longitude)
    coord_c = Coordinates(latitude=node_c.latitude, longitude=node_c.longitude)
    edge_ab = _edge("e-ab", "a", "b", coord_a, coord_b, highway="residential")
    graph = RoadGraph(graph_version="test", nodes={"a": node_a, "b": node_b, "c": node_c}, edges={"e-ab": edge_ab})
    way_tags = {"e-ab": {"highway": "residential"}}

    generator, _, _ = make_generator(graph, way_tags=way_tags)

    segment = await generator._engine.preview_segment(coord_a, coord_c)

    assert segment is None


async def test_preview_segment_returns_none_when_bbox_has_no_road_data():
    generator, _, _ = make_generator(graph=None)

    segment = await generator._engine.preview_segment(ORIGIN, ORIGIN)

    assert segment is None


# --- 改善計画T274: 周回ルートの逆回り候補評価 ---


def test_reverse_traced_edges_builds_connected_reverse_path_without_new_geometry():
    # 改善計画T537: 旧`_build_node_pair_index`（bboxの全Edgeから`(from,to)→Edge`の
    # 逆引き表を毎回構築）は撤去し、`_reverse_traced_edges`はタイル集合キーで
    # キャッシュ済みの`LazyRoadGraph.edge_index_by_node_pair`を経由する
    # （road_graph_engine.pyのモジュールdocstring・_reverse_traced_edges参照）。
    # そのため本テストもgraphからbuild_lazy_road_graphで組み立てたlazy_graphを渡す。
    coord_a = destination_point(ORIGIN, 90, 1.0)
    coord_b = destination_point(ORIGIN, 90, 2.0)
    e1_fwd = _edge("e1-fwd", "o", "a", ORIGIN, coord_a)
    e2_fwd = _edge("e2-fwd", "a", "b", coord_a, coord_b)
    e1_bwd = _edge("e1-bwd", "a", "o", coord_a, ORIGIN)
    e2_bwd = _edge("e2-bwd", "b", "a", coord_b, coord_a)
    graph = RoadGraph(
        graph_version="t",
        nodes={
            "o": Node(node_id="o", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude),
            "a": Node(node_id="a", latitude=coord_a.latitude, longitude=coord_a.longitude),
            "b": Node(node_id="b", latitude=coord_b.latitude, longitude=coord_b.longitude),
        },
        edges={"e1-fwd": e1_fwd, "e2-fwd": e2_fwd, "e1-bwd": e1_bwd, "e2-bwd": e2_bwd},
    )
    lazy_graph = road_graph_engine.build_lazy_road_graph(graph)

    reverse_edges = road_graph_engine._reverse_traced_edges([e1_fwd, e2_fwd], lazy_graph, graph)

    assert reverse_edges is not None
    # 元の経路o→a→bを逆順に辿るb→a→oの順(改善計画T274)。
    assert [e.edge_id for e in reverse_edges] == ["e2-bwd", "e1-bwd"]
    assert (reverse_edges[0].from_node_id, reverse_edges[0].to_node_id) == ("b", "a")
    assert (reverse_edges[1].from_node_id, reverse_edges[1].to_node_id) == ("a", "o")
    # geometryは逆方向Edge自体からではなく、順方向で既にhydrate済みのgeometryを反転させたもの
    # （DB再取得なし）。
    assert reverse_edges[0].geometry == list(reversed(e2_fwd.geometry))
    assert reverse_edges[1].geometry == list(reversed(e1_fwd.geometry))
    # bearing_degは逆方向Edge自身のトポロジ値(lazy_graph経由でgraph.edgesから引いた値、
    # +180近似ではない)を使う。
    assert reverse_edges[0].bearing_deg == e2_bwd.bearing_deg
    assert reverse_edges[1].bearing_deg == e1_bwd.bearing_deg


def test_reverse_traced_edges_returns_none_when_any_segment_is_one_way():
    coord_a = destination_point(ORIGIN, 90, 1.0)
    e1_fwd = _edge("e1-fwd", "o", "a", ORIGIN, coord_a)
    # e1-bwdを作らない(一方通行を模す)。
    graph = RoadGraph(
        graph_version="t",
        nodes={
            "o": Node(node_id="o", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude),
            "a": Node(node_id="a", latitude=coord_a.latitude, longitude=coord_a.longitude),
        },
        edges={"e1-fwd": e1_fwd},
    )
    lazy_graph = road_graph_engine.build_lazy_road_graph(graph)

    assert road_graph_engine._reverse_traced_edges([e1_fwd], lazy_graph, graph) is None


def test_reverse_elevation_attribute_swaps_and_negates():
    forward = ElevationAttribute(
        edge_id="e-fwd", start_elevation_m=10.0, end_elevation_m=30.0,
        elevation_gain_m=20.0, elevation_loss_m=2.0, average_grade=1.8,
        max_grade=3.0, min_grade=-0.5, data_source="test", data_version="v1", calculated_at="t",
    )

    reverse = road_graph_engine._reverse_elevation_attribute(forward, "e-bwd")

    assert reverse.edge_id == "e-bwd"
    assert reverse.start_elevation_m == 30.0
    assert reverse.end_elevation_m == 10.0
    assert reverse.elevation_gain_m == 2.0
    assert reverse.elevation_loss_m == 20.0
    assert reverse.average_grade == -1.8
    assert reverse.max_grade == 0.5
    assert reverse.min_grade == -3.0
    assert reverse.data_source == "test"
    assert reverse.data_version == "v1"
    assert reverse.calculated_at == "t"


def test_reverse_elevation_attribute_preserves_all_none_when_unavailable():
    # domain/attributes.py: compute_elevation_attributeは有効な標高点が2点未満だと
    # edge_id/data_source/calculated_at以外全てNoneのまま返す。この形の入力に対しても
    # 代数変換が例外を出さずNoneを維持することを確認する。
    forward = ElevationAttribute(edge_id="e-fwd", data_source="test", calculated_at="t")

    reverse = road_graph_engine._reverse_elevation_attribute(forward, "e-bwd")

    assert reverse.start_elevation_m is None
    assert reverse.end_elevation_m is None
    assert reverse.elevation_gain_m is None
    assert reverse.elevation_loss_m is None
    assert reverse.average_grade is None
    assert reverse.max_grade is None
    assert reverse.min_grade is None


def test_reverse_elevation_attributes_maps_by_reverse_edge_id_and_skips_missing():
    coord_a = destination_point(ORIGIN, 90, 1.0)
    coord_b = destination_point(ORIGIN, 90, 2.0)
    e1_fwd = _edge("e1-fwd", "o", "a", ORIGIN, coord_a)
    e2_fwd = _edge("e2-fwd", "a", "b", coord_a, coord_b)
    e1_bwd = LeanEdge(edge_id="e1-bwd", from_node_id="a", to_node_id="o", geometry=[], distance_m=e1_fwd.distance_m)
    e2_bwd = LeanEdge(edge_id="e2-bwd", from_node_id="b", to_node_id="a", geometry=[], distance_m=e2_fwd.distance_m)
    elevation_attributes = {
        "e1-fwd": ElevationAttribute(
            edge_id="e1-fwd", start_elevation_m=0.0, end_elevation_m=10.0, data_source="t", calculated_at="t"
        ),
        # e2-fwdは標高未取得(欠落)を模す。
    }

    result = road_graph_engine._reverse_elevation_attributes(
        [e1_fwd, e2_fwd], [e2_bwd, e1_bwd], elevation_attributes
    )

    assert set(result.keys()) == {"e1-bwd"}
    assert result["e1-bwd"].start_elevation_m == 10.0
    assert result["e1-bwd"].end_elevation_m == 0.0


def _candidate_with_difficulties(difficulty_distance_pairs: list[tuple[float, float]]) -> RouteCandidate:
    segments = [
        RouteSegmentDetail(
            start_latitude=0.0, start_longitude=0.0, end_latitude=0.0, end_longitude=0.0,
            cumulative_distance_km=0.0, distance_km=distance_km, difficulty=difficulty,
        )
        for difficulty, distance_km in difficulty_distance_pairs
    ]
    return RouteCandidate(
        id="route-000", direction_label="北",
        distance_km=sum(d for _, d in difficulty_distance_pairs),
        geometry={"type": "LineString", "coordinates": []},
        segments=segments,
    )


def test_route_composite_difficulty_is_distance_weighted_average():
    candidate = _candidate_with_difficulties([(0.0, 1.0), (100.0, 3.0)])

    assert road_graph_engine._route_composite_difficulty(candidate) == 75.0


def test_route_composite_difficulty_is_none_without_segments():
    candidate = RouteCandidate(
        id="route-000", direction_label="北", distance_km=1.0,
        geometry={"type": "LineString", "coordinates": []},
    )

    assert road_graph_engine._route_composite_difficulty(candidate) is None


def test_pick_better_candidate_prefers_lower_composite_difficulty():
    easy = _candidate_with_difficulties([(10.0, 1.0)])
    hard = _candidate_with_difficulties([(90.0, 1.0)])

    assert road_graph_engine._pick_better_candidate(hard, easy) is easy
    assert road_graph_engine._pick_better_candidate(easy, hard) is easy


def test_pick_better_candidate_falls_back_to_forward_when_reverse_unavailable():
    forward = _candidate_with_difficulties([(50.0, 1.0)])
    reverse_unavailable = RouteCandidate(
        id="route-000", direction_label="北", distance_km=1.0,
        geometry={"type": "LineString", "coordinates": []},
    )  # segments=None（逆回り不成立を模す）

    assert road_graph_engine._pick_better_candidate(forward, reverse_unavailable) is forward


async def test_build_best_candidate_uses_reverse_loop_when_it_has_lower_wind_difficulty():
    # 改善計画T274の統合確認: 東向き(bearing≈90)の経路へ強い向かい風(wind_direction_deg=90、
    # 8m/s=wind軸のdifficulty上限に達する強さ)を設定すると、折り返す逆回り(西向き、追い風)の
    # 方がwind軸のdifficultyが低くなる。wind以外の重みをすべて0にし、_build_best_candidateが
    # 実際に逆回り側（起点からa→oではなくo→aの逆、つまりsegmentsの起点がaになる側）を
    # 選ぶことを確認する。
    coord_a = destination_point(ORIGIN, 90, 1.0)
    edge_fwd = _edge("e-fwd", "o", "a", ORIGIN, coord_a, highway="residential")
    edge_bwd = _edge("e-bwd", "a", "o", coord_a, ORIGIN, highway="residential")
    graph = RoadGraph(
        graph_version="test",
        nodes={
            "o": Node(node_id="o", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude),
            "a": Node(node_id="a", latitude=coord_a.latitude, longitude=coord_a.longitude),
        },
        edges={"e-fwd": edge_fwd, "e-bwd": edge_bwd},
    )
    weather = WeatherConditions(
        temperature_c=20.0, apparent_temperature_c=None, wind_speed_ms=8.0, wind_direction_deg=90.0,
        wind_direction_label="東", wind_gusts_ms=None, precipitation_probability_percent=None,
        precipitation_mm=None, uv_index=None, observed_at="t",
        weather_code=None, is_day=None,
        sunrise=None, sunset=None, precipitation_probability_max_percent=None, wind_speed_max_ms=None,
        temperature_max_c=None, temperature_min_c=None,
        uv_index_max=None, today_periods=[],
    )
    preference = RoutePreference(
        weights={"gradient": 0.0, "wind": 1.0, "surface_q": 0.0, "stop_density": 0.0,
                 "car_stress": 0.0, "accident": 0.0, "night": 0.0}
    )
    engine = RoadGraphEngine(
        graph_service=None,
        elevation_attribute_service=FakeElevationAttributeService({}),
        weather_service=FakeWeatherService(weather),
        route_preference=preference,
    )
    context = road_graph_engine._RoadGraphContext(
        graph=graph, materials={}, accident_years_covered=0,
        weather=weather, origin_node="o",
        node_index=build_node_spatial_index(graph), night_active=False,
        # 改善計画T537: _build_best_candidate→_reverse_traced_edgesがlazy_graph
        # （LazyRoadGraph.edge_index_by_node_pair）を逆回り候補の逆引きに使うため、
        # 旧`node_pair_index`引数の代わりに実際のlazy_graphを渡す。
        lazy_graph=road_graph_engine.build_lazy_road_graph(graph),
        **_build_context_score_fields(graph, {}, preference, weather=weather, night_active=False),
    )
    traced = road_graph_engine.TracedLoop(
        bearing=90, distance_km=round(edge_fwd.distance_m / 1000, 2), data=[edge_fwd]
    )

    candidate = await engine._build_best_candidate(context, traced, traced.data, datetime.now(timezone.utc))

    # 逆回り(a→o、追い風)が採用されるため、区間の始点は順方向の起点(o)ではなくa。
    assert candidate.segments[0].start_latitude == pytest.approx(coord_a.latitude)
    assert candidate.segments[0].start_longitude == pytest.approx(coord_a.longitude)
    assert candidate.wind_score is not None and candidate.wind_score < 0  # 追い風


async def test_build_best_candidate_falls_back_to_forward_when_loop_has_one_way_edge():
    # 経路中に一方通行(逆方向Edgeが存在しない)区間があれば逆回りは合成不能なため、
    # 順方向のみが返ることを確認する。
    coord_a = destination_point(ORIGIN, 90, 1.0)
    edge_fwd = _edge("e-fwd", "o", "a", ORIGIN, coord_a, highway="residential")
    graph = RoadGraph(
        graph_version="test",
        nodes={
            "o": Node(node_id="o", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude),
            "a": Node(node_id="a", latitude=coord_a.latitude, longitude=coord_a.longitude),
        },
        edges={"e-fwd": edge_fwd},
    )
    preference = RoutePreference()
    engine = RoadGraphEngine(
        graph_service=None,
        elevation_attribute_service=FakeElevationAttributeService({}),
        weather_service=FakeWeatherService(None),
        route_preference=preference,
    )
    context = road_graph_engine._RoadGraphContext(
        graph=graph, materials={}, accident_years_covered=0,
        weather=None, origin_node="o",
        node_index=build_node_spatial_index(graph), night_active=False,
        # 改善計画T537: _build_best_candidate→_reverse_traced_edgesがlazy_graph
        # （LazyRoadGraph.edge_index_by_node_pair）を逆回り候補の逆引きに使うため、
        # 旧`node_pair_index`引数の代わりに実際のlazy_graphを渡す。
        lazy_graph=road_graph_engine.build_lazy_road_graph(graph),
        **_build_context_score_fields(graph, {}, preference, weather=None, night_active=False),
    )
    traced = road_graph_engine.TracedLoop(
        bearing=90, distance_km=round(edge_fwd.distance_m / 1000, 2), data=[edge_fwd]
    )

    candidate = await engine._build_best_candidate(context, traced, traced.data, datetime.now(timezone.utc))

    assert candidate.segments[0].start_latitude == pytest.approx(ORIGIN.latitude)
    assert candidate.segments[0].start_longitude == pytest.approx(ORIGIN.longitude)


# --- 改善計画T364: 経由地(waypoints)指定ルート ---


def _chain_graph(origin: Coordinates, points: list[Coordinates]) -> RoadGraph:
    """origin→points[0]→points[1]→...→originという一本道（双方向）のRoad Graphを作る。

    ノードidは起点が"o"、points[i]が"p{i}"。各区間を双方向Edge2本（往復）で結ぶ
    （一方通行にすると逆回り不能になり別の検証観点と混ざるため、ここでは双方向にする）。
    """
    all_points = [origin, *points, origin]
    nodes = {"o": Node(node_id="o", latitude=origin.latitude, longitude=origin.longitude)}
    for i, point in enumerate(points):
        nodes[f"p{i}"] = Node(node_id=f"p{i}", latitude=point.latitude, longitude=point.longitude)
    node_ids = ["o", *[f"p{i}" for i in range(len(points))], "o"]

    edges: dict[str, DirectedEdge] = {}
    for i, (from_id, to_id) in enumerate(zip(node_ids, node_ids[1:])):
        from_coord, to_coord = all_points[i], all_points[i + 1]
        edges[f"e{i}-fwd"] = _edge(f"e{i}-fwd", from_id, to_id, from_coord, to_coord, highway="residential")
        edges[f"e{i}-bwd"] = _edge(f"e{i}-bwd", to_id, from_id, to_coord, from_coord, highway="residential")
    return RoadGraph(graph_version="test", nodes=nodes, edges=edges)


async def test_generate_via_waypoints_visits_a_single_interior_waypoint():
    point_a = destination_point(ORIGIN, 90, 1.0)
    graph = _chain_graph(ORIGIN, [point_a])
    generator, _, _ = make_generator(graph)

    candidates = await generator.generate_via_waypoints(ORIGIN, waypoints=[point_a], distance_km=2.0)

    assert len(candidates) == 1
    assert candidates[0].id == "route-waypoints"
    node_ids = [edge.from_node_id for edge in graph.edges.values()]  # sanity: グラフ自体は "o"/"p0" のみ
    assert set(node_ids) <= {"o", "p0"}


async def test_generate_via_waypoints_visits_multiple_interior_waypoints_in_order():
    point_a = destination_point(ORIGIN, 90, 1.0)
    point_b = destination_point(ORIGIN, 180, 1.0)
    point_c = destination_point(ORIGIN, 270, 1.0)
    graph = _chain_graph(ORIGIN, [point_a, point_b, point_c])
    generator, _, _ = make_generator(graph)

    candidates = await generator.generate_via_waypoints(
        ORIGIN, waypoints=[point_a, point_b, point_c], distance_km=6.0
    )

    assert len(candidates) == 1
    # 3経由地×往復2区間=6 Edgeぶんの距離になっているはず（一本道なので迂回のしようがない）。
    expected_km = round(sum(e.distance_m for e in graph.edges.values()) / 2 / 1000, 2)
    assert candidates[0].distance_km == pytest.approx(expected_km, abs=0.01)


async def test_generate_via_waypoints_with_destination_ends_at_destination_not_origin():
    # 改善計画T365: destination指定時は終点が起点に戻らない片道ルートになる。
    point_a = destination_point(ORIGIN, 90, 1.0)
    destination = destination_point(ORIGIN, 180, 1.0)
    graph = _chain_graph(ORIGIN, [point_a, destination])
    generator, _, _ = make_generator(graph)

    candidates = await generator.generate_via_waypoints(
        ORIGIN, waypoints=[point_a], distance_km=4.0, destination=destination
    )

    assert len(candidates) == 1
    assert candidates[0].id == "route-destination"
    assert candidates[0].direction_label == "目的地ルート"
    # 起点への復路（destination→o、e2-*）は通らないはず。o→p0（e0）+p0→destination（e1）
    # の2区間ぶんの距離だけになる。
    expected_km = round((graph.edges["e0-fwd"].distance_m + graph.edges["e1-fwd"].distance_m) / 1000, 2)
    assert candidates[0].distance_km == pytest.approx(expected_km, abs=0.01)


async def test_generate_via_waypoints_returns_empty_when_a_waypoint_cannot_be_snapped():
    point_a = destination_point(ORIGIN, 90, 1.0)
    unreachable = destination_point(ORIGIN, 90, 50.0)  # bboxからも大きく外れる孤立地点
    graph = _chain_graph(ORIGIN, [point_a])
    generator, _, _ = make_generator(graph)

    candidates = await generator.generate_via_waypoints(
        ORIGIN, waypoints=[point_a, unreachable], distance_km=2.0
    )

    assert candidates == []


async def test_prepare_uses_bbox_covering_waypoints_when_specified():
    # 改善計画T364: 経由地はradius_km圏外にありうるため、8方位探索と同じ
    # _bbox_around_point（起点中心の円）ではなく、preview_segmentと同じ
    # _bbox_covering_points（複数点の外接矩形）を使うことを確認する。
    far_point = destination_point(ORIGIN, 90, 20.0)  # radius_kmよりずっと遠い
    graph = _chain_graph(ORIGIN, [far_point])
    generator, graph_service, _ = make_generator(graph)

    await generator._engine.prepare(ORIGIN, radius_km=1.0, waypoints=[far_point])

    expected_bbox = road_graph_engine._bbox_covering_points(
        [ORIGIN, far_point], road_graph_engine.PREVIEW_BBOX_MARGIN_KM
    )
    assert graph_service.last_bbox == expected_bbox
    # 円形bboxだと遠方のfar_pointを覆わないことの確認（分岐が実際に効いていることの裏付け）。
    circular_bbox = road_graph_engine._bbox_around_point(ORIGIN, 1.0 + road_graph_engine.BBOX_MARGIN_MIN_KM)
    assert far_point.longitude > circular_bbox.max_longitude


async def test_prepare_uses_circular_bbox_when_no_waypoints():
    graph = build_loop_graph(ORIGIN, distance_km=30.0)
    generator, graph_service, _ = make_generator(graph)

    await generator._engine.prepare(ORIGIN, radius_km=10.0)

    expected_bbox = road_graph_engine._bbox_around_point(
        ORIGIN, 10.0 + max(road_graph_engine.BBOX_MARGIN_MIN_KM, 10.0 * road_graph_engine.BBOX_MARGIN_RATIO)
    )
    assert graph_service.last_bbox == expected_bbox


async def test_build_best_candidate_does_not_reverse_waypoint_route_even_when_reverse_is_favored():
    # 改善計画T364最重要回帰: 8方位探索と同条件（強い向かい風で逆回りの方がwind
    # difficultyが低い）でも、traced.bearing is Noneの経由地ルートでは訪問順序が要件
    # そのものなので、_build_best_candidateは逆回り合成をスキップし順方向を維持する。
    coord_a = destination_point(ORIGIN, 90, 1.0)
    edge_fwd = _edge("e-fwd", "o", "a", ORIGIN, coord_a, highway="residential")
    edge_bwd = _edge("e-bwd", "a", "o", coord_a, ORIGIN, highway="residential")
    graph = RoadGraph(
        graph_version="test",
        nodes={
            "o": Node(node_id="o", latitude=ORIGIN.latitude, longitude=ORIGIN.longitude),
            "a": Node(node_id="a", latitude=coord_a.latitude, longitude=coord_a.longitude),
        },
        edges={"e-fwd": edge_fwd, "e-bwd": edge_bwd},
    )
    weather = WeatherConditions(
        temperature_c=20.0, apparent_temperature_c=None, wind_speed_ms=8.0, wind_direction_deg=90.0,
        wind_direction_label="東", wind_gusts_ms=None, precipitation_probability_percent=None,
        precipitation_mm=None, uv_index=None, observed_at="t",
        weather_code=None, is_day=None,
        sunrise=None, sunset=None, precipitation_probability_max_percent=None, wind_speed_max_ms=None,
        temperature_max_c=None, temperature_min_c=None,
        uv_index_max=None, today_periods=[],
    )
    preference = RoutePreference(
        weights={"gradient": 0.0, "wind": 1.0, "surface_q": 0.0, "stop_density": 0.0,
                 "car_stress": 0.0, "accident": 0.0, "night": 0.0}
    )
    engine = RoadGraphEngine(
        graph_service=None,
        elevation_attribute_service=FakeElevationAttributeService({}),
        weather_service=FakeWeatherService(weather),
        route_preference=preference,
    )
    context = road_graph_engine._RoadGraphContext(
        graph=graph, materials={}, accident_years_covered=0,
        weather=weather, origin_node="o",
        node_index=build_node_spatial_index(graph), night_active=False,
        # 改善計画T537: _build_best_candidate→_reverse_traced_edgesがlazy_graph
        # （LazyRoadGraph.edge_index_by_node_pair）を逆回り候補の逆引きに使うため、
        # 旧`node_pair_index`引数の代わりに実際のlazy_graphを渡す。
        lazy_graph=road_graph_engine.build_lazy_road_graph(graph),
        **_build_context_score_fields(graph, {}, preference, weather=weather, night_active=False),
    )
    traced = road_graph_engine.TracedLoop(
        bearing=None, distance_km=round(edge_fwd.distance_m / 1000, 2), data=[edge_fwd]
    )

    candidate = await engine._build_best_candidate(context, traced, traced.data, datetime.now(timezone.utc))

    # 逆回り(a→o、追い風)の方がwind difficultyは低いはずだが、bearing=Noneなので
    # 順方向(o→a)のまま維持される。
    assert candidate.segments[0].start_latitude == pytest.approx(ORIGIN.latitude)
    assert candidate.segments[0].start_longitude == pytest.approx(ORIGIN.longitude)


# --- select_loop_turnaroundsの同点タイブレーク（_order_by_bearing_spread） ---


def _spread_fixture():
    # 車輪状に均等配置した8方位。closenessは単調増加で常に一意なタイブレークになる。
    nodes = list(range(8))
    bearing_by_node = {n: 45.0 * n for n in nodes}
    closeness_by_node = {n: float(n) for n in nodes}
    return nodes, bearing_by_node, closeness_by_node


def test_order_by_bearing_spread_uses_closeness_when_nothing_selected():
    nodes, bearing_by_node, closeness_by_node = _spread_fixture()

    ordered = road_graph_engine._order_by_bearing_spread(list(reversed(nodes)), [], bearing_by_node, closeness_by_node)

    assert ordered == nodes


def test_order_by_bearing_spread_covers_four_quadrants_when_selecting_greedily():
    # 採用済みとの角距離の最小値が最大の候補を順に採用すると、対蹠点（180°）→残り2象限の
    # 順になり、4件で必ず4象限が揃う。
    nodes, bearing_by_node, closeness_by_node = _spread_fixture()
    selected: list[int] = []
    remaining = list(nodes)
    while len(selected) < 4:
        ordered = road_graph_engine._order_by_bearing_spread(remaining, selected, bearing_by_node, closeness_by_node)
        selected.append(ordered[0])
        remaining = ordered[1:]

    assert selected[1] == 4  # 1件目（closeness最小=0°）の対蹠点
    assert {int(bearing_by_node[n] // 90) for n in selected} == {0, 1, 2, 3}


def test_order_by_bearing_spread_is_deterministic_and_breaks_ties_by_closeness_then_index():
    bearing_by_node = {10: 90.0, 11: 90.0, 12: 270.0, 13: 90.0}
    closeness_by_node = {10: 2.0, 11: 1.0, 12: 5.0, 13: 1.0}

    first = road_graph_engine._order_by_bearing_spread([10, 11, 12, 13], [0], {**bearing_by_node, 0: 0.0}, closeness_by_node)
    second = road_graph_engine._order_by_bearing_spread([13, 12, 11, 10], [0], {**bearing_by_node, 0: 0.0}, closeness_by_node)

    # 角距離はすべて90°で同値→closeness昇順（11,13は同値→index昇順）→10、12の順
    assert first == [11, 13, 10, 12]
    assert first == second
