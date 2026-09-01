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
- **改善計画T529（`docs/tasks/T529.md`）→T536（`docs/tasks/T536.md`）で置き換え:
  Edgeコストは「タイル単位の静的スコア行列＋リクエスト時ベクトル計算」**。T529当初は
  探索前にbbox全体（数十万Edge）のコストを`compute_edge_costs_bulk`で一括計算してから
  `scipy.sparse.csgraph.dijkstra`へ渡していたが、この事前計算自体が`prepare_ms`の
  支配的コストだった（T522実測、王子30km周回でcost_ms=18,105ms）。続くT529
  （`edge_cost_fn`コールバックによるlazy評価）・T534（Edge単位の辞書キャッシュ）でも、
  探索中にEdge1本ごとにPythonのコスト計算コールバックを呼ぶ構造自体は変わらず、
  依然としてA* 24本で数秒〜十数秒を占めていた（T522全再点検、本番VM実測8.3〜17.7秒）。
  T536は、タイル読込時（`GraphService._get_or_build_tile_materials`）に「Edge×公開軸」の
  静的スコア行列（`domain/evaluation.py: StaticEdgeScoreMatrix`、風など動的軸の列は
  NaN）を1回だけ構築してキャッシュし、リクエスト時にその行列＋動的軸（風、
  `evaluate_dynamic_axis_arrays`）＋重みベクトルからコスト配列を**bbox全体ぶん1回だけ**
  numpyで合成する設計へ変更した。`LazyRoadGraph`のEdge/Node payloadは整数indexにし、
  A*（`domain/routing.py: shortest_path_node_ids_lazy`）へは`edge_cost_fn=cost_list.
  __getitem__`のような素のlistインデックスアクセスを渡す——探索中にPythonの関数
  フレームを一切作らない（本番VM試作でA* 24本 8.3〜17.7秒→0.37秒を確認済み）。
  同一Node間の並行Edgeは、コストが探索前に判明しているため「cost最小を採用」
  （改善計画T363の元の意味論）に戻せる。`_RoadGraphContext.cost_cache`（Edge単位の
  1リクエスト内キャッシュ）・`infrastructure/axis_score_cache.py`（Edge単位の複数
  リクエストにまたがるキャッシュ、T534）はいずれも不要になり撤去した——静的スコア
  行列はタイル単位で`infrastructure/tile_score_matrix_cache.py`へキャッシュされ、
  リクエスト時のベクトル計算はEdge単位のPythonコールバックを経由しないため。
- `_build_segment_details`（区間表示）も探索と同じコスト配列・スコア行列から
  `axis_difficulties`を引く（T536で、探索と表示の二重計算を解消）。
- 8方位の`trace_loop`は直列実行する（`asyncio.to_thread`による並列化は、rustworkxが
  GILを解放しないため8スレッドが競合しむしろ約2秒遅くなることを実測、T522参照）。
- **改善計画T537（`docs/tasks/T537.md`）: 探索用グラフ（`LazyRoadGraph`）・routable
  Node空間索引（`NodeSpatialIndex`）はタイル集合キーのプロセス内LRU
  （`infrastructure/search_graph_cache.py`）でキャッシュする**。T536完了後も
  `build_lazy_road_graph`・`compute_routable_node_ids`・`build_node_spatial_index`は
  毎リクエスト作り直されており、これらはタイル集合と0次フィルタ（`hard_filters`・
  `max_average_grade_percent`）だけで決まる純粋な派生物のため、同じタイル集合への
  2回目以降のリクエストはこれらの構築自体を丸ごと省略できる（T522実測、温パスの
  prepareの残り約2秒の内訳）。並行Edge（同一Node間の複数Edge）の解消は、T536で
  復活させた「cost最小を採用」（コストはリクエストごとに軸重み・風・0次フィルタで
  変わる）ではなく、`build_lazy_road_graph`の決定的フォールバック（edge_idの昇順で
  先頭を採用）へ戻す——タイル集合だけで決まるキャッシュとコストベースの動的解消は
  両立しないため、実データで稀な並行Edgeの厳密さより2回目以降のprepare短縮を優先した
  （並行Edgeのうち一方だけが0次フィルタで除外される稀なケースでは、cost最小方式なら
  自動的に許可される側が選ばれるが、この方式では選ばれない場合がある。T536当時の
  `_build_node_pair_index`「多重辺は後勝ちで曖昧になりうるが許容する」と同種の
  簡略化として許容する、判断理由の詳細はdocs/tasks/T537.md参照）。
  `_build_node_pair_index`（逆回り候補用の全Edge分の逆引き表、O(Edge数)）は撤去し、
  `_reverse_traced_edges`はキャッシュ済み`LazyRoadGraph.edge_index_by_node_pair`
  （並行Edge解消後、経路上のEdgeだけに対する遅延引き）で代替する。
"""

import asyncio
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np

from app.domain.attributes import EdgeMaterialBundle, ElevationAttribute
from app.domain.difficulty import distance_weighted_difficulty
from app.domain.errors import RoutingError
from app.domain.evaluation import (
    DynamicAxisRequestContext,
    RoutePreference,
    compose_costs_from_axis_matrix,
    compute_hard_filter_excluded,
    compute_routable_node_ids,
    compute_wind_penalty,
    evaluate_dynamic_axis_arrays,
)
from app.domain.geo import KM_PER_DEGREE_LATITUDE, haversine_distance_km_array
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
from app.infrastructure import search_graph_cache
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
    # だったが、Edge単位で`EdgeMaterialBundle`へ統合した1辞書へ改めた
    # （`domain/attributes.py: EdgeMaterialBundle`のdocstring参照）。T536以降はEdge単位の
    # 材料アクセスは探索コスト算出のホットパスからは外れたが、`_build_segment_details`の
    # 表示用フィールド（surface等）取得には引き続き使う。
    materials: dict[str, EdgeMaterialBundle]
    accident_years_covered: int
    weather: WeatherConditions | None
    origin_node: str
    # 改善計画T219（T12 Stage 1）: 1リクエストにつき最大17回呼ばれるfind_nearest_node相当を
    # 都度線形探索せず使い回すための索引（domain/routing.py参照）。
    node_index: NodeSpatialIndex
    # 改善計画T529→T536: trace_loopが実際のA*探索に使うrustworkxベースの探索用グラフ
    # （Node/Edge payloadは整数index、domain/routing.py: LazyRoadGraph参照）。改善計画
    # T537: タイル集合キーでキャッシュ済み（infrastructure/search_graph_cache.py）。
    # `_reverse_traced_edges`が`edge_index_by_node_pair`を逆回り候補のEdge逆引きにも使う
    # （旧`_RoadGraphContext.node_pair_index`[全Edge分の逆引き表]の代替、T537で撤去）。
    lazy_graph: LazyRoadGraph
    # 改善計画T536: リクエストにつき1回だけbbox全体ぶん合成済みのコスト配列
    # （`lazy_graph.edge_ids`と同じ行順のPython list、A*のedge_cost_fnへ
    # `cost_list.__getitem__`としてそのまま渡す）。0次フィルタで除外されたEdgeは
    # math.infになっている。
    cost_list: list[float]
    # 改善計画T536: `score_matrix.edge_ids`（並行Edge解消前、bbox全体の生Edge集合）上での
    # edge_id→行indexの対応表。`difficulty_array`/`axis_arrays`と組み合わせて
    # `_build_segment_details`が探索と同じ配列からaxis_difficultiesを引くために使う
    # （並行Edge解消後のlazy_graphより広い集合をカバーするため、経路上のどのEdgeも
    # 必ず引ける）。
    full_edge_row: dict[str, int]
    # 改善計画T536: 合成済みcomposite difficulty配列（NaN=データ無し、full_edge_row基準）。
    difficulty_array: np.ndarray
    # 改善計画T536: 公開軸ごとのスコア配列（axis_id→array、full_edge_row基準、動的軸[風]も
    # 実際の値へ上書き済み）。_build_segment_detailsのaxis_difficulties構築に使う。
    axis_arrays: dict[str, np.ndarray]
    # 改善計画T536: A*のestimate_cost_fn（ヒューリスティック）を、レグごとの目的地に対して
    # numpyで1回だけベクトル計算するための、lazy_graph.index_to_node_id順の緯度・経度配列。
    node_lat: np.ndarray
    node_lon: np.ndarray
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
    lazy_graph: LazyRoadGraph
    # 改善計画T537: bboxを覆うz12タイル集合（frozenset[(zoom,x,y)]）。GraphService.
    # get_search_materials_for_bboxが「タイルキャッシュをそのまま結合したgraph」を
    # 返した場合のみ設定される（split鮮度が古いbbox限定の再構築経路ではNone）。
    # prepare/preview_segmentがroutable Node索引のキャッシュキーとして使い回す。
    tile_set: frozenset[tuple[int, int, int]] | None
    # 改善計画T533: _RoadGraphContextと同じ理由でEdgeMaterialBundleへ統合済み。
    materials: dict[str, EdgeMaterialBundle]
    accident_years_covered: int
    weather: WeatherConditions | None
    night_active: bool
    # 改善計画T536: _RoadGraphContextと同じ意味（フィールドdocstring参照）。
    cost_list: list[float]
    full_edge_row: dict[str, int]
    difficulty_array: np.ndarray
    axis_arrays: dict[str, np.ndarray]
    node_lat: np.ndarray
    node_lon: np.ndarray


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
        # 改善計画T536: EvaluationService（compute_edge_costs_bulkのbbox全体一括評価）は
        # 本エンジンから不要になった（探索コストは_build_search_graphがbbox全体ぶん
        # リクエストにつき1回だけベクトル合成する）。EvaluationServiceクラス自体・
        # compute_edge_costs_bulkは回帰テストオラクルとして残置——静的スコア行列
        # （StaticEdgeScoreMatrix）が同じ抽出・計算フェーズ（_evaluate_axes_bulk）を
        # 共有するため、両者の一致は引き続きtests/test_evaluation_bulk.pyで検証する。
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
        """bboxに対する探索用グラフ（lazy_graph）＋bbox全体ぶんのコスト配列を構築する
        （改善計画T237、`prepare`・`preview_segment`共通）。wind/night軸の判定は
        `wind_and_night_origin`（周回ならその起点、区間確認なら起点側の座標）を基準にする
        ——探索中は到達時刻が未確定のため出発時刻の近似として使う簡略化はどちらの用途でも
        変わらない（モジュールdocstring参照）。

        改善計画T536: `GraphService.get_search_materials_for_bbox`が返す
        `StaticEdgeScoreMatrix`（タイル単位でキャッシュ済みの静的Edge×公開軸スコア行列）に
        対し、動的軸（風、`evaluate_dynamic_axis_arrays`）と重みベクトルを適用して
        コスト配列を**bbox全体ぶん1回だけ**numpyで合成する。これがEdgeごとのPython
        コールバックを排除する設計の核心（`LazyRoadGraph`のNode/Edge payloadを整数index
        にし、探索本体[`shortest_path_node_ids_lazy`]へは合成済みの`list.__getitem__`を
        渡すだけにする）。
        """
        # 改善計画T522: prepare_msが総時間の8〜9割を占める事象（中心部東京30km実測で
        # 251〜355秒）の調査で、materials取得（DB/タイルキャッシュ）の後段が無計測のまま
        # 数秒〜十数秒を占めていることが判明した（docs/tasks/T522.md参照）。原因特定の
        # ためステージ別に計測する。
        stage_started = time.monotonic()

        # 改善計画T219（T12 Stage 1）→T536: トポロジ＋材料＋静的スコア行列をz12タイル
        # 単位のプロセス内キャッシュ経由でまとめて取得する（同一エリアへの2回目以降の
        # リクエストはDBアクセスもEdge単位のPython評価も一切発生しない、
        # graph_service.pyのget_search_materials_for_bbox参照）。
        built = await self._graph_service.get_search_materials_for_bbox(bbox)
        materials_ms = round((time.monotonic() - stage_started) * 1000)
        if built is None:
            return None
        search_materials, score_matrix, tile_set = built
        if not search_materials.graph.edges:
            return None
        graph = search_materials.graph
        # 改善計画T533: surface・edge_attribute_counts（stop/intersection/accident件数）・
        # way_tags・elevation_attribute・is_designatedは、Edge単位で`EdgeMaterialBundle`へ
        # 統合済みの1辞書としてそのまま使う（T536以降は表示用[_build_segment_details]の
        # 一部フィールド取得にのみ使う）。
        edge_materials = search_materials.materials
        # accident_years_coveredは密度の「件/(km・年)」正規化に使う（bboxに依存しない
        # グローバル値、GraphService側でプロセス内キャッシュ済み）。
        accident_years_covered = await self._graph_service.get_accident_years_covered()

        weather_started = time.monotonic()
        weather = await self._weather_service.get_conditions(wind_and_night_origin)
        weather_ms = round((time.monotonic() - weather_started) * 1000)
        # 改善計画T173: 時間帯依存軸（time_scope="night_only"、現在はnight軸のみ）の
        # 動的化。区間ごとの到達時刻は探索中は未確定のため（風と同じモジュールdocstringの
        # 制約）、出発地点の座標・呼び出し時点を出発時刻の近似として採用し、起点が市民薄明の
        # 外（夜間）ならnight_only軸の重みをそのまま、日中なら0倍にしたRoutePreferenceの
        # コピーを探索コストへ渡す（self._route_preference自体は書き換えない、リクエスト間で
        # 共有される状態のため）。改善計画T352: axis_id"night"のハードコード分岐を
        # AxisDefinition.time_scopeによる汎用ロジックへ置き換えた
        # （RoutePreference.with_time_scope参照）。
        night_active = is_night(wind_and_night_origin, now)

        # --- 改善計画T536: bbox全体ぶんのコスト配列をリクエストにつき1回だけ合成する ---
        cost_started = time.monotonic()
        active_scopes = frozenset({"night_only"}) if night_active else frozenset()
        preference = self._route_preference.with_time_scope(active_scopes)
        weights = preference.weights

        # StaticEdgeScoreMatrix.axis_scores（Edge×公開軸の2次元配列）を軸id→1次元配列の
        # 辞書へ展開し、動的軸（風）だけをリクエスト時点の値へ上書きする
        # （evaluate_dynamic_axis_arrays、軸名を一切ハードコードしない汎用ディスパッチ、
        # domain/evaluation.py: DYNAMIC_MATERIAL_EVALUATORS参照）。
        static_axis_scores = {
            axis_id: score_matrix.axis_scores[:, i] for i, axis_id in enumerate(score_matrix.axis_ids)
        }
        dynamic_context = DynamicAxisRequestContext(bearing_deg=score_matrix.bearing_deg, weather=weather)
        resolved_axis_scores = evaluate_dynamic_axis_arrays(static_axis_scores, dynamic_context)
        # evaluate_dynamic_axis_arraysは内部軸も含めうるため、公開軸のみへ絞って合成する
        # （compute_edge_costs_bulkの計算フェーズと同じ絞り込み、domain/evaluation.py参照）。
        published_axis_arrays = {axis_id: resolved_axis_scores[axis_id] for axis_id in score_matrix.axis_ids}

        cost_array, difficulty_array = compose_costs_from_axis_matrix(
            score_matrix.distance_m, published_axis_arrays, weights, self._penalty_strength,
        )
        hard_filter_excluded = compute_hard_filter_excluded(
            score_matrix.is_motorway, score_matrix.is_trunk, score_matrix.no_bicycle,
            score_matrix.gradient_percent, self._hard_filters, self._max_average_grade_percent,
        )
        cost_array = np.where(hard_filter_excluded, np.inf, cost_array)
        cost_ms = round((time.monotonic() - cost_started) * 1000)

        cost_by_edge_id = dict(zip(score_matrix.edge_ids, cost_array.tolist()))
        full_edge_row = {edge_id: i for i, edge_id in enumerate(score_matrix.edge_ids)}

        # 改善計画T536→T537: LazyRoadGraph（Node/Edge payloadは整数index、domain/routing.py
        # 参照）の構築はタイル集合キーでキャッシュする（infrastructure/search_graph_cache.py、
        # _get_or_build_lazy_graph参照）。同じタイル集合への2回目以降のリクエストは
        # asyncio.to_thread自体を経由せず即座に返る。T536当時は`cost_by_edge_id`を渡して
        # 並行Edge（同一Node間の複数Edge）をcost最小で解消していたが、コストはリクエストごと
        # （軸重み・風・0次フィルタ）に変わるためタイル集合だけで決まるこのキャッシュとは
        # 両立しない——`_get_or_build_lazy_graph`のdocstring・モジュールdocstring「対応方針」
        # 節に判断理由を記載。
        graph_started = time.monotonic()
        lazy_graph, lazy_graph_cached = await _get_or_build_lazy_graph(tile_set, graph)
        graph_ms = round((time.monotonic() - graph_started) * 1000)

        # A*のcost_fnへ渡す配列はlazy_graph.edge_ids（並行Edge解消後）の行順に揃える。
        cost_list = [cost_by_edge_id[edge_id] for edge_id in lazy_graph.edge_ids]
        # A*のestimate_cost_fn（ヒューリスティック）をレグごとにnumpyで1回だけ計算できる
        # よう、lazy_graph.index_to_node_id順の緯度・経度配列を1回だけ構築する。
        node_lat = np.array([graph.nodes[node_id].latitude for node_id in lazy_graph.index_to_node_id])
        node_lon = np.array([graph.nodes[node_id].longitude for node_id in lazy_graph.index_to_node_id])

        total_ms = round((time.monotonic() - stage_started) * 1000)
        logger.info(
            "_build_search_graph edges=%d nodes=%d materials_ms=%d weather_ms=%d cost_ms=%d graph_ms=%d "
            "total_ms=%d lazy_graph_cached=%s",
            len(graph.edges), len(graph.nodes), materials_ms, weather_ms, cost_ms, graph_ms, total_ms,
            lazy_graph_cached,
        )

        return _SearchGraph(
            graph=graph,
            lazy_graph=lazy_graph,
            tile_set=tile_set,
            materials=edge_materials,
            accident_years_covered=accident_years_covered,
            weather=weather,
            night_active=night_active,
            cost_list=cost_list,
            full_edge_row=full_edge_row,
            difficulty_array=difficulty_array,
            axis_arrays=published_axis_arrays,
            node_lat=node_lat,
            node_lon=node_lon,
        )

    async def _get_or_build_node_index(
        self,
        tile_set: frozenset[tuple[int, int, int]] | None,
        graph: RoadGraphLike,
        materials: dict[str, EdgeMaterialBundle],
    ) -> tuple[NodeSpatialIndex, bool]:
        """0次フィルタ通過後のroutable Node空間索引（`NodeSpatialIndex`）を、タイル集合＋
        0次フィルタ設定（`hard_filters`・`max_average_grade_percent`、いずれも本エンジンの
        コンストラクタ引数でリクエスト間は変わらない）をキーにキャッシュする
        （改善計画T537、`infrastructure/search_graph_cache.py`）。

        `tile_set`がNone（`GraphService.get_search_materials_for_bbox`がsplit鮮度の古い
        bbox限定の再構築経路を通った場合）はキャッシュを経由せず毎回構築する
        （`_build_search_graph`のtile_set docstring参照）。戻り値の2つ目はキャッシュ
        ヒットしたかどうか（ログ用）。
        """
        key = None
        if tile_set is not None:
            key = (tile_set, self._hard_filters, self._max_average_grade_percent)
            cached = search_graph_cache.get_routable_index(key)
            if cached is not None:
                return cached, True
        routable_ids = await asyncio.to_thread(
            compute_routable_node_ids, graph, materials, self._hard_filters, self._max_average_grade_percent,
        )
        node_index = await asyncio.to_thread(build_node_spatial_index, graph, node_ids=routable_ids)
        if key is not None:
            search_graph_cache.set_routable_index(key, node_index)
        return node_index, False

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
        # 改善計画T522→T537: 索引構築（KDTree構築・Edge数十万件規模の辞書構築）は
        # タイル集合＋0次フィルタ設定キーでキャッシュする
        # （infrastructure/search_graph_cache.py、_get_or_build_node_index参照）。
        # 同じ組み合わせへの2回目以降のリクエストはasyncio.to_thread自体を経由せず
        # 即座に返る。find_nearest_node_indexedは既存索引への単発クエリでコストが軽い
        # ためキャッシュ対象にせずメインコルーチンのまま呼ぶ。
        index_started = time.monotonic()
        node_index, node_index_cached = await self._get_or_build_node_index(
            search.tile_set, search.graph, search.materials
        )
        origin_node = find_nearest_node_indexed(node_index, origin)
        if origin_node is None:
            return None
        index_ms = round((time.monotonic() - index_started) * 1000)
        logger.info(
            "prepare index build edges=%d index_ms=%d node_index_cached=%s",
            len(search.graph.edges), index_ms, node_index_cached,
        )

        return _RoadGraphContext(
            graph=search.graph,
            materials=search.materials,
            accident_years_covered=search.accident_years_covered,
            weather=search.weather,
            origin_node=origin_node,
            node_index=node_index,
            lazy_graph=search.lazy_graph,
            cost_list=search.cost_list,
            full_edge_row=search.full_edge_row,
            difficulty_array=search.difficulty_array,
            axis_arrays=search.axis_arrays,
            node_lat=search.node_lat,
            node_lon=search.node_lon,
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

        # 改善計画T256: prepareと同じ理由で、索引の候補を実際に経路探索可能なNodeのみに
        # 絞る（幹線道路にしか接続していない孤立Nodeを除外）。改善計画T529:
        # 旧`routable_node_ids`（sparse_graph算出）から`compute_routable_node_ids`
        # （0次ハードフィルタのみの軽量版）へ置き換えた（docs/tasks/T529.md参照）。
        # 改善計画T522→T537: prepareと同じ理由でタイル集合キーのキャッシュを経由する
        # （_get_or_build_node_index参照）。
        node_index, _node_index_cached = await self._get_or_build_node_index(
            search.tile_set, search.graph, search.materials
        )
        origin_node = find_nearest_node_indexed(node_index, origin)
        destination_node = find_nearest_node_indexed(node_index, destination)
        if origin_node is None or destination_node is None:
            return None

        # 改善計画T536: コストは_build_search_graphでbbox全体ぶん既に合成済み
        # （search.cost_list、lazy_graph.edge_ids順）のため、Edgeごとのコールバックは
        # 不要——素のlistインデックスアクセスをそのままedge_cost_fnとして渡す。
        cost_fn = search.cost_list.__getitem__
        estimate_fn = _build_estimate_cost_fn(search.graph, search.node_lat, search.node_lon, destination_node)
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

        # 改善計画T536: コストは_build_search_graphでbbox全体ぶん既に合成済み
        # （context.cost_list、lazy_graph.edge_ids順）のため、A*のedge_cost_fnは素の
        # listインデックスアクセスをそのまま渡す（Edgeごとのコールバック・キャッシュは
        # 不要になった）。estimate_fn（A*ヒューリスティック）はレグごとに目的地
        # （to_node）が変わるため、レグごとにnumpyで1回だけベクトル計算し直す。
        #
        # 改善計画T536（対応方針5）: 8方位のtrace_loopは`asyncio.to_thread`による並列を
        # やめ、直列（呼び出し元route_generator.pyのasyncio.gatherに委ねる、実質1スレッド）
        # で実行する。rustworkxはEdgeごとにPythonコールバックへ戻るためGILを手放せず、
        # 8スレッド並列は直列より約2秒遅いことを実測した（T522参照）。本関数は`_trace_
        # segments`を直接（awaitを挟まず）呼ぶ同期関数として実行するため、8方位分の
        # gatherは実質的に順番に完了する。
        cost_fn = context.cost_list.__getitem__

        def _trace_segments() -> list[list[str]] | None:
            segment_paths = []
            for from_node, to_node in zip(node_sequence, node_sequence[1:]):
                estimate_fn = _build_estimate_cost_fn(context.graph, context.node_lat, context.node_lon, to_node)
                segment_path = shortest_path_node_ids_lazy(
                    context.lazy_graph, from_node, to_node, cost_fn, estimate_fn
                )
                if segment_path is None:
                    return None
                segment_paths.append(segment_path)
            return segment_paths

        trace_started = time.monotonic()
        segment_paths = _trace_segments()
        trace_wall_ms = round((time.monotonic() - trace_started) * 1000)
        logger.info("trace_loop direction=%s wall_ms=%d", bearing, trace_wall_ms)
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

        reverse_edges = _reverse_traced_edges(edges_in_path, context.lazy_graph, context.graph)
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
        # 改善計画T522派生（評価ロジックの入口〜出口の見直し）: context.materials
        # （EdgeMaterialBundle、探索フェーズで既にDBから取得・タイル単位でプロセス内
        # キャッシュ済み）が対象Edgeの標高を既に持っていれば、それをそのまま使い
        # ElevationAttributeServiceへの問い合わせ自体を避ける。同じelevation_attributes
        # テーブルを候補確定後にもう一度読み直していた重複DB往復を解消する
        # （evaluate_loopsはasyncio.gatherで候補を並行評価するが、
        # ElevationAttributeService._repository_lockが内部で直列化するため、
        # 削減した往復の分だけ候補数[最大8]倍のレイテンシが積み上がっていた）。
        # 事前計算バッチが未実行のEdge（context.materials側がNone）だけ、従来どおり
        # ElevationAttributeService経由でその場取得・永続化する。
        cached: dict[str, ElevationAttribute] = {}
        missing_edges: list[EdgeLike] = []
        for edge in edges_in_path:
            bundle = context.materials.get(edge.edge_id)
            if bundle is not None and bundle.elevation_attribute is not None:
                cached[edge.edge_id] = bundle.elevation_attribute
            else:
                missing_edges.append(edge)

        if not missing_edges:
            return cached

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
            edges={edge.edge_id: edge for edge in missing_edges},
        )
        fetched = await self._elevation_attribute_service.get_attributes_for_graph(path_graph)
        return {**cached, **fetched}

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
        wind_score = _aggregate_wind_score(edges_in_path, context.weather)
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
        #
        # 改善計画T536: 軸別スコア・合成difficultyは、探索コスト算出時に既に合成済みの
        # `context.axis_arrays`/`context.difficulty_array`（`context.full_edge_row`で
        # edge_idから行indexを引く）からそのまま読む——以前は`compute_edge_axis_scores`/
        # `compute_cost_from_axis_scores`を区間ごとに再計算していたが（T143の非DRY構造）、
        # 探索と表示の二重計算を解消する（T522派生調査「評価ロジック入口〜出口の再点検」で
        # 指摘された1件）。重み（night時間帯スコープ含む）は探索コスト算出時点で既に
        # 折り込み済みのため、ここでpreferenceを再構築する必要も無くなった。
        segments = []
        cumulative_km = 0.0

        for edge in edges:
            distance_km = edge.distance_m / 1000
            elevation_attr = elevation_attributes.get(edge.edge_id)
            # 改善計画T533: surfaceは、Edge単位で統合済みの1オブジェクトから取り出す
            # （`domain/attributes.py: EdgeMaterialBundle`参照。stop_count等の他材料は
            # T536以降axis_difficultiesの再計算に使わないため取り出さない）。
            bundle = context.materials.get(edge.edge_id)
            surface_type = bundle.surface if bundle else None

            gradient_percent = elevation_attr.average_grade if elevation_attr else None
            wind_penalty = compute_wind_penalty(edge, context.weather)
            road_surface_good = classify_osm_surface(surface_type)

            row = context.full_edge_row.get(edge.edge_id)
            if row is None:
                # 通常は到達しない（full_edge_rowはbbox全体の生Edge集合を覆うため）。
                # 経路上のEdgeが何らかの理由で行を持たない防御的フォールバック。
                axis_scores: dict[str, float] = {}
                composite_difficulty_value: float | None = None
            else:
                axis_scores = {
                    axis_id: float(arr[row])
                    for axis_id, arr in context.axis_arrays.items()
                    if not math.isnan(arr[row])
                }
                difficulty_value = context.difficulty_array[row]
                composite_difficulty_value = None if math.isnan(difficulty_value) else float(difficulty_value)

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


async def _get_or_build_lazy_graph(
    tile_set: frozenset[tuple[int, int, int]] | None, graph: RoadGraphLike
) -> tuple[LazyRoadGraph, bool]:
    """探索用グラフ（`LazyRoadGraph`）をタイル集合キーでキャッシュする（改善計画T537、
    `infrastructure/search_graph_cache.py`）。

    `tile_set`は`GraphService.get_search_materials_for_bbox`が「bboxを覆う全z12タイルの
    材料キャッシュをそのまま結合したグラフ」を返した場合のみ設定される
    （`_build_search_graph`のtile_set docstring参照）。Noneの場合はキャッシュを経由せず
    毎回構築する。

    改善計画T536が復活させた「並行Edge（同一Node間の複数Edge）はcost最小を採用」
    （`build_lazy_road_graph`の`edge_cost_by_id`引数）は、コストがリクエストごと
    （軸重み・風・0次フィルタ）に変わるため、タイル集合だけで決まるこのキャッシュとは
    両立しない。本関数は`edge_cost_by_id`を渡さず、`build_lazy_road_graph`の決定的
    フォールバック（edge_idの昇順で先頭を採用、T529〜T534当時の挙動）で並行Edgeを
    解消する——2つの並行Edgeのうち一方だけがこのリクエストの0次フィルタで除外される
    稀なケースでは、cost最小方式なら自動的に許可される側が選ばれるが、この方式では
    選ばれない場合がある（`(u,v)`ペア自体が到達不能になる）。実データでの並行Edge自体が
    稀（旧`_build_node_pair_index`のdocstring参照）なうえ、その中でさらに片方だけ
    0次フィルタ対象という二重に稀な条件のため、同一タイル集合への2回目以降の
    リクエストでグラフ構築・索引構築を丸ごと省略できる利点を優先した
    （判断理由の詳細はdocs/tasks/T537.md参照）。

    戻り値の2つ目はキャッシュヒットしたかどうか（ログ用）。
    """
    if tile_set is not None:
        cached = search_graph_cache.get_lazy_graph(tile_set)
        if cached is not None:
            return cached, True
    lazy_graph = await asyncio.to_thread(build_lazy_road_graph, graph)
    if tile_set is not None:
        search_graph_cache.set_lazy_graph(tile_set, lazy_graph)
    return lazy_graph, False


def _build_estimate_cost_fn(
    graph: RoadGraphLike,
    node_lat: np.ndarray,
    node_lon: np.ndarray,
    target_node_id: str,
) -> Callable[[int], float]:
    """`shortest_path_node_ids_lazy`へ渡すA*のestimate_cost_fn（改善計画T529→T536）を、
    目的地ノード`target_node_id`への直線距離（m）として組み立てる。

    改善計画T536: レグごとに目的地が変わるたび、グラフ上の全Node分の直線距離を
    numpyで1回だけベクトル計算し（`haversine_distance_km_array`）、`list.__getitem__`を
    そのまま返す——Pythonの関数フレームを作らないA*の設計（`LazyRoadGraph`のdocstring
    参照）と揃える。`node_lat`/`node_lon`は`lazy_graph.index_to_node_id`と同じ行順
    （`_build_search_graph`がリクエストにつき1回だけ構築、レグごとの再構築はしない）。

    Edge Costは常に`cost >= distance_m`を満たす（`docs/decisions/t12-routing-scale.md`
    原則1「不変条件1」、ペナルティ倍率は常に1以上）ため、直線距離は実際のコストを
    過大評価しない下界＝admissibleなヒューリスティックになる。この不変条件は
    「将来のA*ヒューリスティック admissibility保存のため」と当時のADRが明記して
    意図的に維持してきたものであり、本タスクがその意図どおり利用する形になる。
    """
    target_node = graph.nodes[target_node_id]
    est_list: list[float] = (haversine_distance_km_array(node_lat, node_lon, target_node) * 1000).tolist()
    return est_list.__getitem__


def _reverse_traced_edges(
    edges_in_path: list[EdgeLike], lazy_graph: LazyRoadGraph, graph: RoadGraphLike
) -> list[EdgeLike] | None:
    """順方向の経路`edges_in_path`（起点→...→起点）を逆順に辿った場合の、対応する
    逆方向Edge列を構築する（改善計画T274）。経路中に一方通行（逆方向Edgeが存在しない）
    区間が1つでもあれば物理的に逆走不可能なため`None`を返す。

    改善計画T537: 以前は`_build_node_pair_index`（bboxの全Edgeから`(from,to)→Edge`の
    逆引き表を1リクエストにつき1回だけ構築、O(Edge数)）を使っていたが、これはタイル
    集合キーでキャッシュする`LazyRoadGraph`（改善計画T537、`_get_or_build_lazy_graph`）と
    重複する構造のため撤去した。代わりに、経路上のEdgeだけに対する遅延引きへ変える:
    `lazy_graph.edge_index_by_node_pair`（並行Edge解消後、`build_lazy_road_graph`が
    既に構築済み）で`(to_index, from_index)`→edge_indexを引き、`lazy_graph.edge_ids`で
    edge_idへ変換、`graph`（`context.graph`、フル解像度のトポロジ）から実際のEdgeを
    引く。並行Edge（同じNode対を複数のEdgeが結ぶ稀なケース）は`build_lazy_road_graph`の
    決定的な解消規則（旧`_build_node_pair_index`の「`graph.edges`挿入順で後勝ち」より
    決定的）に従う。`geometry`だけは逆方向Edge自体（lean、空プレースホルダ）からではなく、
    順方向で既にhydrate済みのgeometryを反転させて使う（同じ物理区間を逆順に辿るだけの
    ため、DB再取得不要。build_road_graphの`-bwd`Edgeが`-fwd`のgeometryを反転して持つのと
    同じ関係）。distance_m・osm_way_id・highwayは進行方向に依存しない値だが、
    「逆方向Edge自身の値」として引く（forward側からの流用ではなく、逆方向Edgeが実在する
    という確認を兼ねる）。
    """
    reverse_edges: list[EdgeLike] = []
    for edge in reversed(edges_in_path):
        from_index = lazy_graph.node_id_to_index.get(edge.to_node_id)
        to_index = lazy_graph.node_id_to_index.get(edge.from_node_id)
        reverse_edge_index = (
            lazy_graph.edge_index_by_node_pair.get((from_index, to_index))
            if from_index is not None and to_index is not None
            else None
        )
        reverse_topology = (
            graph.edges.get(lazy_graph.edge_ids[reverse_edge_index]) if reverse_edge_index is not None else None
        )
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
