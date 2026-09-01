"""Road Graph + rustworkx（A*/Dijkstra、lazy評価）の自前ルーティングエンジン。

`RouteGenerator`（services/route_generator.py）の`LoopRoutingEngine`契約を実装する。
Road Graph・Evaluation Engine・Route Engine（domain/routing.py）を使って経由地点間の
経路を自前で計算する。ルート生成の唯一のエンジン実装。

設計上の重要な決定（実機検証で判明した問題への対応）:
- **Overpassへの問い合わせは1回だけ**: 8方位が個別にbboxを計算して並列問い合わせすると
  公開インスタンスに拒否され全滅することを実機確認したため、起点を中心とした単一の円
  （8方位分の経由地点をすべて覆う半径）でRoad Graphを`prepare`で1回だけ取得し、
  全方位で共有する。
- **標高（勾配）は改善計画T218a（T12 Stage 0.5）で探索コストへ組み込み済み**:
  当初はRoad Graph全体（数万Edge）への標高取得（GSI API逐次呼び出し）が非現実的に遅く、
  経路探索は標高を使わないCostで行い`evaluate_loops`（距離フィルタ通過後）でのみ標高取得
  していた。T218a以降、探索コストは事前計算済みの`elevation_attributes`
  （`app.batch.precompute_elevation_attributes`、T10のDEMタイル方式で一括計算済み）を
  単純なキー参照で読み、gradient軸へ組み込む（その場でのGSI問い合わせは発生しない）。
  `evaluate_loops`側の標高取得（`ElevationAttributeService`経由、こちらは未計算Edgeが
  あればその場で取得しrepositoryへ永続化する）は、経路確定後の表示・スコアリング向けとして
  引き続き別に行う（`elevation_attributes`テーブルを両者が共有するキャッシュ層として
  参照する構図。事前計算が漏れているEdgeは探索コスト側でgradient軸のみ「データ無し」扱いに
  なるが、他の軸で評価は継続する）。
- 風は出発時点の起点付近の風をルート全体に一様適用する（探索中は到達時刻が未確定のため、
  区間ごとの推定到達時刻の風は使わない）。
- **改善計画T529（`docs/tasks/T529.md`）: Edgeコストはlazy評価**。以前は探索前に
  bbox全体（数十万Edge）のコストを`compute_edge_costs_bulk`で一括計算してから
  `scipy.sparse.csgraph.dijkstra`へ渡していたが、この事前計算自体が`prepare_ms`の
  支配的コストだった（T522実測、王子30km周回でcost_ms=18,105ms）。実際にA*/Dijkstraが
  訪れるEdgeはbbox全体のごく一部（PoC実測で2.79%）のため、`rustworkx`の
  `edge_cost_fn`コールバック（訪れたEdgeに対してのみ都度呼ばれる）へ
  スカラー版のコスト計算をラップして渡す設計へ変更した
  （`domain/routing.py: LazyRoadGraph`/`shortest_path_node_ids_lazy`参照）。
  1リクエスト内（最大24回＝8方位×3レグ）でEdgeコストの再計算を避けるため、
  `_RoadGraphContext.cost_cache`で結果を使い回す。
- **改善計画T534（`docs/tasks/T534.md`）: 風以外の軸別スコアもEdge単位でプロセス内
  キャッシュ**。T529のlazy評価後もcProfile実測で`compute_edge_cost`内部（タグパース・
  軸評価ループ）が支配的コストと判明した。風以外の軸別スコアはEdgeの材料のみで決まり
  リクエスト間で不変なため、`compute_edge_static_axis_data`の結果をEdge ID単位で
  `infrastructure/axis_score_cache.py`へキャッシュし、`compute_edge_cost_from_static_data`
  が風の組み込みと重み付き合成だけをリクエストごとに行う。`cost_cache`（1リクエスト内）
  より寿命の長い、複数リクエストにまたがるプロセス内キャッシュである点が異なる。
- `LazyRoadGraph`（domain/routing.py: build_lazy_road_graph）は同一ノード間の並行Edgeを
  1本しか保持しない。ただしコストを事前計算しないため「cost最小のEdgeを採用」はできず、
  edge_idの昇順で先頭を採用する決定的な選択に留める（改善計画T363の非決定性解消という
  目的は維持しつつ、lazy評価の制約に合わせた簡略化）。
"""

import asyncio
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.domain.attributes import EdgeMaterialBundle, ElevationAttribute
from app.domain.difficulty import distance_weighted_difficulty
from app.domain.errors import RoutingError
from app.domain.evaluation import (
    RoutePreference,
    compute_cost_from_axis_scores,
    compute_edge_axis_scores,
    compute_edge_cost_from_static_data,
    compute_edge_static_axis_data,
    compute_routable_node_ids,
    compute_wind_penalty,
)
from app.domain.geo import KM_PER_DEGREE_LATITUDE, haversine_distance_km
from app.domain.graph import EdgeLike, LeanEdge, LeanRoadGraph, RoadGraphLike
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
from app.domain.routing import (
    LazyRoadGraph,
    NodeSpatialIndex,
    build_lazy_road_graph,
    build_node_spatial_index,
    concat_node_paths,
    find_nearest_node_indexed,
    path_to_edge_ids_lazy,
    shortest_path_node_ids_lazy,
)
from app.domain.weather import WeatherConditions
from app.domain.wind import ASSUMED_SPEED_KMH
from app.infrastructure import axis_score_cache
from app.services.elevation_aggregation import max_or_none, min_or_none, sum_or_none
from app.services.elevation_attribute_service import ElevationAttributeService
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

logger = logging.getLogger("ridecompass.graph")


@dataclass
class _RoadGraphContext:
    """prepareで構築し、全方位のtrace_loop/evaluate_loopsで共有するリクエスト単位の状態。"""

    graph: RoadGraphLike
    # 改善計画T533: 以前はelevation_attributes/surface_attributes/stop_counts/way_tags/
    # intersection_counts/accident_counts/designated_edge_idsの7個の別々の辞書・集合
    # だったが、Edge単位で`EdgeMaterialBundle`へ統合した1辞書へ改めた（cost_fn等の
    # ホットパスで7回の個別.get()を1回で済ませるため、`domain/attributes.py:
    # EdgeMaterialBundle`のdocstring参照）。
    materials: dict[str, EdgeMaterialBundle]
    accident_years_covered: int
    wind: WeatherConditions | None
    origin_node: str
    # 改善計画T219（T12 Stage 1）: 1リクエストにつき最大17回呼ばれるfind_nearest_node相当を
    # 都度線形探索せず使い回すための索引（domain/routing.py参照）。
    node_index: NodeSpatialIndex
    # 改善計画T529: trace_loopが実際のA*/Dijkstra探索に使うrustworkxベースの探索用
    # グラフ（トポロジのみ、Edgeコストは持たない）。旧scipy版`sparse_graph`（Edgeコストを
    # 事前に一括計算してから構築）から置き換えた——bbox全体のコストを毎回計算する設計
    # 自体がprepare_msの支配的コストだったため（docs/tasks/T522.md・T529.md参照）。
    lazy_graph: LazyRoadGraph
    # 改善計画T529: 探索中に実際に訪れたEdgeのコストだけを都度計算し、1リクエスト内
    # （最大24回＝8方位×3レグ）で使い回すキャッシュ。リクエストを跨いで共有しない
    # （風・夜間判定等の動的要素がリクエストごとに変わるため、`prepare`が
    # `_RoadGraphContext`を構築するたびに空の辞書で初期化する）。
    cost_cache: dict[str, float]
    # 改善計画T173: prepare実行時点で起点が市民薄明の外（夜間）だったかどうか。search_edge_costs
    # 構築時に使った値と同じものを_build_segment_details（表示用difficulty）でも使い、探索コストと
    # 表示を一致させる（詳細はprepare()参照）。
    night_active: bool
    # 改善計画T274: (from_node_id, to_node_id) → Edge の逆引き表。周回の逆回り候補
    # （_reverse_traced_edges）が「この経路の各Edgeを逆方向に辿るEdgeが存在するか」を
    # 追加のDB問い合わせなしに判定するために使う。bboxの全Edge（探索対象の両方向）から
    # 1リクエストにつき1回だけ構築し、全方位のevaluate_loopsで使い回す。同じNode対を
    # 複数のEdgeが結ぶ稀なケース（多重辺）は後勝ちで曖昧になりうるが、
    # build_lazy_road_graph（並行Edgeを1本しか保持しない）と同種の簡略化として許容する。
    node_pair_index: dict[tuple[str, str], EdgeLike]


@dataclass
class _SearchGraph:
    """`prepare`・`preview_segment`共通の「bboxに対する探索用グラフ＋材料一式」
    （改善計画T237）。wind/night軸・0次ハードフィルタ等の探索コスト算出ロジックを
    `_build_search_graph`1箇所にまとめ、ループ探索・単発区間確認の両方で重複させない。
    """

    graph: RoadGraphLike
    lazy_graph: LazyRoadGraph
    # 改善計画T533: _RoadGraphContextと同じ理由でEdgeMaterialBundleへ統合済み。
    materials: dict[str, EdgeMaterialBundle]
    accident_years_covered: int
    wind: WeatherConditions | None
    night_active: bool


class RoadGraphEngine:
    engine_name = "road_graph"

    def __init__(
        self,
        graph_service: GraphService,
        elevation_attribute_service: ElevationAttributeService,
        weather_service: WeatherService,
        route_preference: RoutePreference,
        penalty_strength: float = 1.0,
        max_average_grade_percent: float | None = None,
        hard_filters: frozenset[str] | None = None,
    ):
        self._graph_service = graph_service
        self._elevation_attribute_service = elevation_attribute_service
        # 改善計画T529: EvaluationService（compute_edge_costs_bulkのbbox全体一括評価）は
        # lazy評価化により本エンジンから不要になった（探索コストはtrace_loopが直接
        # compute_edge_cost[スカラー版]をedge_cost_fnとして使う）。EvaluationService
        # クラス自体・compute_edge_costs_bulkは、フォールバック案（抽出フェーズの
        # ベクトル化、docs/tasks/T529.md参照）用の回帰テストオラクルとして残置。
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

    def _build_edge_cost_fn(
        self, search: "_SearchGraph | _RoadGraphContext", cost_cache: dict[str, float]
    ) -> Callable[[str], float]:
        """`shortest_path_node_ids_lazy`へ渡す`edge_cost_fn`を組み立てる（改善計画T529）。

        探索が実際に訪れたEdge（edge_id）に対してのみ都度呼ばれ、`compute_edge_cost`
        （`domain/evaluation.py`、bulk版`compute_edge_costs_bulk`の回帰テストオラクルとして
        現役）と等価な`compute_edge_cost_from_static_data`（改善計画T534、Edge単位で
        プロセス内キャッシュ済みの静的軸別スコアを再利用する版）を使う。Hard Constraintで
        除外されるEdge（`allowed=False`）・コスト算出不能なEdgeは`math.inf`を返し、
        rustworkxの探索から実質的に除外する（`LazyRoadGraph`はグラフ構築時にHard
        Constraintを知らないため、コストが分かるここで表現する。`domain/routing.py:
        shortest_path_node_ids_lazy`のdocstring参照）。

        `cost_cache`は呼び出し元（`prepare`/`preview_segment`）が`_RoadGraphContext`に
        持たせる1リクエスト内共有の辞書。1リクエストにつき最大24回（8方位×3レグ）の
        探索間で同じEdgeのコストを再計算しない。
        """
        active_scopes = frozenset({"night_only"}) if search.night_active else frozenset()
        preference = self._route_preference.with_time_scope(active_scopes)
        weights = preference.weights
        graph = search.graph
        materials = search.materials
        accident_years_covered = search.accident_years_covered
        wind = search.wind
        penalty_strength = self._penalty_strength
        max_average_grade_percent = self._max_average_grade_percent
        hard_filters = self._hard_filters

        def cost_fn(edge_id: str) -> float:
            cached = cost_cache.get(edge_id)
            if cached is not None:
                return cached
            edge = graph.edges[edge_id]
            # 改善計画T533: 以前は7つの別々の辞書・集合へ個別に.get()/inしていたが、
            # Edge単位で統合済みの1オブジェクト（EdgeMaterialBundle）を1回引くだけで
            # 済むようにした（実データ計測で3.5倍、docs/tasks/T533.md参照）。
            bundle = materials.get(edge_id)
            # 改善計画T534: 風以外の軸別スコア（タグパース・区分線形補間・軸評価ループ、
            # cProfile実測でcompute_edge_costの累積時間の6割超）はEdgeの材料だけで決まり
            # リクエスト間で不変なため、Edge単位でプロセス内キャッシュする
            # （infrastructure/axis_score_cache.py参照）。初回訪問時のみ計算しキャッシュへ
            # 積み、2回目以降は風の組み込みと重み付き合成だけで済む。
            static_axis_data = axis_score_cache.get(edge_id)
            if static_axis_data is None:
                counts = bundle.attribute_counts if bundle else None
                static_axis_data = compute_edge_static_axis_data(
                    edge, bundle.elevation_attribute if bundle else None, bundle.surface if bundle else None,
                    stop_count=counts.stop_count if counts else None,
                    way_tags=bundle.way_tags if bundle else None,
                    intersection_count=counts.intersection_count if counts else None,
                    accident_count=counts.accident_count if counts else None,
                    accident_years_covered=accident_years_covered,
                    is_designated=bundle.is_designated if bundle else False,
                )
                axis_score_cache.set(edge_id, static_axis_data)
            result = compute_edge_cost_from_static_data(
                edge, static_axis_data, bundle.elevation_attribute if bundle else None,
                bundle.way_tags if bundle else None, preference, wind=wind,
                penalty_strength=penalty_strength, max_average_grade_percent=max_average_grade_percent,
                weights=weights, hard_filters=hard_filters,
            )
            cost = result.cost if (result.allowed and result.cost is not None) else math.inf
            cost_cache[edge_id] = cost
            return cost

        return cost_fn

    async def _build_search_graph(
        self, bbox: BoundingBox, wind_and_night_origin: Coordinates, now: datetime
    ) -> _SearchGraph | None:
        """bboxに対する探索用グラフ（lazy_graph）＋材料一式を構築する（改善計画T237、
        `prepare`・`preview_segment`共通）。wind/night軸の判定は`wind_and_night_origin`
        （周回ならその起点、区間確認なら起点側の座標）を基準にする——探索中は到達時刻が
        未確定のため出発時刻の近似として使う簡略化はどちらの用途でも変わらない
        （モジュールdocstring参照）。

        改善計画T529: Edgeコストは事前に一括計算しない（lazy評価、モジュールdocstring
        参照）。ここで構築するのはトポロジのみの`LazyRoadGraph`と、後段の
        cost_fnクロージャ（`_build_edge_cost_fn`）が参照する材料一式のみ。
        """
        # 改善計画T522: prepare_msが総時間の8〜9割を占める事象（中心部東京30km実測で
        # 251〜355秒）の調査で、materials取得（DB/タイルキャッシュ）の後段が無計測のまま
        # 数秒〜十数秒を占めていることが判明した（docs/tasks/T522.md参照）。原因特定の
        # ためステージ別に計測する。
        stage_started = time.monotonic()

        # 改善計画T219（T12 Stage 1）: トポロジ＋材料（surface/edge_attribute_counts/
        # way_tags/elevation_attributes/designated_edge_ids）をz12タイル単位のプロセス内
        # キャッシュ経由でまとめて取得する（同一エリアへの2回目以降のリクエストはDBへ
        # 一切アクセスしない。以前はここで6回の個別呼び出しを行っていた、
        # graph_service.pyのget_search_materials_for_bbox参照）。
        materials = await self._graph_service.get_search_materials_for_bbox(bbox)
        materials_ms = round((time.monotonic() - stage_started) * 1000)
        if materials is None or not materials.graph.edges:
            return None
        graph = materials.graph
        # 改善計画T533: surface・edge_attribute_counts（stop/intersection/accident件数）・
        # way_tags・elevation_attribute・is_designatedは、Edge単位で`EdgeMaterialBundle`へ
        # 統合済みの1辞書としてそのまま使う（以前はここで3つの個別dictへ分解していた、
        # `domain/attributes.py: EdgeMaterialBundle`のdocstring参照）。
        edge_materials = materials.materials
        # accident_years_coveredは密度の「件/(km・年)」正規化に使う（bboxに依存しない
        # グローバル値、GraphService側でプロセス内キャッシュ済み）。
        accident_years_covered = await self._graph_service.get_accident_years_covered()

        wind_started = time.monotonic()
        wind = await self._weather_service.get_conditions(wind_and_night_origin)
        wind_ms = round((time.monotonic() - wind_started) * 1000)
        # 改善計画T173: 時間帯依存軸（time_scope="night_only"、現在はnight軸のみ）の
        # 動的化。区間ごとの到達時刻は探索中は未確定のため（風と同じモジュールdocstringの
        # 制約）、出発地点の座標・呼び出し時点を出発時刻の近似として採用し、起点が市民薄明の
        # 外（夜間）ならnight_only軸の重みをそのまま、日中なら0倍にしたRoutePreferenceの
        # コピーを探索コストへ渡す（self._route_preference自体は書き換えない、リクエスト間で
        # 共有される状態のため）。改善計画T352: axis_id"night"のハードコード分岐を
        # AxisDefinition.time_scopeによる汎用ロジックへ置き換えた
        # （RoutePreference.with_time_scope参照）。
        night_active = is_night(wind_and_night_origin, now)

        # 改善計画T529: LazyRoadGraph（トポロジのみ）の構築はEdge数十万件規模でも
        # 数百ms〜1秒台に収まる想定だが（PoC実測、docs/tasks/T529.md参照）、念のため
        # get_or_build_graph_with_attributesのbuild_road_graphと同じ理由で
        # asyncio.to_threadへ逃がす。
        graph_started = time.monotonic()
        lazy_graph = await asyncio.to_thread(build_lazy_road_graph, graph)
        graph_ms = round((time.monotonic() - graph_started) * 1000)
        total_ms = round((time.monotonic() - stage_started) * 1000)
        logger.info(
            "_build_search_graph edges=%d nodes=%d materials_ms=%d wind_ms=%d graph_ms=%d total_ms=%d",
            len(graph.edges), len(graph.nodes), materials_ms, wind_ms, graph_ms, total_ms,
        )

        return _SearchGraph(
            graph=graph,
            lazy_graph=lazy_graph,
            materials=edge_materials,
            accident_years_covered=accident_years_covered,
            wind=wind,
            night_active=night_active,
        )

    async def prepare(
        self,
        origin: Coordinates,
        radius_km: float,
        now: datetime | None = None,
        waypoints: list[Coordinates] | None = None,
    ) -> _RoadGraphContext | None:
        # nowは改善計画T173のnight軸判定用（省略時は実際の現在時刻）。テストが任意の時刻を
        # 注入できるよう引数化した（wind同様、探索中は到達時刻が未確定のためprepare実行時点を
        # 出発時刻の近似として使う簡略化、詳細は_build_search_graph参照）。
        now = now or datetime.now(timezone.utc)
        if waypoints:
            # 改善計画T364: ユーザー指定の経由地は起点から半径radius_km以内とは限らない
            # ため、8方位探索の円形bbox（_bbox_around_point）ではなく、preview_segmentと
            # 同じ「複数点の外接矩形+固定マージン」を使う。
            bbox = _bbox_covering_points([origin, *waypoints], PREVIEW_BBOX_MARGIN_KM)
        else:
            margin_km = max(BBOX_MARGIN_MIN_KM, radius_km * BBOX_MARGIN_RATIO)
            bbox = _bbox_around_point(origin, radius_km + margin_km)

        search = await self._build_search_graph(bbox, origin, now)
        if search is None:
            return None

        # 改善計画T219: このgraphに対する索引を1回だけ構築し、原点＋trace_loopの
        # 経由地スナップ（1リクエストで最大17回）すべてで使い回す。
        # 改善計画T256: 索引の候補は実際に経路探索可能な（Hard Constraint通過後も
        # 次数1以上の）Nodeのみに絞る。絞らないと、幹線道路（highway=trunk等）にしか
        # 接続していない地理的最近傍Node（新宿駅・渋谷駅等、駅前が国道の交差点に直接
        # 面する場所で実機確認）が選ばれ、そこがHard Constraint除外後のグラフ上では
        # 孤立点になるため、8方位すべてのDijkstra探索が"no path found"で失敗してしまう。
        # 改善計画T529: lazy評価ではEdgeコストを事前計算しないため、旧`routable_node_ids`
        # （sparse_graphから算出）は使えない——0次ハードフィルタだけを軽量に評価する
        # `compute_routable_node_ids`（domain/evaluation.py）へ置き換えた
        # （docs/tasks/T529.md参照）。
        # 改善計画T522: 索引構築（KDTree構築・Edge数十万件規模の辞書構築）もget_or_build_
        # graph_with_attributesのbuild_road_graphと同じ理由でasyncio.to_threadへ逃がす
        # （docs/tasks/T522.md参照）。find_nearest_node_indexedは既存索引への単発クエリで
        # コストが軽いためメインコルーチンのまま呼ぶ。
        index_started = time.monotonic()
        routable_ids = await asyncio.to_thread(
            compute_routable_node_ids,
            search.graph, search.materials,
            self._hard_filters, self._max_average_grade_percent,
        )
        node_index = await asyncio.to_thread(build_node_spatial_index, search.graph, node_ids=routable_ids)
        origin_node = find_nearest_node_indexed(node_index, origin)
        if origin_node is None:
            return None
        node_pair_index = await asyncio.to_thread(_build_node_pair_index, search.graph)
        index_ms = round((time.monotonic() - index_started) * 1000)
        logger.info("prepare index build edges=%d index_ms=%d", len(search.graph.edges), index_ms)

        return _RoadGraphContext(
            graph=search.graph,
            materials=search.materials,
            accident_years_covered=search.accident_years_covered,
            wind=search.wind,
            origin_node=origin_node,
            node_index=node_index,
            lazy_graph=search.lazy_graph,
            cost_cache={},
            night_active=search.night_active,
            node_pair_index=node_pair_index,
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

        # 改善計画T256: prepareと同じ理由で、索引の候補を実際に経路探索可能なNodeのみに
        # 絞る（幹線道路にしか接続していない孤立Nodeを除外）。改善計画T529:
        # 旧`routable_node_ids`（sparse_graph算出）から`compute_routable_node_ids`
        # （0次ハードフィルタのみの軽量版）へ置き換えた（docs/tasks/T529.md参照）。
        # 改善計画T522: prepareと同じ理由でasyncio.to_threadへ逃がす（docs/tasks/T522.md参照）。
        routable_ids = await asyncio.to_thread(
            compute_routable_node_ids,
            search.graph, search.materials,
            self._hard_filters, self._max_average_grade_percent,
        )
        node_index = await asyncio.to_thread(build_node_spatial_index, search.graph, node_ids=routable_ids)
        origin_node = find_nearest_node_indexed(node_index, origin)
        destination_node = find_nearest_node_indexed(node_index, destination)
        if origin_node is None or destination_node is None:
            return None

        # 改善計画T529: lazy評価（rustworkxのA*、モジュールdocstring参照）。cost_cacheは
        # このpreview_segment呼び出し1回限りのローカル辞書（trace_loopのような複数回の
        # 探索間での再利用は無いため、prepare()のcontext.cost_cacheとは異なりここでは
        # 使い捨てでよい）。
        cost_fn = self._build_edge_cost_fn(search, {})
        estimate_fn = _build_estimate_cost_fn(search.graph, destination_node)
        path = await asyncio.to_thread(
            shortest_path_node_ids_lazy, search.lazy_graph, origin_node, destination_node, cost_fn, estimate_fn
        )
        if path is None:
            return None
        edge_ids = path_to_edge_ids_lazy(search.lazy_graph, path)
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
        self, context: _RoadGraphContext, waypoints: list[Coordinates], bearing: int | None
    ) -> TracedLoop:
        # waypoints = [起点, 中間経由地..., 終点]（8方位探索ではRouteGenerator._loop_waypoints
        # が経由地2点の固定三角形＋終点=起点を、改善計画T364の経由地指定ルートでは
        # ユーザー指定の中間経由地1〜N点＋終点=起点を、改善計画T365の目的地指定ルートでは
        # さらに終点=目的地（起点と異なる座標）を渡す）。起点は最近接Nodeをprepareでスナップ
        # したNodeを使い、中間経由地はここでスナップする（改善計画T219: prepareで構築済みの
        # 索引を使い回す、都度線形探索しない）。
        interior_nodes = []
        for point in waypoints[1:-1]:
            node = find_nearest_node_indexed(context.node_index, point)
            if node is None:
                raise RoutingError(f"direction {bearing}: could not snap waypoints to road graph")
            interior_nodes.append(node)
        # 改善計画T365: 終点が起点と同一座標（周回、T364までの唯一の形）ならprepareで
        # 特別扱い済みのcontext.origin_nodeをそのまま再利用する（起終点を同じNodeに
        # 揃えないと周回が閉じない）。終点が起点と異なる座標（目的地ルート）の場合のみ
        # find_nearest_node_indexedで独立にスナップする。
        end_point = waypoints[-1]
        if end_point.latitude == waypoints[0].latitude and end_point.longitude == waypoints[0].longitude:
            end_node = context.origin_node
        else:
            end_node = find_nearest_node_indexed(context.node_index, end_point)
            if end_node is None:
                raise RoutingError(f"direction {bearing}: could not snap destination to road graph")
        node_sequence = [context.origin_node, *interior_nodes, end_node]

        # 改善計画T529: A*/Dijkstra本体はscipy（bbox全体のコストを事前に一括計算してから
        # 構築するeager評価）ではなく、rustworkx（訪れたEdgeのみ都度コストを計算する
        # lazy評価）で行う（1リクエストにつき最大24回、モジュールdocstring参照）。
        # cost_fnは`context.cost_cache`（8方位×3レグで共有）経由でEdgeの重複計算を避ける。
        # estimate_fn（A*ヒューリスティック）はレグごとに目的地（to_node）が変わるため
        # レグごとに組み立て直す。同期関数（rustworkxの探索本体）を直接awaitせず呼ぶと
        # イベントループを塞ぐため、asyncio.to_threadへ逃がす（T522と同じ理由）。
        raw_cost_fn = self._build_edge_cost_fn(context, context.cost_cache)
        # 改善計画T529フォローアップ調査: 本番実測でtrace_ms（lazy評価が実際に走る場所）が
        # 旧実装より悪化する事象が判明した（docs/tasks/T529.md参照）。原因切り分けのため、
        # 方位ごとにedge_cost_fn呼び出し回数（cache hit/miss問わず）・壁時計時間・
        # cost_cacheの純増分（このリクエスト内で他方位と共有できた分）を計測する。
        call_count = 0

        def cost_fn(edge_id: str) -> float:
            nonlocal call_count
            call_count += 1
            return raw_cost_fn(edge_id)

        def _trace_segments() -> list[list[str]] | None:
            segment_paths = []
            for from_node, to_node in zip(node_sequence, node_sequence[1:]):
                estimate_fn = _build_estimate_cost_fn(context.graph, to_node)
                segment_path = shortest_path_node_ids_lazy(
                    context.lazy_graph, from_node, to_node, cost_fn, estimate_fn
                )
                if segment_path is None:
                    return None
                segment_paths.append(segment_path)
            return segment_paths

        trace_started = time.monotonic()
        cache_size_before = len(context.cost_cache)
        segment_paths = await asyncio.to_thread(_trace_segments)
        trace_wall_ms = round((time.monotonic() - trace_started) * 1000)
        cache_size_after = len(context.cost_cache)
        logger.info(
            "trace_loop direction=%s wall_ms=%d cost_fn_calls=%d cache_before=%d cache_after=%d cache_added=%d",
            bearing, trace_wall_ms, call_count, cache_size_before, cache_size_after,
            cache_size_after - cache_size_before,
        )
        if segment_paths is None:
            raise RoutingError(f"direction {bearing}: no path found between waypoints")

        full_path = concat_node_paths(segment_paths)
        edge_ids = path_to_edge_ids_lazy(context.lazy_graph, full_path)
        if not edge_ids:
            raise RoutingError(f"direction {bearing}: resulting path has no edges")
        # 改善計画T218（T12 Stage 0）: prepareが読み込んだcontext.graph（LeanRoadGraph）の
        # Edgeはgeometryが空プレースホルダのため、区間表示・標高取得等（後段の
        # _build_candidate）に使う実ジオメトリをこの経路ぶん（数十〜数百Edge）だけ
        # 取得し直す。`or context.graph.edges[edge_id]`は、Overpassフォールバック撤去
        # （T22/T222）後の現在はOverpass経由構築を指すものではない——prepare時点から
        # このget_edges_with_geometryのDBクエリまでの間に、別リクエストが同じbboxを
        # 再構築（save_graphのUPSERT/DELETE、is_split_up_to_dateの項参照）してedge_idが
        # 入れ替わるレースが理論上ありうるため、その場合にKeyErrorで落とさず
        # context.graph側の値（geometryは空プレースホルダのまま）へ倒す防御的フォールバック
        # として残す。
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
            await asyncio.gather(*(self._build_best_candidate(context, t, start_time) for t in traced))
        )

    async def _build_best_candidate(
        self, context: _RoadGraphContext, traced: TracedLoop, start_time: datetime
    ) -> RouteCandidate:
        """1方位ぶんの周回候補を組み立てる。改善計画T274: 同じ物理的な周回形状の
        逆回り（起点→B→A→起点）も、追加のDB/外部API呼び出しゼロで合成できる場合は
        合成し、distance_weighted_difficulty（segmentsの距離加重平均、
        RouteGenerator._with_overall_difficultyと同じ指標）が小さい方を採用する
        （両方向を別候補として追加するのではなく、方位ごとに良い方だけを残す設計。
        経路中に一方通行Edgeが1つでもあれば逆回りは物理的に成立しないため、その場合は
        順方向のみを返す）。改善計画T364: ユーザーが指定した経由地ルート
        （traced.bearing is None）は訪問順序そのものが要件のため、逆回り合成は行わない。
        """
        edges_in_path: list[EdgeLike] = traced.data
        elevation_attributes = await self._fetch_elevation_attributes(context, edges_in_path)
        forward_candidate = self._build_candidate(context, traced, edges_in_path, elevation_attributes, start_time)

        if traced.bearing is None:
            return forward_candidate

        reverse_edges = _reverse_traced_edges(edges_in_path, context.node_pair_index)
        if reverse_edges is None:
            return forward_candidate
        reverse_elevation_attributes = _reverse_elevation_attributes(
            edges_in_path, reverse_edges, elevation_attributes
        )
        reverse_candidate = self._build_candidate(
            context, traced, reverse_edges, reverse_elevation_attributes, start_time
        )
        return _pick_better_candidate(forward_candidate, reverse_candidate)

    async def _fetch_elevation_attributes(
        self, context: _RoadGraphContext, edges_in_path: list[EdgeLike]
    ) -> dict[str, ElevationAttribute]:
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
        return await self._elevation_attribute_service.get_attributes_for_graph(path_graph)

    def _build_candidate(
        self,
        context: _RoadGraphContext,
        traced: TracedLoop,
        edges_in_path: list[EdgeLike],
        elevation_attributes: dict[str, ElevationAttribute],
        start_time: datetime,
    ) -> RouteCandidate:
        # 改善計画T274: edges_in_path・elevation_attributesを引数化し（以前はtraced.dataと
        # 自前のGSI問い合わせ結果を直接使っていた）、逆回り候補（_reverse_traced_edges・
        # _reverse_elevation_attributes、追加I/Oなしで導出済み）も同じ組み立てロジックへ
        # 通せるようにした。distance_km・bearingは順方向・逆回りで共通（同じ物理経路の
        # 総距離・同じ方位の候補のため）traced（順方向のTracedLoop）からそのまま使う。
        geometry = _concat_edge_geometries(edges_in_path)
        elevation_stats = _aggregate_elevation(edges_in_path, elevation_attributes)
        road_score = _aggregate_road_score(edges_in_path, context.materials)
        wind_score = _aggregate_wind_score(edges_in_path, context.wind)
        segments = self._build_segment_details(edges_in_path, elevation_attributes, context, start_time)
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
        # 改善計画T173: 時間帯依存軸の重みはcontext.night_active（prepare時点の判定、
        # 探索コストで使ったものと同一）で0倍にする。表示（本関数）と探索コストが
        # 食い違わないようにする。改善計画T352: 汎用ロジックへ置き換え（上記_build_search_
        # graph参照）。
        active_scopes = frozenset({"night_only"}) if context.night_active else frozenset()
        preference = self._route_preference.with_time_scope(active_scopes)
        segments = []
        cumulative_km = 0.0

        for edge in edges:
            distance_km = edge.distance_m / 1000
            elevation_attr = elevation_attributes.get(edge.edge_id)
            # 改善計画T533: surface/stop_count/way_tags/intersection_count/accident_count/
            # is_designatedは、Edge単位で統合済みの1オブジェクトから1回の.get()で取り出す
            # （`domain/attributes.py: EdgeMaterialBundle`参照）。
            bundle = context.materials.get(edge.edge_id)
            counts = bundle.attribute_counts if bundle else None
            surface_type = bundle.surface if bundle else None
            stop_count = counts.stop_count if counts else None
            edge_way_tags = bundle.way_tags if bundle else None
            intersection_count = counts.intersection_count if counts else None
            accident_count = counts.accident_count if counts else None

            gradient_percent = elevation_attr.average_grade if elevation_attr else None
            wind_penalty = compute_wind_penalty(edge, context.wind)
            road_surface_good = classify_osm_surface(surface_type)
            is_designated = bundle.is_designated if bundle else False

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
                    # 改善計画T309: axis_scores（compute_edge_axis_scores）は既にaxis_id→
                    # difficultyの汎用dict（データ無しの軸はキー自体を持たない）のため、
                    # そのままRouteSegmentDetail.axis_difficultiesへ渡せる。
                    axis_difficulties=axis_scores,
                    difficulty=composite_difficulty_value,
                )
            )
            cumulative_km += distance_km

        return segments


def _build_estimate_cost_fn(graph: RoadGraphLike, target_node_id: str) -> Callable[[str], float]:
    """`shortest_path_node_ids_lazy`へ渡すA*のestimate_cost_fn（改善計画T529）を、
    目的地ノード`target_node_id`への直線距離（m）として組み立てる。

    Edge Costは常に`cost >= distance_m`を満たす（`docs/decisions/t12-routing-scale.md`
    原則1「不変条件1」、ペナルティ倍率は常に1以上）ため、直線距離は実際のコストを
    過大評価しない下界＝admissibleなヒューリスティックになる。この不変条件は
    「将来のA*ヒューリスティック admissibility保存のため」と当時のADRが明記して
    意図的に維持してきたものであり、本タスクがその意図どおり利用する形になる。
    """
    target_node = graph.nodes[target_node_id]
    target_coord = Coordinates(latitude=target_node.latitude, longitude=target_node.longitude)

    def estimate_fn(node_id: str) -> float:
        node = graph.nodes[node_id]
        node_coord = Coordinates(latitude=node.latitude, longitude=node.longitude)
        return haversine_distance_km(node_coord, target_coord) * 1000

    return estimate_fn


def _build_node_pair_index(graph: RoadGraphLike) -> dict[tuple[str, str], EdgeLike]:
    """(from_node_id, to_node_id) → Edge の逆引き表（改善計画T274）。`_RoadGraphContext`
    に1リクエストにつき1回だけ構築し、`_reverse_traced_edges`が使い回す。多重辺
    （同じNode対を複数のEdgeが結ぶ稀なケース）は辞書内包表記の性質上、`graph.edges`の
    挿入順で後勝ちになる（`_RoadGraphContext.node_pair_index`のコメント参照）。
    """
    return {(edge.from_node_id, edge.to_node_id): edge for edge in graph.edges.values()}


def _reverse_traced_edges(
    edges_in_path: list[EdgeLike], node_pair_index: dict[tuple[str, str], EdgeLike]
) -> list[EdgeLike] | None:
    """順方向の経路`edges_in_path`（起点→...→起点）を逆順に辿った場合の、対応する
    逆方向Edge列を構築する（改善計画T274）。経路中に一方通行（逆方向Edgeが存在しない）
    区間が1つでもあれば物理的に逆走不可能なため`None`を返す。

    `node_pair_index`（`context.graph`から構築済み）を使い、逆方向Edgeのトポロジ
    （`bearing_deg`等、進行方向で値が変わる唯一のフィールド）を追加のDB/外部API
    呼び出しなしに引く。`geometry`だけは逆方向Edge自体（lean、空プレースホルダ）からではなく、
    順方向で既にhydrate済みのgeometryを反転させて使う（同じ物理区間を逆順に辿るだけの
    ため、DB再取得不要。build_road_graphの`-bwd`Edgeが`-fwd`のgeometryを反転して持つのと
    同じ関係）。distance_m・osm_way_id・highwayは進行方向に依存しない値だが、
    「逆方向Edge自身の値」として`node_pair_index`側から読む（forward側からの流用ではなく、
    逆方向Edgeが実在するという確認を兼ねる）。
    """
    reverse_edges: list[EdgeLike] = []
    for edge in reversed(edges_in_path):
        reverse_topology = node_pair_index.get((edge.to_node_id, edge.from_node_id))
        if reverse_topology is None:
            return None
        reverse_edges.append(
            LeanEdge(
                edge_id=reverse_topology.edge_id,
                from_node_id=reverse_topology.from_node_id,
                to_node_id=reverse_topology.to_node_id,
                geometry=list(reversed(edge.geometry)),
                distance_m=reverse_topology.distance_m,
                osm_way_id=reverse_topology.osm_way_id,
                highway=reverse_topology.highway,
                bearing_deg=reverse_topology.bearing_deg,
            )
        )
    return reverse_edges


def _reverse_elevation_attribute(forward: ElevationAttribute, reverse_edge_id: str) -> ElevationAttribute:
    """順方向のElevationAttributeから、同じ物理的な地形を逆方向に走った場合の値を
    代数的に導出する（改善計画T274）。標高は地形の物理量で進行方向に依存しないため、
    この変換は厳密に正しい: 獲得標高↔喪失標高の入れ替え、始点/終点標高の入れ替え、
    平均勾配の符号反転、最大/最小勾配の符号反転＋入れ替え（domain/attributes.py:
    compute_elevation_attributeが区間の形状点列を進行方向の順で積算するため、逆順に
    辿ると各区間のdiff＝勾配の符号がすべて反転し、max/minも入れ替わる）。GSI標高APIを
    叩き直さない。
    """
    return ElevationAttribute(
        edge_id=reverse_edge_id,
        start_elevation_m=forward.end_elevation_m,
        end_elevation_m=forward.start_elevation_m,
        elevation_gain_m=forward.elevation_loss_m,
        elevation_loss_m=forward.elevation_gain_m,
        average_grade=-forward.average_grade if forward.average_grade is not None else None,
        max_grade=-forward.min_grade if forward.min_grade is not None else None,
        min_grade=-forward.max_grade if forward.max_grade is not None else None,
        data_source=forward.data_source,
        data_version=forward.data_version,
        calculated_at=forward.calculated_at,
    )


def _reverse_elevation_attributes(
    edges_in_path: list[EdgeLike],
    reverse_edges: list[EdgeLike],
    elevation_attributes: dict[str, ElevationAttribute],
) -> dict[str, ElevationAttribute]:
    """`_reverse_traced_edges`が返した逆方向Edge列ぶんの`ElevationAttribute`辞書を、
    順方向で既に取得済みの値から代数的に導出する（改善計画T274、`_reverse_elevation_attribute`
    を経路全体へ適用する薄いラッパー）。順方向で標高が取得できなかったEdge
    （`elevation_attributes`にキーが無い）は、逆方向側でもキーを持たせない（欠損の伝播）。
    """
    result: dict[str, ElevationAttribute] = {}
    for forward_edge, reverse_edge in zip(reversed(edges_in_path), reverse_edges):
        forward_attribute = elevation_attributes.get(forward_edge.edge_id)
        if forward_attribute is not None:
            result[reverse_edge.edge_id] = _reverse_elevation_attribute(forward_attribute, reverse_edge.edge_id)
    return result


def _route_composite_difficulty(candidate: RouteCandidate) -> float | None:
    """候補のsegmentsから、距離加重平均の合成difficultyを求める（改善計画T274、
    逆回り候補との比較指標）。`RouteGenerator._with_overall_difficulty`と同じ計算だが、
    あちらは方位ごとに採否が確定した最終候補へ`overall_difficulty`を付与する後処理
    （エンジン非依存の戦略層）なのに対し、ここは同じ方位の順方向・逆回り候補のどちらを
    残すかをエンジン内部で決めるための指標であり、計算するタイミング・対象が異なる
    （同じ指標を2箇所で使うが、役割が違うため無理に共通化しない）。
    """
    if not candidate.segments:
        return None
    return distance_weighted_difficulty([(s.difficulty, s.distance_km) for s in candidate.segments])


def _pick_better_candidate(forward: RouteCandidate, reverse: RouteCandidate) -> RouteCandidate:
    """順方向・逆回り候補のうち、`_route_composite_difficulty`が小さい（走りやすい）方を
    採用する（改善計画T274）。逆回り側が算出不能（segments欠損等）なら順方向を採用する
    （比較不能を「逆回りの方が良い」とは解釈しない、安全側）。
    """
    forward_difficulty = _route_composite_difficulty(forward)
    reverse_difficulty = _route_composite_difficulty(reverse)
    if reverse_difficulty is not None and (forward_difficulty is None or reverse_difficulty < forward_difficulty):
        return reverse
    return forward


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

    # 最終集約（sum/min/max・空ならNone・小数1桁丸め）はelevation_aggregation.pyへ集約する。
    return {
        "elevation_gain_m": sum_or_none(gains),
        "min_elevation_m": min_or_none(elevations),
        "max_elevation_m": max_or_none(elevations),
        "max_gradient_percent": max_or_none(grades),
    }


def _aggregate_road_score(edges: list[EdgeLike], materials: dict[str, EdgeMaterialBundle]) -> float | None:
    """経路の総距離に対する「走行しやすい舗装路面」の割合(%)を算出する。Edge単位のsurfaceタグを
    domain/road.py: distance_weighted_road_scoreへ渡す薄いラッパー。
    """
    def surface_of(edge: EdgeLike) -> str | None:
        bundle = materials.get(edge.edge_id)
        return bundle.surface if bundle else None

    return distance_weighted_road_score(
        [(edge.distance_m, classify_osm_surface(surface_of(edge))) for edge in edges]
    )


def _aggregate_wind_score(edges: list[EdgeLike], wind: WeatherConditions | None) -> float | None:
    """経路全体の距離加重平均wind_penalty（符号付きm/s、正=正味向かい風）。
    風は区間ごとの推定到達時刻ではなく出発時点の値をルート全体に一様適用する
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
