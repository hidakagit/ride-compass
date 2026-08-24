"""Road Graph + scipy.sparse.csgraph（Dijkstra）の自前ルーティングエンジン（試験実装）。

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
- **標高（勾配）は改善計画T218a（T12 Stage 0.5）で探索コストへ組み込み済み**:
  当初はRoad Graph全体（数万Edge）への標高取得（GSI API逐次呼び出し）が非現実的に遅く、
  経路探索は標高を使わないCostで行い`evaluate_loops`（距離フィルタ通過後）でのみ標高取得
  していた。T218a以降、`prepare`は事前計算済みの`elevation_attributes`
  （`app.batch.precompute_elevation_attributes`、T10のDEMタイル方式で一括計算済み）を
  単純なキー参照で読み、`search_edge_costs`のgradient軸へ組み込む（その場でのGSI問い合わせは
  発生しない）。`evaluate_loops`側の標高取得（`ElevationAttributeService`経由、こちらは
  未計算Edgeがあればその場で取得しrepositoryへ永続化する）は、経路確定後の表示・スコアリング
  向けとして引き続き別に行う（`elevation_attributes`テーブルを両者が共有するキャッシュ層として
  参照する構図。事前計算が漏れているEdgeは探索コスト側でgradient軸のみ「データ無し」扱いに
  なるが、他の軸で評価は継続する）。
- 風は出発時点の起点付近の風をルート全体に一様適用する（探索中は到達時刻が未確定のため。
  OpenRouteServiceEngineの「区間ごとの推定到達時刻の風」とは意味が異なる点に注意。
  レスポンスの`engine`フィールドで識別できる）。
- `SparseRoadGraph`（domain/routing.py: build_sparse_graph）は同一ノード間の並行Edgeを
  1本しか保持しない（後から登場したEdgeで上書き）。稀なケースでは最安のEdgeが
  選ばれない可能性がある。
"""

import asyncio
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.domain.accident import distance_weighted_accident_density
from app.domain.axis_definitions import car_stress_display_level
from app.domain.difficulty import distance_weighted_difficulty
from app.domain.errors import RoutingError
from app.domain.evaluation import (
    RoutePreference,
    compute_cost_from_axis_scores,
    compute_edge_axis_scores,
    compute_wind_penalty,
)
from app.domain.geo import KM_PER_DEGREE_LATITUDE
from app.domain.graph import EdgeLike, LeanRoadGraph, RoadGraphLike
from app.domain.region import BoundingBox
from app.domain.road import classify_osm_surface, distance_weighted_road_score
from app.domain.route import (
    Coordinates,
    RouteCandidate,
    RouteSegment,
    RouteSegmentDetail,
    aggregate_segments_into_bins,
)
from app.domain.twilight import is_night
from app.domain.traffic import (
    classify_bicycle_infrastructure,
    distance_weighted_bicycle_infra_score,
    distance_weighted_intersection_density,
    distance_weighted_stop_density,
    is_dedicated_bicycle_infra,
)
from app.domain.routing import (
    NodeSpatialIndex,
    SparseRoadGraph,
    build_node_spatial_index,
    build_sparse_graph,
    concat_node_paths,
    find_nearest_node_indexed,
    path_to_edge_ids_sparse,
    routable_node_ids,
    shortest_path_node_ids_sparse,
)
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

# 改善計画T237: preview_segment（起点・終点2点間の単発経路確認）が使うbboxマージン。
# ループ探索のBBOX_MARGIN_MIN_KMと同じ「道なりが直線外接矩形からはみ出る余裕」を
# 単純な固定値で持たせる（previewは距離が事前に分からないため半径比例のロジックは使えない）。
PREVIEW_BBOX_MARGIN_KM = 2.0


@dataclass
class _RoadGraphContext:
    """prepareで構築し、全方位のtrace_loop/evaluate_loopsで共有するリクエスト単位の状態。"""

    graph: RoadGraphLike
    surface_attributes: dict[str, str | None]
    stop_counts: dict[str, int]
    way_tags: dict[str, dict[str, str]]
    intersection_counts: dict[str, int]
    accident_counts: dict[str, int]
    accident_years_covered: int
    designated_edge_ids: set[str]
    wind: WeatherConditions | None
    origin_node: str
    # 改善計画T219（T12 Stage 1）: 1リクエストにつき最大17回呼ばれるfind_nearest_node相当を
    # 都度線形探索せず使い回すための索引（domain/routing.py参照）。
    node_index: NodeSpatialIndex
    # 改善計画T220（T12 Stage 2）: trace_loopが実際のDijkstraに使うscipy版グラフ。探索本体は
    # 常にこちらを使う（road_graph_engine.pyモジュールdocstring参照）。旧nx_graphフィールドは
    # ランタイムで誰にも読まれていなかったため改善計画T226で削除済み（domain/routing.pyの
    # NetworkX系関数自体はsparse版の回帰テストオラクルとして引き続き存在する）。
    sparse_graph: SparseRoadGraph
    # 改善計画T173: prepare実行時点で起点が市民薄明の外（夜間）だったかどうか。search_edge_costs
    # 構築時に使った値と同じものを_build_segment_details（表示用difficulty）でも使い、探索コストと
    # 表示を一致させる（詳細はprepare()参照）。
    night_active: bool


@dataclass
class _SearchGraph:
    """`prepare`・`preview_segment`共通の「bboxに対する探索用グラフ＋材料一式」
    （改善計画T237）。wind/night軸・0次ハードフィルタ等の探索コスト算出ロジックを
    `_build_search_graph`1箇所にまとめ、ループ探索・単発区間確認の両方で重複させない。
    """

    graph: RoadGraphLike
    sparse_graph: SparseRoadGraph
    surface_attributes: dict[str, str | None]
    stop_counts: dict[str, int]
    way_tags: dict[str, dict[str, str]]
    intersection_counts: dict[str, int]
    accident_counts: dict[str, int]
    accident_years_covered: int
    designated_edge_ids: set[str]
    wind: WeatherConditions | None
    night_active: bool


class RoadGraphEngine:
    engine_name = "road_graph"

    def __init__(
        self,
        graph_service: GraphService,
        elevation_attribute_service: ElevationAttributeService,
        evaluation_service: EvaluationService,
        weather_service: WeatherService,
        route_preference: RoutePreference,
        penalty_strength: float = 1.0,
        max_average_grade_percent: float | None = None,
        hard_filters: frozenset[str] | None = None,
    ):
        self._graph_service = graph_service
        self._elevation_attribute_service = elevation_attribute_service
        self._evaluation_service = evaluation_service
        self._weather_service = weather_service
        self._route_preference = route_preference
        # 改善計画T218・T12 ADR原則1: コスト式`distance × (1 + P × difficulty/100)`のP。
        # 既定1.0は従来どおりの挙動（最悪でも距離2倍）。
        self._penalty_strength = penalty_strength
        # 改善計画T218a・T12 ADR原則5: 0次ハードフィルタの勾配しきい値（%、既定None＝
        # 除外しない）。domain/evaluation.py: is_edge_allowed参照。
        self._max_average_grade_percent = max_average_grade_percent
        # 改善計画T266: 0次ハードフィルタ名（no_bicycle/motorway/trunk）の個別ON/OFF上書き
        # （既定None＝DEFAULT_HARD_FILTERS＝全フィルタ有効）。
        self._hard_filters = hard_filters

    async def _build_search_graph(
        self, bbox: BoundingBox, wind_and_night_origin: Coordinates, now: datetime
    ) -> _SearchGraph | None:
        """bboxに対する探索用グラフ（sparse_graph）＋材料一式を構築する（改善計画T237、
        `prepare`・`preview_segment`共通）。wind/night軸の判定は`wind_and_night_origin`
        （周回ならその起点、区間確認なら起点側の座標）を基準にする——探索中は到達時刻が
        未確定のため出発時刻の近似として使う簡略化はどちらの用途でも変わらない
        （モジュールdocstring参照）。
        """
        # 改善計画T219（T12 Stage 1）: トポロジ＋材料（surface/edge_attribute_counts/
        # way_tags/elevation_attributes/designated_edge_ids）をz12タイル単位のプロセス内
        # キャッシュ経由でまとめて取得する（同一エリアへの2回目以降のリクエストはDBへ
        # 一切アクセスしない。以前はここで6回の個別呼び出しを行っていた、
        # graph_service.pyのget_search_materials_for_bbox参照）。
        materials = await self._graph_service.get_search_materials_for_bbox(bbox)
        if materials is None or not materials.graph.edges:
            return None
        graph = materials.graph
        surface_attributes = materials.surface_attributes
        # 静的道路属性P1（信号・横断歩道・一時停止・踏切・交差点密度）＋外部静的データ
        # ソースT50（事故密度）。事前集計済みのedge_attribute_counts（改善計画T144）が
        # 3種の値をまとめて持つため、evaluate_graph等の呼び出し先シグネチャ（従来どおり
        # 3つの個別dictを受け取る）に合わせてここで分解する。
        stop_counts = {edge_id: c.stop_count for edge_id, c in materials.edge_attribute_counts.items()}
        intersection_counts = {
            edge_id: c.intersection_count for edge_id, c in materials.edge_attribute_counts.items()
        }
        accident_counts = {edge_id: c.accident_count for edge_id, c in materials.edge_attribute_counts.items()}
        way_tags = materials.way_tags
        # accident_years_coveredは密度の「件/(km・年)」正規化に使う（bboxに依存しない
        # グローバル値、GraphService側でプロセス内キャッシュ済み）。
        accident_years_covered = await self._graph_service.get_accident_years_covered()
        designated_edge_ids = materials.designated_edge_ids
        # 改善計画T218a（T12 Stage 0.5）: 事前計算済みのgradient（average_grade）を探索コストへ
        # 組み込む。`app.batch.precompute_elevation_attributes`で事前計算済みのEdgeのみ値が
        # 埋まる（未計算のEdgeはNoneのまま=評価スキップ、compute_edge_axis_scoresの既存の
        # 「データ無しは軸を合成から除外」動作に委ねる）。
        elevation_attributes = materials.elevation_attributes

        wind = await self._weather_service.get_conditions(wind_and_night_origin)
        # 改善計画T173: night軸の動的化。区間ごとの到達時刻は探索中は未確定のため（風と
        # 同じモジュールdocstringの制約）、出発地点の座標・呼び出し時点を出発時刻の近似として
        # 採用し、起点が市民薄明の外（夜間）ならnight_weightをそのまま、日中なら0倍にした
        # RoutePreferenceのコピーを探索コストへ渡す（self._route_preference自体は
        # 書き換えない、リクエスト間で共有される状態のため）。
        night_active = is_night(wind_and_night_origin, now)
        search_preference = (
            self._route_preference
            if night_active
            else self._route_preference.with_weight("night", 0.0)
        )
        # 改善計画T218a: 探索用Costへ事前計算済みgradientを組み込む（モジュールdocstring参照）。
        search_edge_costs = self._evaluation_service.evaluate_graph(
            graph, elevation_attributes, surface_attributes, wind=wind, stop_counts=stop_counts,
            way_tags=way_tags, intersection_counts=intersection_counts,
            accident_counts=accident_counts, accident_years_covered=accident_years_covered,
            designated_edge_ids=designated_edge_ids, preference=search_preference,
            penalty_strength=self._penalty_strength,
            max_average_grade_percent=self._max_average_grade_percent,
            hard_filters=self._hard_filters,
        )
        sparse_graph = build_sparse_graph(graph, search_edge_costs)

        return _SearchGraph(
            graph=graph,
            sparse_graph=sparse_graph,
            surface_attributes=surface_attributes,
            stop_counts=stop_counts,
            way_tags=way_tags,
            intersection_counts=intersection_counts,
            accident_counts=accident_counts,
            accident_years_covered=accident_years_covered,
            designated_edge_ids=designated_edge_ids,
            wind=wind,
            night_active=night_active,
        )

    async def prepare(
        self, origin: Coordinates, radius_km: float, now: datetime | None = None
    ) -> _RoadGraphContext | None:
        # nowは改善計画T173のnight軸判定用（省略時は実際の現在時刻）。テストが任意の時刻を
        # 注入できるよう引数化した（wind同様、探索中は到達時刻が未確定のためprepare実行時点を
        # 出発時刻の近似として使う簡略化、詳細は_build_search_graph参照）。
        now = now or datetime.now(timezone.utc)
        margin_km = max(BBOX_MARGIN_MIN_KM, radius_km * BBOX_MARGIN_RATIO)
        bbox = _bbox_around_point(origin, radius_km + margin_km)

        search = await self._build_search_graph(bbox, origin, now)
        if search is None:
            return None

        # 改善計画T219: このgraphに対する索引を1回だけ構築し、原点＋trace_loopの
        # 経由地スナップ（1リクエストで最大17回）すべてで使い回す。
        # 改善計画T256: 索引の候補はsparse_graph上で実際に経路探索可能な（Hard
        # Constraint通過後も次数1以上の）Nodeのみに絞る。絞らないと、幹線道路
        # （highway=trunk等）にしか接続していない地理的最近傍Node（新宿駅・渋谷駅等、
        # 駅前が国道の交差点に直接面する場所で実機確認）が選ばれ、そこがHard Constraint
        # 除外後のグラフ上では孤立点になるため、8方位すべてのDijkstra探索が
        # "no path found"で失敗してしまう。
        node_index = build_node_spatial_index(search.graph, node_ids=routable_node_ids(search.sparse_graph))
        origin_node = find_nearest_node_indexed(node_index, origin)
        if origin_node is None:
            return None

        return _RoadGraphContext(
            graph=search.graph,
            sparse_graph=search.sparse_graph,
            surface_attributes=search.surface_attributes,
            stop_counts=search.stop_counts,
            way_tags=search.way_tags,
            intersection_counts=search.intersection_counts,
            accident_counts=search.accident_counts,
            accident_years_covered=search.accident_years_covered,
            designated_edge_ids=search.designated_edge_ids,
            wind=search.wind,
            origin_node=origin_node,
            node_index=node_index,
            night_active=search.night_active,
        )

    async def preview_segment(
        self, origin: Coordinates, destination: Coordinates, now: datetime | None = None
    ) -> RouteSegment | None:
        """起点・終点2点間の単発区間確認（`/api/routes/preview`、改善計画T237）。

        `prepare`＋`trace_loop`（周回・3レグ探索）とは異なり、1回の最短経路探索のみを行う。
        探索コストは`generate`と同じ評価軸重み付き（`RoutePreference`）を使う——ORSの
        previewのような単純最短距離ではなく、`penalty_strength`等の研究パラメータも含めて
        generateと一貫した経路選択にする（2026-08-23、ユーザー確認済みの設計判断）。
        経路が見つからない場合はNoneを返す（呼び出し元がRoutingErrorへ変換する）。
        """
        now = now or datetime.now(timezone.utc)
        bbox = _bbox_covering_points([origin, destination], PREVIEW_BBOX_MARGIN_KM)

        search = await self._build_search_graph(bbox, origin, now)
        if search is None:
            return None

        # 改善計画T256: prepareと同じ理由で、索引の候補をsparse_graph上で経路探索可能な
        # Nodeのみに絞る（幹線道路にしか接続していない孤立Nodeを除外）。
        node_index = build_node_spatial_index(search.graph, node_ids=routable_node_ids(search.sparse_graph))
        origin_node = find_nearest_node_indexed(node_index, origin)
        destination_node = find_nearest_node_indexed(node_index, destination)
        if origin_node is None or destination_node is None:
            return None

        path = shortest_path_node_ids_sparse(search.sparse_graph, origin_node, destination_node)
        if path is None:
            return None
        edge_ids = path_to_edge_ids_sparse(search.sparse_graph, path)
        if not edge_ids:
            return None

        # 改善計画T218（T12 Stage 0）と同じレイジー取得（prepareがlean=Trueで読み込んだ
        # search.graphのEdgeはgeometryが空プレースホルダのため、この経路ぶんだけ取得し直す）。
        hydrated = await self._graph_service.get_edges_with_geometry(edge_ids)
        edges_in_path: list[EdgeLike] = [hydrated.get(edge_id) or search.graph.edges[edge_id] for edge_id in edge_ids]

        distance_km = round(sum(edge.distance_m for edge in edges_in_path) / 1000, 2)
        geometry = _concat_edge_geometries(edges_in_path)
        # road_graphエンジンは実測所要時間モデルを持たないため、他所（segments構築時の
        # estimated_arrival_time）と同じASSUMED_SPEED_KMHで概算する。
        duration_minutes = round(distance_km / ASSUMED_SPEED_KMH * 60, 1)

        return RouteSegment(distance_km=distance_km, duration_minutes=duration_minutes, geometry=geometry)

    async def trace_loop(
        self, context: _RoadGraphContext, waypoints: list[Coordinates], bearing: int
    ) -> TracedLoop:
        # waypoints = [起点, 経由地A, 経由地B, 起点]（RouteGenerator._loop_waypoints）。
        # 起点は最近接NodeをprepareでスナップしたNodeを使い、経由地2点をここでスナップする
        # （改善計画T219: prepareで構築済みの索引を使い回す、都度線形探索しない）。
        node_a = find_nearest_node_indexed(context.node_index, waypoints[1])
        node_b = find_nearest_node_indexed(context.node_index, waypoints[2])
        if node_a is None or node_b is None:
            raise RoutingError(f"direction {bearing}: could not snap waypoints to road graph")

        # 改善計画T220（T12 Stage 2）: Dijkstra本体はNetworkX（Python実装）ではなく
        # scipy.sparse.csgraph（C実装）で行う（1リクエストにつき最大24回、実測で
        # ボトルネックと判明。モジュールdocstring参照）。context.sparse_graphを使う。
        path_1 = shortest_path_node_ids_sparse(context.sparse_graph, context.origin_node, node_a)
        path_2 = shortest_path_node_ids_sparse(context.sparse_graph, node_a, node_b)
        path_3 = shortest_path_node_ids_sparse(context.sparse_graph, node_b, context.origin_node)
        if path_1 is None or path_2 is None or path_3 is None:
            raise RoutingError(f"direction {bearing}: no path found between waypoints")

        full_path = concat_node_paths([path_1, path_2, path_3])
        edge_ids = path_to_edge_ids_sparse(context.sparse_graph, full_path)
        if not edge_ids:
            raise RoutingError(f"direction {bearing}: resulting path has no edges")
        # 改善計画T218（T12 Stage 0）: prepareがlean=Trueで読み込んだcontext.graphの
        # Edgeはgeometryが空プレースホルダのため、区間表示・標高取得等（後段の
        # _build_candidate）に使う実ジオメトリをこの経路ぶん（数十〜数百Edge）だけ
        # 取得し直す。Overpass経由構築時（context.graphが元々フルジオメトリ）は
        # get_edges_with_geometryが空辞書を返すため、そちらのcontext.graph側の値を使う。
        hydrated = await self._graph_service.get_edges_with_geometry(edge_ids)
        edges_in_path: list[EdgeLike] = [hydrated.get(edge_id) or context.graph.edges[edge_id] for edge_id in edge_ids]

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
        edges_in_path: list[EdgeLike] = traced.data

        # 改善計画T248: ElevationAttributeService.get_attributes_for_graphは
        # graph.edgesしか読まない（nodesは未参照）ため、nodesは空でよい。
        # context.graph.nodes（LeanNode、数万件規模）をそのまま渡すとPydantic
        # RoadGraphのフィールド型（dict[str, Node]）検証に失敗するため、
        # バリデーションを行わないLeanRoadGraphを使う（edges_in_pathは通常
        # hydrated＝Pydantic DirectedEdgeだが、稀なフォールバック時のLeanEdgeが
        # 混在してもLeanRoadGraphなら型検証エラーにならない）。
        path_graph = LeanRoadGraph(
            graph_version=context.graph.graph_version,
            nodes={},
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
        # ルート全体の集約値（car_stress_score等）はビン化前のEdge単位segmentsから計算する
        # （ビン単位のcar_stress自体が既に丸め済みのため、ビン後の値を使うと丸め誤差が
        # 二重に乗ってしまう。改善計画T11）。
        car_stress_score = distance_weighted_difficulty(
            [(s.car_stress, s.distance_km) for s in segments]
        )
        bicycle_infra_score = distance_weighted_bicycle_infra_score(
            [(s.distance_km, is_dedicated_bicycle_infra(s.bicycle_infra)) for s in segments]
        )
        # 改善計画T11（レビュー指摘M3）: APIレスポンスとして返すsegmentsは約500m単位に
        # 集約する（Edge単位のままだと30km級で150〜230件になりペイロード・フロント
        # 描画コストが嵩む）。
        segments = aggregate_segments_into_bins(segments)

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
        edges: list[EdgeLike],
        elevation_attributes: dict,
        context: _RoadGraphContext,
        start_time: datetime,
    ) -> list[RouteSegmentDetail]:
        # 改善計画T79: 以前は11個の位置引数を取り、うち8個はcontextフィールドの単純展開
        # だった（同型dict[str, int]が3つ並び、順序取り違えが検知されない構造）。
        # edges・elevation_attributes・start_timeはcontextに無いリクエスト単位の値
        # （edges=方位ごとの経路、elevation_attributes=経路確定後に取得、start_time=呼び出し元
        # 引数）のため、これらだけを個別引数として残しcontextを1引数で渡す。
        # 改善計画T173: night_weightはcontext.night_active（prepare時点の判定、探索コストで
        # 使ったものと同一）で0倍にする。表示（本関数）と探索コストが食い違わないようにする。
        preference = (
            self._route_preference
            if context.night_active
            else self._route_preference.with_weight("night", 0.0)
        )
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
            )
            # 改善計画T292: car_stress（1-5の生値、将来の色分けモード等での利用に備えて
            # domain/route.py: RouteSegmentDetailが保持するdisplayフィールド）は、専用
            # レシピ（旧car_stress_level）廃止後、公開軸car_stressのdifficulty(0-100)を
            # car_stress_display_levelで逆変換して求める（openrouteservice_engine.pyと共通）。
            car_stress_difficulty = axis_scores.get("car_stress")
            car_stress = car_stress_display_level(car_stress_difficulty)
            weights = preference.weights
            _, composite_difficulty_value = compute_cost_from_axis_scores(
                edge.distance_m, axis_scores, weights, self._penalty_strength
            )

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
    """centerを中心とした半径radius_kmの円を覆う矩形bboxを求める（1回のRoad Graph取得で
    8方位全ての経由地点をカバーするため、方位ごとではなく起点1つに対して1回だけ計算する）。"""
    lat_margin_deg = radius_km / KM_PER_DEGREE_LATITUDE
    lon_margin_deg = radius_km / (KM_PER_DEGREE_LATITUDE * max(math.cos(math.radians(center.latitude)), 1e-6))
    return BoundingBox(
        min_latitude=center.latitude - lat_margin_deg,
        max_latitude=center.latitude + lat_margin_deg,
        min_longitude=center.longitude - lon_margin_deg,
        max_longitude=center.longitude + lon_margin_deg,
    )


def _bbox_covering_points(points: list[Coordinates], margin_km: float) -> BoundingBox:
    """複数地点すべてを覆う外接矩形に、margin_kmの余裕を足したbboxを求める（改善計画T237、
    `preview_segment`の起点・終点2点用）。`_bbox_around_point`と異なり中心・半径ではなく
    点集合の外接矩形が起点になる点が違うだけで、マージンの度数換算は同じ
    （`KM_PER_DEGREE_LATITUDE`ベース）。"""
    center_lat = sum(p.latitude for p in points) / len(points)
    lat_margin_deg = margin_km / KM_PER_DEGREE_LATITUDE
    lon_margin_deg = margin_km / (KM_PER_DEGREE_LATITUDE * max(math.cos(math.radians(center_lat)), 1e-6))
    return BoundingBox(
        min_latitude=min(p.latitude for p in points) - lat_margin_deg,
        max_latitude=max(p.latitude for p in points) + lat_margin_deg,
        min_longitude=min(p.longitude for p in points) - lon_margin_deg,
        max_longitude=max(p.longitude for p in points) + lon_margin_deg,
    )


def _concat_edge_geometries(edges: list[EdgeLike]) -> dict:
    """経路上のEdge群をひとつながりのGeoJSON LineStringへ変換する。隣接するEdgeの
    境界点（前Edgeの終端＝次Edgeの始端）は重複させない。"""
    coordinates: list[list[float]] = []
    for edge in edges:
        points = [[lon, lat] for lat, lon in edge.geometry]
        if coordinates and points and coordinates[-1] == points[0]:
            points = points[1:]
        coordinates.extend(points)
    return {"type": "LineString", "coordinates": coordinates}


def _aggregate_elevation(edges: list[EdgeLike], elevation_attributes: dict) -> dict:
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


def _aggregate_road_score(edges: list[EdgeLike], surface_attributes: dict[str, str | None]) -> float | None:
    """経路の総距離に対する「走行しやすい舗装路面」の割合(%)を算出する。Edge単位のsurfaceタグを
    domain/road.py: distance_weighted_road_score（両エンジン共通の集約定義、改善計画T21）へ渡す薄いラッパー。
    """
    return distance_weighted_road_score(
        [(edge.distance_m, classify_osm_surface(surface_attributes.get(edge.edge_id))) for edge in edges]
    )


def _aggregate_stop_density(edges: list[EdgeLike], stop_counts: dict[str, int]) -> float | None:
    """経路全体の信号・横断歩道・一時停止・踏切の合計密度(回/km)。Edge単位のカウントを
    domain/traffic.py: distance_weighted_stop_density（両エンジン共通の集約定義、
    静的道路属性P1）へ渡す薄いラッパー。stop_countsに無いEdge（repository未注入等で
    データ自体を取得していない）はNone扱いとし、distance_weighted_stop_density側で
    「実測0件」と区別して除外される（road_score等の「不明はNone」と同じ方針）。
    """
    return distance_weighted_stop_density(
        [(edge.distance_m / 1000, stop_counts.get(edge.edge_id)) for edge in edges]
    )


def _aggregate_intersection_density(edges: list[EdgeLike], intersection_counts: dict[str, int]) -> float | None:
    """経路全体の交差点（次数3以上のNode）の合計密度(回/km)。_aggregate_stop_densityと
    同じ薄いラッパー（静的道路属性P1残り、intersectionDensity）。
    """
    return distance_weighted_intersection_density(
        [(edge.distance_m / 1000, intersection_counts.get(edge.edge_id)) for edge in edges]
    )


def _aggregate_accident_density(
    edges: list[EdgeLike], accident_counts: dict[str, int], accident_years_covered: int
) -> float | None:
    """経路全体の事故密度(件/(km・年))。_aggregate_stop_density/_aggregate_intersection_density
    と同じ薄いラッパー（外部静的データソース T50残作業、8軸目）。
    """
    return distance_weighted_accident_density(
        [(edge.distance_m / 1000, accident_counts.get(edge.edge_id)) for edge in edges], accident_years_covered
    )


def _aggregate_wind_score(edges: list[EdgeLike], wind: WeatherConditions | None) -> float | None:
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
