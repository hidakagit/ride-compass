"""Road Graph + rustworkx（A*/Dijkstra、lazy評価）の自前ルーティングエンジン。

`RouteGenerator`（services/route_generator.py）の`LoopRoutingEngine`契約を実装する。
Road Graph・Evaluation Engine・Route Engine（domain/routing.py）を使って経由地点間の
経路を自前で計算する。ルート生成の唯一のエンジン実装。

設計の骨子（詳細はdocs/modules/backend/routing-engine.md参照）:
- **Road Graphの取得は1リクエストにつき1回だけ**: 候補ごとに個別のbboxで問い合わせず、
  起点を中心とした単一の円（折返し点候補をすべて覆う半径、`RouteGenerator.
  TURNAROUND_RADIUS_RATIO`）でRoad Graphを`prepare`で1回だけ取得し、全候補で共有する。
- **周回候補は8方位固定ではなく、公開軸の重み駆動のフロンティア方式で生成する**。
  `select_loop_turnarounds`が起点からの一対全最短経路木（`domain/routing.py:
  build_shortest_path_tree`、scipy）で「往路の実距離が目標の半分付近」のNode群
  （リング）を求め、往路の距離加重平均difficultyの昇順に折返し点候補を選ぶ
  （似た往路は`select_diverse_by_overlap`で間引く）。`trace_loop_from_turnaround`が
  往路（木の経路そのもの、再探索しない）に、往路Edge＋逆方向Edgeのコストを一時的に
  `RETRACE_PENALTY_MULTIPLIER`倍へ差し替えて探索した復路（A*）を継いで周回にする。
  経由地・目的地指定ルート（`trace_loop`）は指定地点列を順にA*で結ぶ。
- **標高（勾配）は事前計算済みの`elevation_attributes`をキー参照するだけで探索コストへ
  組み込まれる**（その場でのGSI API問い合わせは発生しない）。`evaluate_loops`側の標高
  取得（`ElevationAttributeService`経由、こちらは未計算Edgeがあればその場で取得し
  repositoryへ永続化する）は、経路確定後の表示・スコアリング向けとして引き続き別に行う
  （`elevation_attributes`テーブルを両者が共有するキャッシュ層として参照する構図。
  事前計算が漏れているEdgeは探索コスト側でgradient軸のみ「データ無し」扱いになるが、
  他の軸で評価は継続する）。
- 風は出発時点の起点付近の風をルート全体に一様適用する（探索中は到達時刻が未確定のため、
  区間ごとの推定到達時刻の風は使わない）。
- **Edgeコストは「タイル単位の静的スコア行列＋リクエスト時ベクトル計算」で求める**:
  タイル読込時（`GraphService._get_or_build_tile_materials`）に「Edge×公開軸」の
  静的スコア行列（`domain/evaluation.py: StaticEdgeScoreMatrix`、風など動的軸の列は
  NaN）を1回だけ構築してキャッシュし、リクエスト時にその行列＋動的軸（風、
  `evaluate_dynamic_axis_arrays`）＋重みベクトルからコスト配列を**bbox全体ぶん1回だけ**
  numpyで合成する。`LazyRoadGraph`のEdge/Node payloadは整数indexにし、A*
  （`domain/routing.py: shortest_path_node_ids_lazy`）へは`edge_cost_fn=cost_list.
  __getitem__`のような素のlistインデックスアクセスを渡す——探索中にPythonの関数
  フレームを一切作らない。同一Node間の並行Edgeは、`build_lazy_road_graph`の決定的
  フォールバック（edge_idの昇順で先頭を採用）で解消する——タイル集合だけで決まる
  キャッシュとコストベースの動的解消（cost最小を採用）は両立しないため、実データで稀な
  並行Edgeの厳密さより探索用グラフのキャッシュ再利用を優先している（並行Edgeのうち
  一方だけが0次フィルタで除外される稀なケースでは、cost最小方式なら自動的に許可される
  側が選ばれるが、この方式では選ばれない場合がある。判断理由の詳細はdocs/tasks/T537.md
  参照）。
- `_build_segment_details`（区間表示）も探索と同じコスト配列・スコア行列から
  `axis_difficulties`を引く（探索と表示の二重計算を避ける）。
- 候補ごとの復路探索（`trace_loop_from_turnaround`）・経由地ルートの`trace_loop`は
  直列実行する（`asyncio.to_thread`による並列化は、rustworkxがGILを解放しないため
  複数スレッドが競合しむしろ遅くなる。`trace_loop_from_turnaround`は共有`cost_list`を
  一時的に書き換えるため、並列化とは両立しない）。
- **探索用グラフ（`LazyRoadGraph`）・routable Node空間索引（`NodeSpatialIndex`）は
  タイル集合キーのプロセス内LRU（`infrastructure/search_graph_cache.py`）でキャッシュ
  する**（これらはタイル集合と0次フィルタ[`hard_filters`・`max_average_grade_percent`]
  だけで決まる純粋な派生物のため、同じタイル集合への2回目以降のリクエストはこれらの
  構築自体を丸ごと省略できる）。`_reverse_traced_edges`はキャッシュ済み`LazyRoadGraph.
  edge_index_by_node_pair`（並行Edge解消後、経路上のEdgeだけに対する遅延引き）を使う。
"""

import asyncio
import logging
import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np

from app.domain.attributes import EdgeMaterialBundle, ElevationAttribute
from app.domain.axis_definitions import AXIS_DEFINITIONS, REQUEST_DYNAMIC_MATERIAL_IDS, dynamic_axis_topological_order
from app.domain.difficulty import distance_weighted_difficulty
from app.domain.dynamic_way_values import map_value_kind
from app.domain.errors import RoutingError
from app.domain.evaluation import (
    StaticEdgeScoreMatrix,
    DynamicAxisRequestContext,
    RoutePreference,
    compose_costs_from_axis_matrix,
    compute_hard_filter_excluded,
    compute_routable_node_ids,
    evaluate_dynamic_axis_arrays,
)
from app.domain.geo import (
    KM_PER_DEGREE_LATITUDE,
    bearing_between,
    bearing_between_array,
    haversine_distance_km,
    haversine_distance_km_array,
)
from app.domain.graph import EdgeLike, LeanEdge, LeanRoadGraph, RoadGraphLike
from app.domain.region import BoundingBox
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
    SearchGraphStatics,
    build_lazy_road_graph,
    build_node_spatial_index,
    build_search_graph_statics,
    build_shortest_path_tree,
    concat_node_paths,
    find_missing_lazy_graph_edge_id,
    find_nearest_node_indexed,
    overlap_ratio,
    path_to_edge_ids_lazy,
    path_to_edge_indices_lazy,
    select_diverse_by_overlap,
    shortest_path_node_ids_lazy,
    tree_path_edge_indices,
    tree_path_edge_indices_to_source,
)
from app.domain.weather import WeatherConditions
from app.domain.wind import ASSUMED_SPEED_KMH, ROUTE_DETOUR_RATIO, WindForecastSeries, estimate_passage_hours, kmh_to_ms
from app.infrastructure import search_graph_cache
from app.services.elevation_aggregation import max_or_none, min_or_none, sum_or_none
from app.services.elevation_attribute_service import ElevationAttributeService
from app.services.graph_service import GraphService
from app.services.route_generator import JST, LoopTurnaround, TracedLoop, candidate_identity
from app.services.weather_service import WeatherService

# Road Graphを取得するbboxは、起点・経由地2点の外接矩形にこのマージンを足したもの。
# 実際の道なりは直線距離の外接矩形からはみ出ることが多い（川・線路等を迂回する等）ため、
# 探索が失敗しない程度の余裕を持たせる。半径に比例させつつ最低値を設ける暫定値であり、
# 実データでの検証結果次第で見直す（docs/architecture.md参照）。
BBOX_MARGIN_RATIO = 0.3
BBOX_MARGIN_MIN_KM = 2.0

# preview_segment（起点・終点2点間の単発経路確認）が使うbboxマージン。
# ループ探索のBBOX_MARGIN_MIN_KMと同じ「道なりが直線外接矩形からはみ出る余裕」を
# 単純な固定値で持たせる（previewは距離が事前に分からないため半径比例のロジックは使えない）。
PREVIEW_BBOX_MARGIN_KM = 2.0

# --- フロンティア方式の折返し点選定・復路探索のパラメータ（実測調整前提） ---
# 復路探索の間、往路Edge（＋同一Node対の逆方向Edge）のコストへ掛ける倍率。infにはしない
# （復路が往路を戻る以外に道が無い区間[袋小路等]は通れる必要がある）。
RETRACE_PENALTY_MULTIPLIER = 8.0
# 折返し点候補同士の最小距離（km）。近接Nodeは同じ周回の変種にしかならないため間引く。
MIN_TURNAROUND_SEPARATION_KM = 1.5
# 折返し点候補の往路同士の重複率（距離加重）の上限。同一コリドー上の候補が上位を独占し
# 往路の大半を共有する似た周回がn件並ぶのを防ぐ。プールが埋まらない場合は緩和値で再試行。
TURNAROUND_MAX_OVERLAP_RATIO = 0.6
TURNAROUND_RELAXED_OVERLAP_RATIO = 0.85
# 採用済み候補との周回全体（往路＋復路、進行方向無視）の重複率上限。
# 往路だけを見るTURNAROUND_MAX_OVERLAP_RATIOより緩め——「同じ周回の逆回り」（往路と復路が
# 入れ替わっただけ）や「往路は違うが復路が同じ裏道へ収束する」周回を弾くための、
# より緩い最終チェック。
LOOP_MAX_OVERLAP_RATIO = 0.7
# ランキング上位から間引き判定にかけるリングNode数の上限（往路の経路復元コストの上限）。
MAX_RING_CANDIDATES_EXAMINED = 4000
# 周回全長／往路実距離の比の想定範囲。往路は軸コスト最適経路、復路はその往路を避けて探索
# するため、復路は往路と同程度以上に長くなる（dev実DB・東京駅20kmの実測で1.8〜2.8、中央値
# 約2.05）。リング（折返し候補の往路実距離の範囲）は、この比で周回全長が目標±許容に
# 収まるよう`[(目標-許容)/MIN, (目標+許容)/MAX]`に置く（許容が狭く範囲が反転する場合は
# `目標/2 ± 許容/2`へ戻す）。
LOOP_TO_OUTBOUND_RATIO_MIN = 2.0
LOOP_TO_OUTBOUND_RATIO_MAX = 2.3
# リング中心（タイブレーク「リング中心に近い順」の基準）の比率。上下限の単純平均ではなく
# 目標距離をこの比率で割った値を使う——許容が目標距離以上のとき下限が0でクランプされ、
# 上下限の算術平均だと中心が0付近まで引き下げられ極端に短い往路が上位に来るため。
RING_CENTER_RATIO = (LOOP_TO_OUTBOUND_RATIO_MIN + LOOP_TO_OUTBOUND_RATIO_MAX) / 2.0
# 一対全探索のコスト上限（リング上限×(1+P)）に掛ける余裕。Edge単位の丸め（0.1m）の
# 積み上がりで上限ぎりぎりのNodeを取りこぼさないため。
COST_LIMIT_SLACK = 1.01

# --- 目的地ルート（via-node方式、経由地無し）の代替経路選定パラメータ ---
# via-node候補（前向き木＋後ろ向き木の合成経路）の長さが、最も合成コストの低い経路
# （＝経由地無しの従来の単一生成が返す経路と同じ）の長さの何倍までを候補にするか。
ALTERNATIVE_MAX_STRETCH = 1.3
# 採用済み候補との経路全体（前向き＋後ろ向き）の重複率上限。TURNAROUND_MAX_OVERLAP_RATIO/
# TURNAROUND_RELAXED_OVERLAP_RATIOと同じ役割・同じ値を使う（周回の往路間引きと同じ
# 「同一コリドー上の候補を間引く」意図のため、値を変える理由が無い）。
VIA_NODE_MAX_OVERLAP_RATIO = TURNAROUND_MAX_OVERLAP_RATIO
VIA_NODE_RELAXED_OVERLAP_RATIO = TURNAROUND_RELAXED_OVERLAP_RATIO
# ランキング上位から間引き判定にかけるvia-node候補数の上限（MAX_RING_CANDIDATES_EXAMINEDと
# 同じ役割）。目的地ルートのbboxは周回より小さいため周回より小さい上限にする。
MAX_VIA_NODE_CANDIDATES_EXAMINED = 2000

logger = logging.getLogger("ridecompass.graph")


@dataclass
class LegCostArrays:
    """1レグぶんの合成済みコスト配列一式。`cost_list`は`lazy_graph.edge_ids`順（A*・一対全木へ
    `list.__getitem__`のまま渡す）、それ以外は`score_matrix.edge_ids`（`full_edge_row`）順の
    表示用配列。レグごとに違うのは風（各Edgeの通過予定時刻の風）だけで、静的軸の列は共有する。"""

    label: str
    cost_list: list[float]
    difficulty_array: np.ndarray
    axis_arrays: dict[str, np.ndarray]
    contribution_arrays: dict[str, np.ndarray]
    # `full_edge_row`順の動的材料id→配列（`evaluate_dynamic_material_arrays`が返す全材料が
    # 対象、全行NaNの材料はキーを持たない）。区間表示・`material_values`の集計が、
    # 探索コストの合成と同じ動的入力から求めた値を読むために保持する。
    material_arrays: dict[str, np.ndarray]
    # `full_edge_row`順の通過予定時刻（出発からの経過時間[h]）。時変化しないレグはNone。
    passage_hours: np.ndarray | None


class _LegCostComposer:
    """bbox全体ぶんのコスト配列を、レグ（基準点・時刻オフセット・向き）ごとに合成する。
    静的スコア行列・重み・0次フィルタ・lazy_graph行順の対応表はリクエスト内で共通のため
    1回だけ用意し、`compose`はレグごとに変わる風の列だけを引き直して合成する。
    風の時別系列が無い・風に依存する公開軸の重みが0・基準点が無い場合は、出発時点の
    スナップショットで合成した1本（`snapshot`）を全レグで共有する（追加コストゼロ）。"""

    def __init__(
        self,
        score_matrix: StaticEdgeScoreMatrix,
        weights: dict[str, float],
        penalty_strength: float,
        hard_filter_excluded: np.ndarray,
        weather: WeatherConditions | None,
        wind_series: WindForecastSeries | None,
        start: datetime,
        speed_kmh: float,
        lazy_row_index: np.ndarray,
        detour_ratio: float = ROUTE_DETOUR_RATIO,
        lens_axis_id: str | None = None,
    ) -> None:
        self._score_matrix = score_matrix
        self._static_axis_scores = {
            axis_id: score_matrix.axis_scores[:, i] for i, axis_id in enumerate(score_matrix.axis_ids)
        }
        self._weights = weights
        self._penalty_strength = penalty_strength
        self._hard_filter_excluded = hard_filter_excluded
        self._weather = weather
        self._wind_series = wind_series
        self.start = start
        self.speed_kmh = speed_kmh
        self._lazy_row_index = lazy_row_index
        self._lens_axis_id = lens_axis_id
        # 通過予定時刻の推定に使う迂回率（道なり距離÷直線距離）。探索範囲ごとの学習値が
        # あればそれ、無ければ`ROUTE_DETOUR_RATIO`。`compose`の引数で個別に上書きできる。
        self.detour_ratio = detour_ratio
        # 風に依存する公開軸のうち、探索の重みが0より大きいもの、または地図のレンズが表示を
        # 要求している軸（重み0でも区間表示にはレグごとの風が要る）があれば時変化合成する。
        wind_dependent_axes = set(dynamic_axis_topological_order(AXIS_DEFINITIONS)) & set(score_matrix.axis_ids)
        self.time_varying = wind_series is not None and any(
            weights.get(axis_id, 0.0) > 0 or axis_id == lens_axis_id for axis_id in wind_dependent_axes
        )
        self._cache: dict[tuple, LegCostArrays] = {}

    def compose(
        self,
        label: str,
        anchor: Coordinates | None,
        offset_hours: float,
        direction: int,
        detour_ratio: float | None = None,
    ) -> LegCostArrays:
        """`anchor`から`direction=+1`なら離れていく・`-1`なら向かっていくレグとして、各Edgeの
        通過予定時刻（`offset_hours`基準、`domain/wind.py: estimate_passage_hours`）の風で
        コスト配列を合成する。`detour_ratio`を渡すとそのレグだけ迂回率を上書きする
        （復路が往路木の実測値を使うため）。"""
        ratio = self.detour_ratio if detour_ratio is None else detour_ratio
        if not self.time_varying or anchor is None:
            key: tuple = ("snapshot",)
            passage = None
        else:
            key = (round(anchor.latitude, 5), round(anchor.longitude, 5), round(offset_hours, 3), direction, round(ratio, 3))
            passage = estimate_passage_hours(
                self._score_matrix.mid_lat, self._score_matrix.mid_lon, anchor, offset_hours, direction, self.speed_kmh,
                detour_ratio=ratio,
            )
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        started = time.monotonic()
        dynamic_context = DynamicAxisRequestContext(
            bearing_deg=self._score_matrix.bearing_deg, weather=self._weather, travel_speed_ms=kmh_to_ms(self.speed_kmh),
            wind_series=self._wind_series, start=self.start, passage_hours=passage,
        )
        resolved = evaluate_dynamic_axis_arrays(self._static_axis_scores, dynamic_context)
        # evaluate_dynamic_axis_arraysは内部軸も含めうるため、公開軸のみへ絞って合成する。
        published = {axis_id: resolved[axis_id] for axis_id in self._score_matrix.axis_ids}
        cost_array, difficulty_array, contribution_arrays = compose_costs_from_axis_matrix(
            self._score_matrix.distance_m, published, self._weights, self._penalty_strength,
        )
        cost_array = np.where(self._hard_filter_excluded, np.inf, cost_array)
        material_arrays = {
            material_id: resolved[material_id]
            for material_id in REQUEST_DYNAMIC_MATERIAL_IDS
            if material_id in resolved and not np.all(np.isnan(resolved[material_id]))
        }
        leg = LegCostArrays(
            label=label,
            cost_list=cost_array[self._lazy_row_index].tolist(),
            difficulty_array=difficulty_array,
            axis_arrays=published,
            contribution_arrays=contribution_arrays,
            material_arrays=material_arrays,
            passage_hours=passage,
        )
        self._cache[key] = leg
        if passage is None:
            logger.info("compose_leg_costs leg=%s mode=snapshot compose_ms=%d", label,
                        round((time.monotonic() - started) * 1000))
        else:
            logger.info(
                "compose_leg_costs leg=%s mode=time_varying anchor=(%.2f,%.2f) offset_h=%.2f direction=%+d "
                "detour_ratio=%.2f passage_h=[%.2f,%.2f] compose_ms=%d",
                label, anchor.latitude, anchor.longitude, offset_hours, direction, ratio,
                float(passage.min()), float(passage.max()), round((time.monotonic() - started) * 1000),
            )
        return leg


@dataclass
class _RoadGraphContext:
    """prepareで構築し、全方位のtrace_loop/evaluate_loopsで共有するリクエスト単位の状態。"""

    graph: RoadGraphLike
    # Edge単位で`EdgeMaterialBundle`へ統合した1辞書（`domain/attributes.py:
    # EdgeMaterialBundle`のdocstring参照）。Edge単位の材料アクセスは探索コスト算出の
    # ホットパスからは外れているが、`_build_segment_details`の表示用フィールド
    # （surface等）取得には引き続き使う。
    materials: dict[str, EdgeMaterialBundle]
    accident_years_covered: int
    weather: WeatherConditions | None
    origin_node: str
    # 1リクエスト内で繰り返し呼ばれるfind_nearest_node相当（prepareの起点・trace_loopの
    # 各経由地と目的地・preview_segmentの両端）を都度線形探索せず使い回すための索引
    # （domain/routing.py参照）。
    node_index: NodeSpatialIndex
    # trace_loopが実際のA*探索に使うrustworkxベースの探索用グラフ
    # （Node/Edge payloadは整数index、domain/routing.py: LazyRoadGraph参照）。
    # タイル集合キーでキャッシュ済み（infrastructure/search_graph_cache.py）。
    # `_reverse_traced_edges`が`edge_index_by_node_pair`を逆回り候補のEdge逆引きにも使う。
    lazy_graph: LazyRoadGraph
    # レグごとのコスト配列を合成する部品と、合成済みのレグ配列（添字0=往路[起点から離れる
    # レグ]、周回・目的地ルートは1=復路[基準点へ向かうレグ]、経由地ルートはレグ番号順）。
    # `TracedLoop.leg_of_edge`がこの添字を指す。
    composer: _LegCostComposer
    legs: list[LegCostArrays]
    # `score_matrix.edge_ids`（並行Edge解消前、bbox全体の生Edge集合）上でのedge_id→行index
    # の対応表。各レグの表示用配列と組み合わせて`_build_segment_details`が引く。
    full_edge_row: dict[str, int]
    # 周回の復路レグ・目的地ルートの後ろ向き木の基準点に使う起点座標。
    origin: Coordinates
    # A*のestimate_cost_fn（ヒューリスティック）を、レグごとの目的地に対して
    # numpyで1回だけベクトル計算するための、lazy_graph.index_to_node_id順の緯度・経度配列。
    node_lat: np.ndarray
    node_lon: np.ndarray
    # prepare実行時点で起点が市民薄明の外（夜間）だったかどうか。search_edge_costs
    # 構築時に使った値と同じものを_build_segment_details（表示用difficulty）でも使い、探索コストと
    # 表示を一致させる（詳細はprepare()参照）。
    night_active: bool
    # 一対全最短経路木用のCSR構造＋Edge実距離配列（タイル集合キーでキャッシュ済み、
    # domain/routing.py: SearchGraphStatics参照）。build_shortest_path_treeへは
    # cost_listをそのまま渡す（内部でnp.asarray済みのため、同じ内容を2つ持たない）。
    statics: SearchGraphStatics
    # origin_nodeのlazy_graph上のNode index（一対全木の起点）。
    origin_index: int
    # `select_via_nodes`が目的地からの後ろ向き木（転置CSR）をタイル集合キーで
    # キャッシュ・取得するために保持する（`_SearchGraph.tile_set`と同じ値、`SearchGraphStatics`
    # と違い後ろ向き木は目的地ルートでしか使わないため`prepare`では構築しない）。
    tile_set: frozenset[tuple[int, int, int]] | None
    # 復路探索（折返し点→起点）のA*ヒューリスティック配列。目的地が常に起点の
    # ため、リクエストで1回だけ計算し全候補で共有する（初回の復路探索時に遅延構築）。
    origin_estimate: list[float] | None = None
    # select_via_nodesが目的地を最寄りのアクセス可能なNodeへ補正した場合の
    # 実際の座標（補正が無ければNone）。RouteGenerator.last_no_candidates_reasonと同じ
    # side channel——Protocolの戻り値型（list[TracedLoop]）を変えずにRouteGenerator側へ
    # 伝える。
    destination_correction: Coordinates | None = None


@dataclass
class _SearchGraph:
    """`prepare`・`preview_segment`共通の「bboxに対する探索用グラフ＋材料一式」。
    wind/night軸・0次ハードフィルタ等の探索コスト算出ロジックを
    `_build_search_graph`1箇所にまとめ、ループ探索・単発区間確認の両方で重複させない。
    `SearchGraphStatics`（一対全木用のCSR構造）は持たない——`preview_segment`は2点間の
    直接A*しか行わず一対全木を使わないため、必要な`prepare`だけが自前で構築・保持する
    （`_RoadGraphContext.statics`参照）。
    """

    graph: RoadGraphLike
    lazy_graph: LazyRoadGraph
    # bboxを覆うz12タイル集合（frozenset[(zoom,x,y)]）。GraphService.
    # get_search_materials_for_bboxが「タイルキャッシュをそのまま結合したgraph」を
    # 返した場合のみ設定される（split鮮度が古いbbox限定の再構築経路ではNone）。
    # prepare/preview_segmentがroutable Node索引のキャッシュキーとして使い回す。
    tile_set: frozenset[tuple[int, int, int]] | None
    # _RoadGraphContextと同じ理由でEdgeMaterialBundleへ統合済み。
    materials: dict[str, EdgeMaterialBundle]
    accident_years_covered: int
    weather: WeatherConditions | None
    night_active: bool
    # _RoadGraphContextと同じ意味（フィールドdocstring参照）。`outbound`は基準点（起点側の
    # 座標）から離れていくレグとして合成済みの配列。
    composer: _LegCostComposer
    outbound: LegCostArrays
    full_edge_row: dict[str, int]
    node_lat: np.ndarray
    node_lon: np.ndarray
    # `score_matrix.edge_ids`と、それに対応する0次フィルタ除外配列
    # （`compute_hard_filter_excluded`、cost_arrayをinfにするのに使ったのと同じ配列）。
    # `_get_or_build_node_index`がroutable Node判定にこの配列をそのまま使い回すことで、
    # `materials`（EdgeMaterialBundle辞書/EdgeMaterialTable）への依存を持たない。
    edge_ids: list[str]
    hard_filter_excluded: np.ndarray


@dataclass(frozen=True)
class _TurnaroundData:
    """`LoopTurnaround.data`（本エンジン固有）: 折返し点のNodeと、一対全木上の往路
    （`LazyRoadGraph`のEdge index列）。`trace_loop_from_turnaround`が復路探索に使う。"""

    node_id: str
    outbound_edge_indices: list[int]
    outbound_length_m: float


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
        assumed_speed_kmh: float = ASSUMED_SPEED_KMH,
        lens_axis_id: str | None = None,
    ):
        self._graph_service = graph_service
        # 地図のレンズが表示を要求している軸id（無ければNone）。重み0の軸でも区間表示の
        # ために風の時変化合成を行う判定にだけ使う（探索コストには影響しない）。
        self._lens_axis_id = lens_axis_id
        # 仮定巡航速度（km/h、リクエスト単位で上書き可）。各Edgeの通過予定時刻・区間の
        # 到達予想時刻・所要時間の算出に使う。
        self._assumed_speed_kmh = assumed_speed_kmh
        self._elevation_attribute_service = elevation_attribute_service
        # EvaluationService（compute_edge_costs_bulkのbbox全体一括評価）は本エンジンから
        # 不要（探索コストは_build_search_graphがbbox全体ぶんリクエストにつき1回だけ
        # ベクトル合成する）。EvaluationServiceクラス自体・compute_edge_costs_bulkは
        # 回帰テストオラクルとして残置——静的スコア行列（StaticEdgeScoreMatrix）が同じ
        # 抽出・計算フェーズ（_evaluate_axes_bulk）を共有するため、両者の一致は引き続き
        # tests/test_evaluation_bulk.pyで検証する。
        self._weather_service = weather_service
        self._route_preference = route_preference
        # T12 ADR原則1: コスト式`distance × (1 + P × difficulty/100)`のP。
        # 既定1.0の挙動は最悪でも距離2倍。
        self._penalty_strength = penalty_strength
        # T12 ADR原則5: 0次ハードフィルタの勾配しきい値（%、既定None＝
        # 除外しない）。domain/evaluation.py: is_edge_allowed参照。
        self._max_average_grade_percent = max_average_grade_percent
        # 0次ハードフィルタ名（no_bicycle/motorway/trunk）の個別ON/OFF上書き
        # （既定None＝DEFAULT_HARD_FILTERS＝全フィルタ有効）。
        self._hard_filters = hard_filters

    async def _build_search_graph(
        self, bbox: BoundingBox, wind_and_night_origin: Coordinates, now: datetime
    ) -> _SearchGraph | None:
        """bboxに対する探索用グラフ（lazy_graph）＋bbox全体ぶんのコスト配列を構築する
        （`prepare`・`preview_segment`共通）。wind/night軸の判定は
        `wind_and_night_origin`（周回ならその起点、区間確認なら起点側の座標）を基準にする
        ——探索中は到達時刻が未確定のため出発時刻の近似として使う簡略化はどちらの用途でも
        変わらない（モジュールdocstring参照）。

        `GraphService.get_search_materials_for_bbox`が返す
        `StaticEdgeScoreMatrix`（タイル単位でキャッシュ済みの静的Edge×公開軸スコア行列）に
        対し、動的軸（風、`evaluate_dynamic_axis_arrays`）と重みベクトルを適用して
        コスト配列を**bbox全体ぶん1回だけ**numpyで合成する。これがEdgeごとのPython
        コールバックを排除する設計の核心（`LazyRoadGraph`のNode/Edge payloadを整数index
        にし、探索本体[`shortest_path_node_ids_lazy`]へは合成済みの`list.__getitem__`を
        渡すだけにする）。
        """
        # prepare全体のどの区間が時間を占めているか原因特定できるよう、ステージ別に計測する。
        stage_started = time.monotonic()

        # トポロジ＋材料＋静的スコア行列をz12タイル単位のプロセス内キャッシュ経由で
        # まとめて取得する（同一エリアへの2回目以降のリクエストはDBアクセスもEdge単位の
        # Python評価も一切発生しない、graph_service.pyのget_search_materials_for_bbox参照）。
        built = await self._graph_service.get_search_materials_for_bbox(bbox)
        materials_ms = round((time.monotonic() - stage_started) * 1000)
        if built is None:
            return None
        search_materials, score_matrix, tile_set = built
        if not search_materials.graph.edges:
            return None
        graph = search_materials.graph
        # surface・edge_attribute_counts（stop/intersection/accident件数）・
        # way_tags・elevation_attribute・is_designatedは、Edge単位で`EdgeMaterialBundle`へ
        # 統合済みの1辞書としてそのまま使う（表示用[_build_segment_details]の
        # 一部フィールド取得にのみ使う）。
        edge_materials = search_materials.materials
        # accident_years_coveredは密度の「件/(km・年)」正規化に使う（bboxに依存しない
        # グローバル値、GraphService側でプロセス内キャッシュ済み）。
        accident_years_covered = await self._graph_service.get_accident_years_covered()

        weather_started = time.monotonic()
        weather = await self._weather_service.get_conditions(wind_and_night_origin)
        # 起点の時別風予報（get_conditionsと同じ応答・キャッシュ。追加の外部API呼び出しは無い）。
        wind_series = await self._weather_service.get_wind_forecast_series(wind_and_night_origin)
        weather_ms = round((time.monotonic() - weather_started) * 1000)
        # 通過予定時刻の基準（出発時刻）。時別系列はJSTのローカル時刻のため揃える。
        start = now.astimezone(JST).replace(tzinfo=None)
        # 時間帯依存軸（time_scope="night_only"、現在はnight軸のみ）の動的化。区間ごとの
        # 到達時刻は探索中は未確定のため（風と同じモジュールdocstringの制約）、出発地点の
        # 座標・呼び出し時点を出発時刻の近似として採用し、起点が市民薄明の外（夜間）なら
        # night_only軸の重みをそのまま、日中なら0倍にしたRoutePreferenceのコピーを探索
        # コストへ渡す（self._route_preference自体は書き換えない、リクエスト間で共有される
        # 状態のため）。axis_id"night"のハードコードではなくAxisDefinition.time_scopeに
        # よる汎用ロジックで判定する（RoutePreference.with_time_scope参照）。
        night_active = is_night(wind_and_night_origin, now)

        # --- bbox全体ぶんのコスト配列の合成（レグごと。まず起点から離れる往路レグ） ---
        cost_started = time.monotonic()
        active_scopes = frozenset({"night_only"}) if night_active else frozenset()
        preference = self._route_preference.with_time_scope(active_scopes)
        weights = preference.weights
        hard_filter_excluded = compute_hard_filter_excluded(
            score_matrix.is_motorway, score_matrix.is_trunk, score_matrix.no_bicycle,
            score_matrix.gradient_percent, self._hard_filters, self._max_average_grade_percent,
        )
        full_edge_row = {edge_id: i for i, edge_id in enumerate(score_matrix.edge_ids)}

        # LazyRoadGraph（Node/Edge payloadは整数index、domain/routing.py参照）の構築は
        # タイル集合キーでキャッシュする（infrastructure/search_graph_cache.py、
        # _get_or_build_lazy_graph参照）。並行Edge（同一Node間の複数Edge）の解消はコストに
        # 依存しない決定的な規則で行う——コストはリクエストごと（軸重み・風・0次フィルタ）に
        # 変わるためタイル集合だけで決まるこのキャッシュとは両立しない。
        graph_started = time.monotonic()
        lazy_graph, lazy_graph_cached = await _get_or_build_lazy_graph(tile_set, graph)
        # 再split後の`lazy_graph`・`graph`不整合の検知・再構築は、直後の
        # `full_edge_row[edge_id] for edge_id in lazy_graph.edge_ids`が同種のKeyErrorに
        # 脆弱なため、`prepare`・`preview_segment`共通のこの経路で行う。
        lazy_graph = await _ensure_lazy_graph_consistent(tile_set, lazy_graph, graph)
        graph_ms = round((time.monotonic() - graph_started) * 1000)

        # lazy_graph.edge_ids（並行Edge解消後）の各行が`score_matrix`のどの行かの対応表。
        # レグごとのcost_listはこの索引でnumpyのfancy indexingにより並べ替える。
        lazy_row_index = np.fromiter((full_edge_row[edge_id] for edge_id in lazy_graph.edge_ids), dtype=np.int64, count=len(lazy_graph.edge_ids))
        # 迂回率は同じ探索範囲で前回の往路木から学習した値があればそれを使う（無ければ既定値）。
        learned_detour_ratio = search_graph_cache.get_detour_ratio(tile_set) if tile_set is not None else None
        composer = _LegCostComposer(
            score_matrix, weights, self._penalty_strength, hard_filter_excluded, weather, wind_series,
            start, self._assumed_speed_kmh, lazy_row_index,
            detour_ratio=learned_detour_ratio if learned_detour_ratio is not None else ROUTE_DETOUR_RATIO,
            lens_axis_id=self._lens_axis_id,
        )
        outbound = composer.compose("outbound", wind_and_night_origin, 0.0, +1)
        cost_ms = round((time.monotonic() - cost_started) * 1000) - graph_ms
        # 重み付き軸がすべてNaNのEdge比率（探索コストはbbox内平均difficultyで補完される。
        # 実際の発生頻度を把握するためのサマリ）。
        missing_axis_mask = np.isnan(outbound.difficulty_array)
        total_distance_m = float(score_matrix.distance_m.sum())
        missing_axis_distance_ratio = (
            float(score_matrix.distance_m[missing_axis_mask].sum() / total_distance_m)
            if total_distance_m > 0 else 0.0
        )

        # A*のestimate_cost_fn（ヒューリスティック）をレグごとにnumpyで1回だけ計算できる
        # よう、lazy_graph.index_to_node_id順の緯度・経度配列を1回だけ構築する。
        node_lat = np.array([graph.nodes[node_id].latitude for node_id in lazy_graph.index_to_node_id])
        node_lon = np.array([graph.nodes[node_id].longitude for node_id in lazy_graph.index_to_node_id])

        total_ms = round((time.monotonic() - stage_started) * 1000)
        logger.info(
            "_build_search_graph edges=%d nodes=%d materials_ms=%d weather_ms=%d cost_ms=%d graph_ms=%d "
            "total_ms=%d lazy_graph_cached=%s wind_time_varying=%s speed_kmh=%.1f detour_ratio=%.2f(%s) "
            "missing_axis_edges=%d missing_axis_distance_ratio=%.3f",
            len(graph.edges), len(graph.nodes), materials_ms, weather_ms, cost_ms, graph_ms, total_ms,
            lazy_graph_cached, composer.time_varying, self._assumed_speed_kmh, composer.detour_ratio,
            "learned" if learned_detour_ratio is not None else "default",
            int(missing_axis_mask.sum()), missing_axis_distance_ratio,
        )

        return _SearchGraph(
            graph=graph,
            lazy_graph=lazy_graph,
            tile_set=tile_set,
            materials=edge_materials,
            accident_years_covered=accident_years_covered,
            weather=weather,
            night_active=night_active,
            composer=composer,
            outbound=outbound,
            full_edge_row=full_edge_row,
            node_lat=node_lat,
            node_lon=node_lon,
            edge_ids=score_matrix.edge_ids,
            hard_filter_excluded=hard_filter_excluded,
        )

    async def _get_or_build_node_index(
        self,
        tile_set: frozenset[tuple[int, int, int]] | None,
        graph: RoadGraphLike,
        edge_ids: list[str],
        hard_filter_excluded: np.ndarray,
    ) -> tuple[NodeSpatialIndex, bool]:
        """0次フィルタ通過後のroutable Node空間索引（`NodeSpatialIndex`）を、タイル集合＋
        0次フィルタ設定（`hard_filters`・`max_average_grade_percent`、いずれも本エンジンの
        コンストラクタ引数でリクエスト間は変わらない）をキーにキャッシュする
        （`infrastructure/search_graph_cache.py`）。

        `tile_set`がNone（`GraphService.get_search_materials_for_bbox`がsplit鮮度の古い
        bbox限定の再構築経路を通った場合）はキャッシュを経由せず毎回構築する
        （`_build_search_graph`のtile_set docstring参照）。戻り値の2つ目はキャッシュ
        ヒットしたかどうか（ログ用）。

        `hard_filter_excluded`は`_build_search_graph`がコスト配列を
        `inf`にするのに使ったのと同じ配列（`compute_hard_filter_excluded`の戻り値、
        `edge_ids`と同じ行順）。呼び出し元がこれをそのまま渡すため、
        `compute_routable_node_ids`はEdgeMaterialBundle辞書/EdgeMaterialTableへ一切
        アクセスしない（タイル材料キャッシュの復元コストと完全に独立になる）。
        """
        key = None
        if tile_set is not None:
            key = (tile_set, self._hard_filters, self._max_average_grade_percent)
            cached = search_graph_cache.get_routable_index(key)
            if cached is not None:
                return cached, True
        routable_ids = await asyncio.to_thread(compute_routable_node_ids, graph, edge_ids, hard_filter_excluded)
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
        # nowはnight軸判定用（省略時は実際の現在時刻）。テストが任意の時刻を
        # 注入できるよう引数化した（wind同様、探索中は到達時刻が未確定のためprepare実行時点を
        # 出発時刻の近似として使う簡略化、詳細は_build_search_graph参照）。
        now = now or datetime.now(timezone.utc)
        if waypoints:
            # ユーザー指定の経由地は起点から半径radius_km以内とは限らない
            # ため、周回探索の円形bbox（_bbox_around_point）ではなく、preview_segmentと
            # 同じ「複数点の外接矩形+固定マージン」を使う。
            bbox = _bbox_covering_points([origin, *waypoints], PREVIEW_BBOX_MARGIN_KM)
        else:
            margin_km = max(BBOX_MARGIN_MIN_KM, radius_km * BBOX_MARGIN_RATIO)
            bbox = _bbox_around_point(origin, radius_km + margin_km)

        search = await self._build_search_graph(bbox, origin, now)
        if search is None:
            return None

        # このgraphに対する索引を1回だけ構築し、原点＋trace_loopの
        # 経由地スナップ（経由地・目的地ルートの各地点）すべてで使い回す。
        # 索引の候補は実際に経路探索可能な（Hard Constraint通過後も
        # 次数1以上の）Nodeのみに絞る。絞らないと、幹線道路（highway=trunk等）にしか
        # 接続していない地理的最近傍Node（新宿駅・渋谷駅等、駅前が国道の交差点に直接
        # 面する場所が実例）が選ばれ、そこがHard Constraint除外後のグラフ上では
        # 孤立点になるため、すべての折返し点・経由地への探索が"no path found"で失敗してしまう。
        # lazy評価ではEdgeコストを事前計算しないため、0次ハードフィルタだけを軽量に評価する
        # `compute_routable_node_ids`（domain/evaluation.py）を使う。
        # 索引構築（KDTree構築・Edge数十万件規模の辞書構築）は
        # タイル集合＋0次フィルタ設定キーでキャッシュする
        # （infrastructure/search_graph_cache.py、_get_or_build_node_index参照）。
        # 同じ組み合わせへの2回目以降のリクエストはasyncio.to_thread自体を経由せず
        # 即座に返る。find_nearest_node_indexedは既存索引への単発クエリでコストが軽い
        # ためキャッシュ対象にせずメインコルーチンのまま呼ぶ。
        index_started = time.monotonic()
        node_index, node_index_cached = await self._get_or_build_node_index(
            search.tile_set, search.graph, search.edge_ids, search.hard_filter_excluded
        )
        origin_node = find_nearest_node_indexed(node_index, origin)
        if origin_node is None:
            return None
        index_ms = round((time.monotonic() - index_started) * 1000)
        logger.info(
            "prepare index build edges=%d index_ms=%d node_index_cached=%s",
            len(search.graph.edges), index_ms, node_index_cached,
        )

        # 一対全木用のCSR構造（SearchGraphStatics）は、それを実際に使う
        # select_loop_turnarounds/is_loop_too_similarの前段であるここ（prepare）だけが
        # 構築・キャッシュする（preview_segmentは_build_search_graph止まりで構築しない）。
        # search.lazy_graphは_build_search_graph内で整合性検証済みのため、ここでは
        # 単純なキャッシュ参照/構築のみで再構築ロジックを持たない。
        statics_started = time.monotonic()
        statics, statics_cached = await _get_or_build_search_statics(search.tile_set, search.lazy_graph, search.graph)
        statics_ms = round((time.monotonic() - statics_started) * 1000)
        logger.info(
            "prepare search_statics build edges=%d statics_ms=%d statics_cached=%s",
            len(search.graph.edges), statics_ms, statics_cached,
        )

        return _RoadGraphContext(
            graph=search.graph,
            materials=search.materials,
            accident_years_covered=search.accident_years_covered,
            weather=search.weather,
            origin_node=origin_node,
            node_index=node_index,
            lazy_graph=search.lazy_graph,
            composer=search.composer,
            legs=[search.outbound],
            full_edge_row=search.full_edge_row,
            origin=origin,
            node_lat=search.node_lat,
            node_lon=search.node_lon,
            night_active=search.night_active,
            statics=statics,
            origin_index=search.lazy_graph.node_id_to_index[origin_node],
            tile_set=search.tile_set,
        )

    async def preview_segment(
        self, origin: Coordinates, destination: Coordinates, now: datetime | None = None
    ) -> RouteSegment | None:
        """起点・終点2点間の単発区間確認（`/api/routes/preview`）。

        `prepare`＋`trace_loop`（周回・3レグ探索）とは異なり、1回の最短経路探索のみを行う。
        探索コストは`generate`と同じ評価軸重み付き（`RoutePreference`）を使う——ORSの
        previewのような単純最短距離ではなく、`penalty_strength`等の研究パラメータも含めて
        generateと一貫した経路選択にする。
        経路が見つからない場合はNoneを返す（呼び出し元がRoutingErrorへ変換する）。
        """
        now = now or datetime.now(timezone.utc)
        bbox = _bbox_covering_points([origin, destination], PREVIEW_BBOX_MARGIN_KM)

        search = await self._build_search_graph(bbox, origin, now)
        if search is None:
            return None

        # prepareと同じ理由で、索引の候補を実際に経路探索可能なNodeのみに
        # 絞る（幹線道路にしか接続していない孤立Nodeを除外）。0次ハードフィルタのみの
        # 軽量版`compute_routable_node_ids`を使い、prepareと同じ理由でタイル集合キーの
        # キャッシュを経由する（_get_or_build_node_index参照）。
        node_index, _node_index_cached = await self._get_or_build_node_index(
            search.tile_set, search.graph, search.edge_ids, search.hard_filter_excluded
        )
        origin_node = find_nearest_node_indexed(node_index, origin)
        destination_node = find_nearest_node_indexed(node_index, destination)
        if origin_node is None or destination_node is None:
            return None

        # コストは_build_search_graphでbbox全体ぶん既に合成済み
        # （search.cost_list、lazy_graph.edge_ids順）のため、Edgeごとのコールバックは
        # 不要——素のlistインデックスアクセスをそのままedge_cost_fnとして渡す。
        cost_fn = search.outbound.cost_list.__getitem__
        estimate_fn = _build_estimate_cost_fn(search.graph, search.node_lat, search.node_lon, destination_node)
        path = await asyncio.to_thread(
            shortest_path_node_ids_lazy, search.lazy_graph, origin_node, destination_node, cost_fn, estimate_fn
        )
        if path is None:
            return None
        edge_ids = path_to_edge_ids_lazy(search.lazy_graph, path)
        if not edge_ids:
            return None

        # prepareと同じレイジー取得（prepareがlean=Trueで読み込んだ
        # search.graphのEdgeはgeometryが空プレースホルダのため、この経路ぶんだけ取得し直す）。
        hydrated = await self._graph_service.get_edges_with_geometry(edge_ids)
        edges_in_path: list[EdgeLike] = [hydrated.get(edge_id) or search.graph.edges[edge_id] for edge_id in edge_ids]

        distance_km = round(sum(edge.distance_m for edge in edges_in_path) / 1000, 2)
        geometry = _concat_edge_geometries(edges_in_path)
        # road_graphエンジンは実測所要時間モデルを持たないため、他所（segments構築時の
        # estimated_arrival_time）と同じASSUMED_SPEED_KMHで概算する。
        duration_minutes = round(distance_km / self._assumed_speed_kmh * 60, 1)

        return RouteSegment(distance_km=distance_km, duration_minutes=duration_minutes, geometry=geometry)

    async def trace_loop(
        self,
        context: _RoadGraphContext,
        waypoints: list[Coordinates],
        bearing: int | None,
    ) -> TracedLoop:
        """指定地点列を順にA*で結ぶ（経由地・目的地指定ルート）。
        周回候補（フロンティア方式）は`select_loop_turnarounds`＋
        `trace_loop_from_turnaround`が担い、本メソッドは通らない。

        waypoints = [起点, 中間経由地..., 終点]。起点は最近接Nodeをprepareでスナップ
        したNodeを使い、中間経由地はここでスナップする（prepareで構築済みの
        索引を使い回す、都度線形探索しない）。戻り値の`data`は経路上のedge_id列
        （実ジオメトリの取得は距離フィルタ通過後の`evaluate_loops`が行う）。
        """
        interior_nodes = []
        for point in waypoints[1:-1]:
            node = find_nearest_node_indexed(context.node_index, point)
            if node is None:
                raise RoutingError(f"direction {bearing}: could not snap waypoints to road graph")
            interior_nodes.append(node)
        # 終点が起点と同一座標（周回）ならprepareで特別扱い済みの
        # context.origin_nodeをそのまま再利用する（起終点を同じNodeに揃えないと周回が
        # 閉じない）。終点が起点と異なる座標（目的地ルート）の場合のみ
        # find_nearest_node_indexedで独立にスナップする。
        end_point = waypoints[-1]
        if end_point.latitude == waypoints[0].latitude and end_point.longitude == waypoints[0].longitude:
            end_node = context.origin_node
        else:
            end_node = find_nearest_node_indexed(context.node_index, end_point)
            if end_node is None:
                raise RoutingError(f"direction {bearing}: could not snap destination to road graph")
        node_sequence = [context.origin_node, *interior_nodes, end_node]

        # コストは_build_search_graphでbbox全体ぶん既に合成済み
        # （context.cost_list、lazy_graph.edge_ids順）のため、A*のedge_cost_fnは素の
        # listインデックスアクセスをそのまま渡す。estimate_fn（A*ヒューリスティック）は
        # レグごとに目的地（to_node）が変わるため、レグごとにnumpyで1回だけベクトル計算し直す。
        # 探索は`asyncio.to_thread`で包まず直列に行う（モジュールdocstring参照）。
        # レグごとに、レグ起点を基準点・それまでの累積実距離を時刻オフセットとして
        # コスト配列を合成する（レグ0は起点から離れる往路レグそのもの）。
        def _trace_segments() -> list[list[str]] | None:
            segment_paths: list[list[str]] = []
            context.legs = context.legs[:1]
            cumulative_m = 0.0
            for leg_index, (from_node, to_node) in enumerate(zip(node_sequence, node_sequence[1:])):
                if leg_index == 0:
                    leg = context.legs[0]
                else:
                    from_coordinates = context.graph.nodes[from_node]
                    leg = context.composer.compose(
                        f"leg{leg_index}",
                        Coordinates(latitude=from_coordinates.latitude, longitude=from_coordinates.longitude),
                        cumulative_m / 1000 / context.composer.speed_kmh, +1,
                    )
                    context.legs.append(leg)
                estimate_fn = _build_estimate_cost_fn(context.graph, context.node_lat, context.node_lon, to_node)
                segment_path = shortest_path_node_ids_lazy(
                    context.lazy_graph, from_node, to_node, leg.cost_list.__getitem__, estimate_fn
                )
                if segment_path is None:
                    return None
                segment_paths.append(segment_path)
                cumulative_m += sum(
                    context.graph.edges[edge_id].distance_m
                    for edge_id in path_to_edge_ids_lazy(context.lazy_graph, segment_path)
                )
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
        distance_km = round(sum(context.graph.edges[edge_id].distance_m for edge_id in edge_ids) / 1000, 2)
        leg_of_edge = [
            leg_index for leg_index, segment_path in enumerate(segment_paths) for _ in range(len(segment_path) - 1)
        ]
        return TracedLoop(bearing=bearing, distance_km=distance_km, data=edge_ids, leg_of_edge=leg_of_edge)

    async def select_loop_turnarounds(
        self,
        context: _RoadGraphContext,
        distance_km: float,
        distance_tolerance_km: float,
        pool_size: int,
    ) -> list[LoopTurnaround]:
        """折返し点候補を往路の軸的な良さの順に最大`pool_size`件選ぶ。

        1. 起点からの一対全最短経路木（`domain/routing.py: build_shortest_path_tree`、
           軸重み付きコスト、scipy）を1回だけ求める。探索はコスト上限
           （リング上限×(1+P)、`cost >= distance`の不変条件による安全な上限）で打ち切る。
        2. 木に沿った往路の**実距離**が`[(目標-許容)/LOOP_TO_OUTBOUND_RATIO_MIN,
           (目標+許容)/LOOP_TO_OUTBOUND_RATIO_MAX]`に入るNodeを「リング」として抽出する
           （最短実距離ではなく軸コスト最適経路の実距離で定義する——重みを極端に振った
           設定ほど往路が遠回りするため、最短実距離基準だと往路だけで目標の半分を超え
           距離フィルタで全滅する。比の範囲は復路が往路より長くなりやすい実測に基づく）。
        3. 往路の距離加重平均difficulty `(cost/len - 1)/P`（コスト式の逆算、
           overall_difficultyと同じ物差し）の昇順に並べる。同点（小数1桁）は
           「往路実距離がリング中心に近い順」、さらにNode index順で決定的にする。
        4. 上位から順に、既採用候補と往路の重複率が`TURNAROUND_MAX_OVERLAP_RATIO`を
           超えるもの・`MIN_TURNAROUND_SEPARATION_KM`より近いものを飛ばして`pool_size`件
           採る（同一コリドー上の隣接Nodeが上位を独占し似た周回が並ぶのを防ぐ）。
           埋まらなければ閾値を`TURNAROUND_RELAXED_OVERLAP_RATIO`へ緩めてやり直す。
        """
        target_m = distance_km * 1000.0
        tolerance_m = distance_tolerance_km * 1000.0
        ring_lower_m = max(0.0, (target_m - tolerance_m) / LOOP_TO_OUTBOUND_RATIO_MIN)
        ring_upper_m = (target_m + tolerance_m) / LOOP_TO_OUTBOUND_RATIO_MAX
        if ring_lower_m > ring_upper_m:
            ring_lower_m = max(0.0, (target_m - tolerance_m) / 2.0)
            ring_upper_m = (target_m + tolerance_m) / 2.0
        ring_center_m = target_m / RING_CENTER_RATIO
        cost_limit = ring_upper_m * (1.0 + max(self._penalty_strength, 0.0)) * COST_LIMIT_SLACK
        statics = context.statics

        tree_started = time.monotonic()
        tree = await asyncio.to_thread(
            build_shortest_path_tree,
            statics.csr, context.legs[0].cost_list, statics.edge_length_m, context.origin_index, cost_limit,
        )
        tree_ms = round((time.monotonic() - tree_started) * 1000)

        length = tree.length_m
        in_ring = (length >= ring_lower_m) & (length <= ring_upper_m)
        in_ring[context.origin_index] = False
        ring = np.flatnonzero(in_ring)
        if len(ring) == 0:
            logger.info(
                "select_turnarounds ring_nodes=0 reached=%d ring_km=[%.1f,%.1f] tree_ms=%d",
                int(np.isfinite(tree.cost).sum()), ring_lower_m / 1000, ring_upper_m / 1000, tree_ms,
            )
            return []

        ring_length = length[ring]
        # 迂回率（道なり距離÷直線距離）の実測中央値。復路レグの合成に使い、同じ探索範囲の
        # 次のリクエストが往路レグに使えるよう学習値として保存する。
        detour_ratio_median = _median_detour_ratio(context, ring, ring_length)
        inbound_detour_ratio = _learn_detour_ratio(context, detour_ratio_median)
        # 復路レグ: 起点へ向かうレグとして、周回の総所要時間（目標距離÷仮定速度）を起点への
        # 到着予定時刻に置いて合成する（距離フィルタが目標±許容を強制するため定数扱いできる）。
        inbound = context.composer.compose(
            "inbound", context.origin, distance_km / context.composer.speed_kmh, -1, detour_ratio=inbound_detour_ratio,
        )
        context.legs = [context.legs[0], inbound]
        if self._penalty_strength > 0:
            with np.errstate(invalid="ignore", divide="ignore"):
                difficulty = (tree.cost[ring] / ring_length - 1.0) / self._penalty_strength * 100.0
            difficulty = np.where(np.isfinite(difficulty), difficulty, 0.0)
        else:
            # P=0はコスト＝距離（難易度を一切考慮しない）なので全候補同点。
            difficulty = np.zeros(len(ring))
        difficulty_key = np.round(difficulty, 1)
        closeness_key = np.abs(ring_length - ring_center_m)
        order = np.lexsort((ring, closeness_key, difficulty_key))[:MAX_RING_CANDIDATES_EXAMINED]
        ranked = ring[order]
        # difficulty_by_node／方位／近接判定用平面座標は、以降で実際に引かれうる`ranked`
        # （上限MAX_RING_CANDIDATES_EXAMINED件）ぶんだけ用意する。
        ranked_list = ranked.tolist()
        difficulty_by_node = dict(zip(ranked_list, difficulty_key[order].tolist()))
        # 同点（difficulty_keyが等しい）候補はグループとして渡し、グループ内の試行順は
        # 「採用済み候補との方位角距離の最小値が最大」（最遠点貪欲法、方位は生成機構ではなく
        # 同点タイブレーク専用）で採用のたびに決め直す。difficulty群自体の順序（主キー）・
        # 同点でない候補間の順序は変えない。
        origin_node = context.graph.nodes[context.origin_node]
        bearing_by_node = dict(zip(
            ranked_list,
            bearing_between_array(origin_node, context.node_lat[ranked], context.node_lon[ranked]).tolist(),
        ))
        closeness_by_node = dict(zip(ranked_list, closeness_key[order].tolist()))
        tie_groups = [
            group.tolist() for group in np.split(ranked, np.flatnonzero(np.diff(difficulty_key[order])) + 1)
        ]

        def prefer(remaining: Sequence[int], selected: list[int]) -> list[int]:
            return _order_by_bearing_spread(remaining, selected, bearing_by_node, closeness_by_node)

        lazy_graph = context.lazy_graph
        outbound_cache: dict[int, list[int] | None] = {}

        def outbound_edges(node_index: int) -> list[int] | None:
            if node_index not in outbound_cache:
                outbound_cache[node_index] = tree_path_edge_indices(tree, lazy_graph, node_index)
            return outbound_cache[node_index]

        # 近接判定は、緯度経度を起点基準の平面km座標へ1回だけ変換し（東京規模のbboxでは
        # 等距円筒近似で十分）、採用済み候補との平方距離をPythonのfloat演算で比べる
        # （候補ごとにnumpyのhaversineを呼ぶと数千件×2パスで0.5秒近くかかる）。far_enoughは
        # ranked由来のnode_indexしか引かないため、座標変換もranked分だけに限定する
        # （グラフ全Node分のリストを毎回作らない）。
        min_separation_sq = MIN_TURNAROUND_SEPARATION_KM ** 2
        lat0 = float(context.node_lat[context.origin_index])
        km_per_deg_lon = KM_PER_DEGREE_LATITUDE * math.cos(math.radians(lat0))
        ranked_lat = context.node_lat[ranked] * KM_PER_DEGREE_LATITUDE
        ranked_lon = context.node_lon[ranked] * km_per_deg_lon
        node_y = dict(zip(ranked_list, ranked_lat.tolist()))
        node_x = dict(zip(ranked_list, ranked_lon.tolist()))

        def far_enough(node_index: int, selected: list[int]) -> bool:
            x, y = node_x[node_index], node_y[node_index]
            for other in selected:
                dx = x - node_x[other]
                dy = y - node_y[other]
                if dx * dx + dy * dy < min_separation_sq:
                    return False
            return True

        # 「1回目の閾値→埋まらなければ2回目の緩和閾値で再検査」はselect_diverse_by_overlap
        # 内のループが行う（呼び出し側は1回呼ぶだけでよい）。
        selected = select_diverse_by_overlap(
            [], outbound_edges, statics.edge_length_m,
            [TURNAROUND_MAX_OVERLAP_RATIO, TURNAROUND_RELAXED_OVERLAP_RATIO], pool_size, far_enough,
            tie_groups=tie_groups, prefer=prefer,
        )

        turnarounds: list[LoopTurnaround] = []
        for node_index in selected:
            edges = outbound_edges(node_index)
            if not edges:
                continue
            node_id = lazy_graph.index_to_node_id[node_index]
            node = context.graph.nodes[node_id]
            bearing = int(round(bearing_between(origin_node, node))) % 360
            turnarounds.append(
                LoopTurnaround(
                    bearing=bearing,
                    outbound_difficulty=float(difficulty_by_node[node_index]),
                    data=_TurnaroundData(
                        node_id=node_id, outbound_edge_indices=edges,
                        outbound_length_m=float(length[node_index]),
                    ),
                )
            )
        logger.info(
            "select_turnarounds ring_nodes=%d examined=%d selected=%d pool=%d "
            "ring_km=[%.1f,%.1f] detour_ratio_median=%.2f tree_ms=%d total_ms=%d",
            len(ring), len(ranked_list), len(turnarounds), pool_size,
            ring_lower_m / 1000, ring_upper_m / 1000, detour_ratio_median, tree_ms,
            round((time.monotonic() - tree_started) * 1000),
        )
        return turnarounds

    async def select_via_nodes(
        self, context: _RoadGraphContext, destination: Coordinates, max_routes: int
    ) -> list[TracedLoop]:
        """目的地ルート（起点→目的地、経由地無し）のvia-node方式で、互いに異なる経路を
        最大`max_routes`件返す。周回のretraceペナルティ付き復路探索
        （`trace_loop_from_turnaround`）とは異なり、起点からの前向き木・目的地からの
        後ろ向き木（CSRの転置、`_get_or_build_reverse_search_statics`）を各1回求めれば、
        どのNode（via-node）を経由する経路も両木の経路復元だけで確定するため、候補ごとの
        追加探索が発生しない。

        1. 全Nodeについて経由路長`len_f+len_b`・合成コスト`cost_f+cost_b`をベクトル計算し、
           合成コスト最小のNode（＝経由地無しの従来の単一生成が返す経路と同じ、"最良路"）の
           長さの`ALTERNATIVE_MAX_STRETCH`倍以内のNodeだけを候補にする。
        2. 平均difficulty`(合成コスト/経由路長-1)/P`昇順に並べる。ただし最良路のNodeは常に
           先頭へ回す——合成コスト最小であっても、伸び率の許す範囲でより平均difficultyの
           低い経路が他に存在すれば難易度順ではそちらが上位に来うるため、「最良路は必ず
           結果に含まれる」（docs/tasks/T551.md完了条件）をランキングとは独立に保証する。
        3. `select_diverse_by_overlap`で、前向き経路・後ろ向き経路が同じEdgeを共有する
           Node（行って戻る形になり経路として成立しない）を除外しつつ、採用済み候補との
           重複率が閾値超のものを飛ばして`max_routes`件採る。

        目的地に一番近いNodeが、メインの道路網から孤立した小さな塊
        （歩道橋・私有地内通路等、次数1以上ではあるが起点からは実質到達できない場所）に
        スナップされていると、後ろ向き木が起点側とほぼ重ならず毎回0件になる。前向き木で
        実際に届くかをここで確認し、届かなければ「前向き木が届くNode」だけに絞って
        最寄りへ再スナップする（`context.destination_correction`に実際の座標を残す）。
        """
        lazy_graph = context.lazy_graph
        destination_node = find_nearest_node_indexed(context.node_index, destination)
        if destination_node is None:
            logger.warning("select_via_nodes destination_node=None (not snapped to routable graph)")
            return []
        destination_index = lazy_graph.node_id_to_index[destination_node]

        tree_started = time.monotonic()
        forward_tree = await asyncio.to_thread(
            build_shortest_path_tree,
            context.statics.csr, context.legs[0].cost_list, context.statics.edge_length_m, context.origin_index,
        )

        if not np.isfinite(forward_tree.cost[destination_index]):
            corrected_node = find_nearest_node_indexed(
                context.node_index, destination,
                predicate=lambda node_id: np.isfinite(forward_tree.cost[lazy_graph.node_id_to_index[node_id]]),
            )
            if corrected_node is None:
                logger.warning(
                    "select_via_nodes destination unreachable from origin, no accessible alternative found "
                    "destination_node=%s",
                    destination_node,
                )
                return []
            destination_node = corrected_node
            destination_index = lazy_graph.node_id_to_index[destination_node]
            corrected = context.graph.nodes[destination_node]
            destination = Coordinates(latitude=corrected.latitude, longitude=corrected.longitude)
            context.destination_correction = destination
            logger.warning(
                "select_via_nodes corrected destination to nearest accessible node lat=%.5f lon=%.5f",
                destination.latitude, destination.longitude,
            )

        reverse_statics, reverse_statics_cached = await _get_or_build_reverse_search_statics(
            context.tile_set, lazy_graph, context.graph
        )
        # 迂回率は前向き木（起点から1km以上先の到達Node）の実測中央値を使い、学習値として保存する。
        reached = np.flatnonzero(np.isfinite(forward_tree.cost) & (forward_tree.length_m >= 1000.0))
        detour_ratio_median = _median_detour_ratio(context, reached, forward_tree.length_m[reached])
        inbound_detour_ratio = _learn_detour_ratio(context, detour_ratio_median)
        # 後ろ向き木は目的地へ向かうレグ: 目的地を基準点に、到着予定時刻を
        # 「起点〜目的地の直線距離×迂回率÷仮定速度」に置いて合成する。
        arrival_hours = (
            inbound_detour_ratio * haversine_distance_km(context.origin, destination) / context.composer.speed_kmh
        )
        inbound = context.composer.compose("inbound", destination, arrival_hours, -1, detour_ratio=inbound_detour_ratio)
        context.legs = [context.legs[0], inbound]
        backward_tree = await asyncio.to_thread(
            build_shortest_path_tree,
            reverse_statics.csr, inbound.cost_list, reverse_statics.edge_length_m, destination_index,
        )
        tree_ms = round((time.monotonic() - tree_started) * 1000)

        combined_cost = forward_tree.cost + backward_tree.cost
        combined_length = forward_tree.length_m + backward_tree.length_m
        reachable = np.isfinite(combined_cost)
        if not np.any(reachable):
            # 改善計画docs/logging.md「候補0件はWARNINGへ昇格し、原因の内訳を同じ行に含める」:
            # 前向き木・後ろ向き木のどちらがどれだけ到達できているかを内訳として出す
            # （前向きのみ0なら起点側、後ろ向きのみ0なら目的地側の孤立を疑える）。
            logger.warning(
                "select_via_nodes reachable=0 forward_reached=%d backward_reached=%d "
                "destination_reached_by_forward=%s origin_reached_by_backward=%s "
                "tree_ms=%d reverse_statics_cached=%s",
                int(np.isfinite(forward_tree.cost).sum()), int(np.isfinite(backward_tree.cost).sum()),
                bool(np.isfinite(forward_tree.cost[destination_index])),
                bool(np.isfinite(backward_tree.cost[context.origin_index])),
                tree_ms, reverse_statics_cached,
            )
            return []

        best_index = int(np.argmin(np.where(reachable, combined_cost, np.inf)))
        best_length_m = float(combined_length[best_index])
        within_stretch = reachable & (combined_length <= best_length_m * ALTERNATIVE_MAX_STRETCH)
        candidates = np.flatnonzero(within_stretch)[:MAX_VIA_NODE_CANDIDATES_EXAMINED]

        if self._penalty_strength > 0:
            with np.errstate(invalid="ignore", divide="ignore"):
                difficulty = (
                    (combined_cost[candidates] / combined_length[candidates] - 1.0) / self._penalty_strength * 100.0
                )
            difficulty = np.where(np.isfinite(difficulty), difficulty, 0.0)
        else:
            # P=0はコスト＝距離（難易度を一切考慮しない）なので全候補同点。
            difficulty = np.zeros(len(candidates))
        difficulty_key = np.round(difficulty, 1)
        order = np.lexsort((candidates, difficulty_key))
        ranked = candidates[order].tolist()
        if best_index in ranked:
            ranked.remove(best_index)
        ranked.insert(0, best_index)

        full_edges_cache: dict[int, list[int] | None] = {}
        forward_edge_count: dict[int, int] = {}

        def full_edges(node_index: int) -> list[int] | None:
            if node_index not in full_edges_cache:
                forward_edges = tree_path_edge_indices(forward_tree, lazy_graph, node_index)
                backward_edges = tree_path_edge_indices_to_source(backward_tree, lazy_graph, node_index)
                if forward_edges is None or backward_edges is None:
                    full_edges_cache[node_index] = None
                else:
                    # 行って戻る形（前向き・後ろ向きが同じ物理区間を通る）の判定は、
                    # is_loop_too_similarと同じ進行方向を無視した物理区間キーで行う——
                    # 同じ道でも逆方向Edge（別のedge_id/index）を通れば単純なEdge index
                    # 集合の比較では検出できないため。
                    forward_ids = [lazy_graph.edge_ids[i] for i in forward_edges]
                    backward_ids = [lazy_graph.edge_ids[i] for i in backward_edges]
                    forward_segments = _loop_edge_lengths_by_physical_segment(context.graph, forward_ids)
                    backward_segments = _loop_edge_lengths_by_physical_segment(context.graph, backward_ids)
                    if forward_segments.keys() & backward_segments.keys():
                        full_edges_cache[node_index] = None
                    else:
                        full_edges_cache[node_index] = forward_edges + backward_edges
                        forward_edge_count[node_index] = len(forward_edges)
            return full_edges_cache[node_index]

        selected = select_diverse_by_overlap(
            ranked, full_edges, context.statics.edge_length_m,
            [VIA_NODE_MAX_OVERLAP_RATIO, VIA_NODE_RELAXED_OVERLAP_RATIO], max_routes,
        )

        traced: list[TracedLoop] = []
        for node_index in selected:
            edges = full_edges(node_index)
            if not edges:
                continue
            edge_ids = [lazy_graph.edge_ids[index] for index in edges]
            distance_km = round(sum(context.graph.edges[edge_id].distance_m for edge_id in edge_ids) / 1000, 2)
            forward_count = forward_edge_count[node_index]
            leg_of_edge = [0] * forward_count + [1] * (len(edge_ids) - forward_count)
            traced.append(TracedLoop(bearing=None, distance_km=distance_km, data=edge_ids, leg_of_edge=leg_of_edge))

        logger.info(
            "select_via_nodes reachable=%d within_stretch=%d examined=%d selected=%d max_routes=%d "
            "best_km=%.1f detour_ratio_median=%.2f tree_ms=%d reverse_statics_cached=%s",
            int(reachable.sum()), len(candidates), len(ranked), len(traced), max_routes,
            best_length_m / 1000, detour_ratio_median, tree_ms, reverse_statics_cached,
        )
        return traced

    async def trace_loop_from_turnaround(self, context: _RoadGraphContext, turnaround: LoopTurnaround) -> TracedLoop:
        """往路（一対全木上の経路、`select_loop_turnarounds`で確定済み）に、往路と別の
        復路（折返し点→起点のA*）を継いで周回にする。

        復路探索の間だけ、往路Edge＋同一Node対の逆方向Edgeのコストを
        `RETRACE_PENALTY_MULTIPLIER`倍に**差し替え**、探索後に元へ戻す（`cost_list`の
        コピーは1回10ms超[56万Edge]でプール分積み上がるため、差し替え＋復元で
        O(往路Edge数)にする）。この差し替えはawaitを挟まない同期区間で完結するため、
        asyncioの協調スケジューリング下では他コルーチンから見えない。**将来
        `asyncio.to_thread`等で復路探索を並列化する場合は、共有`cost_list`を書き換える
        この方式は成立しない**（tests/test_road_graph_engine.pyの回帰テスト参照）。
        倍率は有限のため、復路が往路を戻る以外に道が無い区間（袋小路・起点付近の
        単一の道）は自然にそのまま通れる。
        """
        data: _TurnaroundData = turnaround.data
        lazy_graph = context.lazy_graph
        graph = context.graph
        # 復路レグのコスト配列（select_loop_turnaroundsが合成済み。無ければ往路と共有）。
        cost_list = context.legs[1].cost_list if len(context.legs) > 1 else context.legs[0].cost_list

        penalized: set[int] = set(data.outbound_edge_indices)
        for edge_index in data.outbound_edge_indices:
            edge = graph.edges[lazy_graph.edge_ids[edge_index]]
            reverse_index = lazy_graph.edge_index_by_node_pair.get(
                (lazy_graph.node_id_to_index[edge.to_node_id], lazy_graph.node_id_to_index[edge.from_node_id])
            )
            if reverse_index is not None:
                penalized.add(reverse_index)

        trace_started = time.monotonic()
        original = {index: cost_list[index] for index in penalized}
        try:
            for index in penalized:
                cost_list[index] = original[index] * RETRACE_PENALTY_MULTIPLIER
            return_path = shortest_path_node_ids_lazy(
                lazy_graph, data.node_id, context.origin_node, cost_list.__getitem__, _origin_estimate_fn(context),
            )
        finally:
            for index, value in original.items():
                cost_list[index] = value
        trace_wall_ms = round((time.monotonic() - trace_started) * 1000)
        if return_path is None:
            raise RoutingError(f"turnaround bearing={turnaround.bearing}: no return path found")

        # indexは1回求めればID列もそこから導けるため、return_path上のNodeペア走査は
        # 1回だけで済ませる。
        return_edge_index_list = path_to_edge_indices_lazy(lazy_graph, return_path)
        if not return_edge_index_list:
            raise RoutingError(f"turnaround bearing={turnaround.bearing}: return path has no edges")
        return_edge_ids = [lazy_graph.edge_ids[index] for index in return_edge_index_list]
        return_edge_indices = np.array(return_edge_index_list, dtype=np.int64)
        retrace = overlap_ratio(return_edge_indices, np.fromiter(penalized, dtype=np.int64), context.statics.edge_length_m)
        outbound_edge_ids = [lazy_graph.edge_ids[index] for index in data.outbound_edge_indices]
        edge_ids = [*outbound_edge_ids, *return_edge_ids]
        leg_of_edge = [0] * len(outbound_edge_ids) + [1] * len(return_edge_ids)
        distance_km = round(sum(graph.edges[edge_id].distance_m for edge_id in edge_ids) / 1000, 2)
        logger.debug(
            "trace_loop_from_turnaround bearing=%d outbound_km=%.1f loop_km=%.1f retrace_ratio=%.2f wall_ms=%d",
            turnaround.bearing, data.outbound_length_m / 1000, distance_km, retrace, trace_wall_ms,
        )
        return TracedLoop(bearing=turnaround.bearing, distance_km=distance_km, data=edge_ids, leg_of_edge=leg_of_edge)

    def is_loop_too_similar(
        self, context: _RoadGraphContext, candidate: TracedLoop, accepted: list[TracedLoop]
    ) -> bool:
        """`candidate`が`accepted`のいずれかと、周回全体（往路＋復路）で
        `LOOP_MAX_OVERLAP_RATIO`を超えて重複するか。進行方向を無視して
        比較するため、「同じ周回の逆回り」（往路と復路が入れ替わっただけ）や「往路は違うが
        復路が同じ裏道へ収束する」周回のどちらも同じ判定で弾ける。`TracedLoop.data`は
        `edge_ids`（往路＋復路、`trace_loop_from_turnaround`/`trace_loop`参照）。
        """
        candidate_lengths = _loop_edge_lengths_by_physical_segment(context.graph, candidate.data)
        if not candidate_lengths:
            return False
        total = sum(candidate_lengths.values())
        if total <= 0:
            return False
        for other in accepted:
            other_keys = _loop_edge_lengths_by_physical_segment(context.graph, other.data)
            shared = sum(length for key, length in candidate_lengths.items() if key in other_keys)
            ratio = shared / total
            if ratio > LOOP_MAX_OVERLAP_RATIO:
                logger.debug(
                    "loop dedup rejected bearing=%d overlap_ratio=%.2f vs accepted bearing=%s",
                    candidate.bearing, ratio, other.bearing,
                )
                return True
        return False

    async def evaluate_loops(
        self, context: _RoadGraphContext, traced: list[TracedLoop], start_time: datetime
    ) -> list[RouteCandidate]:
        # 実ジオメトリ・標高は経路確定後・距離フィルタ通過後の候補だけに絞って取得する
        # （モジュールdocstring参照。棄却済み候補へのDB/GSI問い合わせを避ける）。
        #
        # prepareが読み込んだcontext.graph（LeanRoadGraph）の
        # Edgeはgeometryが空プレースホルダのため、区間表示・標高取得等（後段の
        # _build_candidate）に使う実ジオメトリを合格候補の経路ぶんだけ、全候補まとめて
        # 1回のDBクエリで取得し直す（候補ごとには問い合わせない）。
        # `or context.graph.edges[edge_id]`は、prepare時点からこのDBクエリまでの間に
        # 別リクエストが同じbboxを再構築（save_graphのUPSERT/DELETE、
        # is_split_up_to_dateの項参照）してedge_idが入れ替わるレースが理論上ありうる
        # ため、その場合にKeyErrorで落とさずcontext.graph側の値（geometryは空
        # プレースホルダのまま）へ倒す防御的フォールバック。
        all_edge_ids = list(dict.fromkeys(edge_id for t in traced for edge_id in t.data))
        hydrated = await self._graph_service.get_edges_with_geometry(all_edge_ids)
        edges_by_candidate: list[list[EdgeLike]] = [
            [hydrated.get(edge_id) or context.graph.edges[edge_id] for edge_id in t.data] for t in traced
        ]
        return list(
            await asyncio.gather(
                *(
                    self._build_best_candidate(context, t, edges_in_path, start_time)
                    for t, edges_in_path in zip(traced, edges_by_candidate)
                )
            )
        )

    async def _build_best_candidate(
        self, context: _RoadGraphContext, traced: TracedLoop, edges_in_path: list[EdgeLike], start_time: datetime
    ) -> RouteCandidate:
        """1候補ぶんの周回を組み立てる。同じ物理的な周回形状の
        逆回り（復路を先に、往路を後に辿る）も、追加のDB/外部API呼び出しゼロで合成できる
        場合は合成し、distance_weighted_difficulty（segmentsの距離加重平均、
        RouteGenerator._with_overall_difficultyと同じ指標）が小さい方を採用する
        （両方向を別候補として追加するのではなく、候補ごとに良い方だけを残す設計。
        周回の逆走は生成方法に依存せず常に物理的に意味があり、勾配・風で評点が変わる。
        経路中に一方通行Edgeが1つでもあれば逆回りは物理的に成立しないため、その場合は
        順方向のみを返す）。ユーザーが指定した経由地ルート
        （traced.bearing is None）は訪問順序そのものが要件のため、逆回り合成は行わない。
        """
        elevation_attributes = await self._fetch_elevation_attributes(context, edges_in_path)
        leg_of_edge = traced.leg_of_edge if traced.leg_of_edge is not None else [0] * len(edges_in_path)
        forward_candidate = self._build_candidate(
            context, traced, edges_in_path, elevation_attributes, start_time, leg_of_edge
        )

        if traced.bearing is None:
            return forward_candidate

        reverse_edges = _reverse_traced_edges(edges_in_path, context.lazy_graph, context.graph)
        if reverse_edges is None:
            return forward_candidate
        reverse_elevation_attributes = _reverse_elevation_attributes(
            edges_in_path, reverse_edges, elevation_attributes
        )
        # 逆回りは復路だった区間を先に走るため、レグの割当ても逆順（先に走る側が往路配列）。
        reverse_candidate = self._build_candidate(
            context, traced, reverse_edges, reverse_elevation_attributes, start_time, list(reversed(leg_of_edge))
        )
        return _pick_better_candidate(forward_candidate, reverse_candidate)

    async def _fetch_elevation_attributes(
        self, context: _RoadGraphContext, edges_in_path: list[EdgeLike]
    ) -> dict[str, ElevationAttribute]:
        # context.materials（EdgeMaterialBundle、探索フェーズで既にDBから取得・
        # タイル単位でプロセス内キャッシュ済み）が対象Edgeの標高を既に持っていれば、
        # それをそのまま使いElevationAttributeServiceへの問い合わせ自体を避ける
        # （evaluate_loopsはasyncio.gatherで候補を並行評価するが、
        # ElevationAttributeService._repository_lockが内部で直列化するため、
        # 候補ごとに個別問い合わせすると候補数[max_routes件]倍のレイテンシが積み上がる）。
        # 事前計算バッチが未実行のEdge（context.materials側がNone）だけ、
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

        # ElevationAttributeService.get_attributes_for_graphは
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
        leg_of_edge: list[int],
    ) -> RouteCandidate:
        # edges_in_path・elevation_attributesを引数化しているため、逆回り候補
        # （_reverse_traced_edges・_reverse_elevation_attributes、追加I/Oなしで導出済み）も
        # 同じ組み立てロジックへ通せる。distance_km・bearingは順方向・逆回りで共通
        # （同じ物理経路の総距離・同じ方位の候補のため）traced（順方向のTracedLoop）から
        # そのまま使う。
        geometry = _concat_edge_geometries(edges_in_path)
        elevation_stats = _aggregate_elevation(edges_in_path, elevation_attributes)
        segments = self._build_segment_details(edges_in_path, elevation_attributes, context, start_time, leg_of_edge)
        # APIレスポンスとして返すsegmentsは約500m単位に集約する（Edge単位のままだと
        # 30km級で150〜230件になりペイロード・フロント描画コストが嵩む）。
        segments = aggregate_segments_into_bins(segments)

        return RouteCandidate(
            **candidate_identity(traced.bearing),
            distance_km=traced.distance_km,
            geometry=geometry,
            segments=segments,
            **elevation_stats,
        )

    def _build_segment_details(
        self,
        edges: list[EdgeLike],
        elevation_attributes: dict,
        context: _RoadGraphContext,
        start_time: datetime,
        leg_of_edge: list[int],
    ) -> list[RouteSegmentDetail]:
        """区間ごとの表示値を組み立てる。軸別スコア・合成difficulty・寄与度・材料値は、
        そのEdgeが探索されたレグ（`leg_of_edge`）の合成済み配列（`context.legs`、
        `context.full_edge_row`で行を引く）からそのまま読み、探索コストと表示を一致させる
        （二重計算を持たない）。到達予想時刻は経路上の累積距離を仮定巡航速度で割って求める。
        """
        segments = []
        cumulative_km = 0.0
        active_material_ids = _active_material_ids(context.composer._weights, context.composer._lens_axis_id)

        for edge, leg_index in zip(edges, leg_of_edge):
            leg = context.legs[leg_index]
            distance_km = edge.distance_m / 1000
            elevation_attr = elevation_attributes.get(edge.edge_id)

            gradient_percent = elevation_attr.average_grade if elevation_attr else None
            # 静的材料（`leg.material_arrays`が持つ動的材料とは別経路）の生値。現状
            # material_valuesが必要とする静的材料はgradient_percentのみ（符号付き材料の
            # 軸はこれ1つ、`_active_material_ids`のdocstring参照）。この区間ループは
            # 元々gradient_percentをEdgeごとに計算済みのため、新たな計算コストは無い。
            static_material_values = (
                {"gradient_percent": round(gradient_percent, 1)}
                if "gradient_percent" in active_material_ids and gradient_percent is not None
                else {}
            )

            row = context.full_edge_row.get(edge.edge_id)
            if row is None:
                # 通常は到達しない（full_edge_rowはbbox全体の生Edge集合を覆うため）。
                # 経路上のEdgeが何らかの理由で行を持たない防御的フォールバック。
                axis_scores: dict[str, float] = {}
                axis_contributions: dict[str, float] = {}
                composite_difficulty_value: float | None = None
                material_values: dict[str, float] = static_material_values
            else:
                axis_scores = {
                    axis_id: float(arr[row])
                    for axis_id, arr in leg.axis_arrays.items()
                    if not math.isnan(arr[row])
                }
                axis_contributions = {
                    axis_id: float(arr[row])
                    for axis_id, arr in leg.contribution_arrays.items()
                    if not math.isnan(arr[row])
                }
                difficulty_value = leg.difficulty_array[row]
                composite_difficulty_value = None if math.isnan(difficulty_value) else float(difficulty_value)
                material_values = {
                    **static_material_values,
                    **{
                        material_id: value
                        for material_id in active_material_ids
                        if (value := _material_value_at(leg, material_id, row)) is not None
                    },
                }

            elapsed_hours = cumulative_km / self._assumed_speed_kmh
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
                    # axis_scoresは既にaxis_id→difficultyの汎用dict（データ無しの軸はキー自体を
                    # 持たない）のため、そのままRouteSegmentDetail.axis_difficultiesへ渡せる。
                    axis_difficulties=axis_scores,
                    axis_contributions=axis_contributions,
                    material_values=material_values,
                    difficulty=composite_difficulty_value,
                )
            )
            cumulative_km += distance_km

        return segments


def _material_value_at(leg: LegCostArrays, material_id: str, row: int) -> float | None:
    """レグの合成に使った材料配列から1行を読む（材料データ無し・欠損はNone）。"""
    array = leg.material_arrays.get(material_id)
    if array is None:
        return None
    value = float(array[row])
    return None if math.isnan(value) else value


def _active_material_ids(weights: Mapping[str, float], lens_axis_id: str | None = None) -> set[str]:
    """重み>0の公開軸が参照する材料idの集合（`AXIS_DEFINITIONS`の`materials`プロパティ
    から導出、軸id自体への参照は除く。軸名のハードコード無し）に加え、`lens_axis_id`が
    符号付き材料の軸（`map_value_kind`が`"signed_material"`）を指す場合はその材料も
    重みに関わらず含める。地図のレンズ（ルート線色分け）は符号付き材料の生値を
    `axis_difficulties`ではなくこの`material_values`経由で塗るため（`frontend/src/
    components/Map/routeStyleModes.ts: routeColorableModeFromAxis`のsigned_material分岐、
    符号[登り/下り]の情報を保つため難易度0-100へは変換しない）、重み0の軸をレンズに
    選んでも表示が欠けないようにする。"""
    from app.domain.material_catalog import is_known_material

    material_ids: set[str] = set()
    for axis_id, weight in weights.items():
        if weight <= 0:
            continue
        definition = AXIS_DEFINITIONS.get(axis_id)
        if definition is None:
            continue
        material_ids.update(m for m in definition.materials if is_known_material(m))
    if lens_axis_id is not None:
        lens_definition = AXIS_DEFINITIONS.get(lens_axis_id)
        if lens_definition is not None and map_value_kind(lens_definition) == "signed_material":
            material_ids.update(m for m in lens_definition.materials if is_known_material(m))
    return material_ids


async def _get_or_build_lazy_graph(
    tile_set: frozenset[tuple[int, int, int]] | None, graph: RoadGraphLike
) -> tuple[LazyRoadGraph, bool]:
    """探索用グラフ（`LazyRoadGraph`）をタイル集合キーでキャッシュする
    （`infrastructure/search_graph_cache.py`）。

    `tile_set`は`GraphService.get_search_materials_for_bbox`が「bboxを覆う全z12タイルの
    材料キャッシュをそのまま結合したグラフ」を返した場合のみ設定される
    （`_build_search_graph`のtile_set docstring参照）。Noneの場合はキャッシュを経由せず
    毎回構築する。

    本関数は`build_lazy_road_graph`へ`edge_cost_by_id`を渡さず、決定的フォールバック
    （edge_idの昇順で先頭を採用）で並行Edge（同一Node間の複数Edge）を解消する——コストは
    リクエストごと（軸重み・風・0次フィルタ）に変わるため、タイル集合だけで決まる
    このキャッシュとは「cost最小を採用」方式は両立しない。2つの並行Edgeのうち一方だけが
    このリクエストの0次フィルタで除外される稀なケースでは、cost最小方式なら自動的に
    許可される側が選ばれるが、この方式では選ばれない場合がある（`(u,v)`ペア自体が
    到達不能になる）。実データでの並行Edge自体が稀なうえ、その中でさらに片方だけ
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


async def _ensure_lazy_graph_consistent(
    tile_set: frozenset[tuple[int, int, int]] | None, lazy_graph: LazyRoadGraph, graph: RoadGraphLike
) -> LazyRoadGraph:
    """`lazy_graph.edge_ids`が`graph.edges`の部分集合であることを検証し、崩れていれば
    タイル集合キャッシュ3種を破棄して`lazy_graph`ごと`graph`から作り直す
    （`prepare`・`preview_segment`共通の`_build_search_graph`が呼ぶ）。

    `_lazy_graph_cache`と`_search_statics_cache`はLRU上限に達すると独立に最古のエントリを
    追い出すため、再split（`save_graph`のedge_id再割当）を挟むと「`lazy_graph`はキャッシュ
    ヒットで古いまま」という状態が起こりうる。放置すると、直後の
    `cost_by_edge_id[edge_id] for edge_id in lazy_graph.edge_ids`（`_build_search_graph`）や
    `domain/routing.py: build_search_graph_statics`が同種のKeyErrorを起こす。この関数は
    `domain/routing.py: find_missing_lazy_graph_edge_id`（CSR構築を伴わない軽量版チェック）
    で不整合の有無だけを先に確認し、無ければ`lazy_graph`をそのまま返す。呼び出し側は
    以降このメソッドの戻り値を使うこと（引数の`lazy_graph`を使い続けると同じKeyError相当を
    再現する）。
    """
    missing = await asyncio.to_thread(find_missing_lazy_graph_edge_id, lazy_graph, graph)
    if missing is None:
        return lazy_graph
    if tile_set is not None:
        logger.warning("search_graph_cache stale_lazy_graph tile_set_size=%d rebuilding", len(tile_set))
        search_graph_cache.invalidate_tile_set(tile_set)
    lazy_graph = await asyncio.to_thread(build_lazy_road_graph, graph)
    if tile_set is not None:
        search_graph_cache.set_lazy_graph(tile_set, lazy_graph)
    return lazy_graph


async def _get_or_build_search_statics(
    tile_set: frozenset[tuple[int, int, int]] | None, lazy_graph: LazyRoadGraph, graph: RoadGraphLike
) -> tuple[SearchGraphStatics, bool]:
    """一対全最短経路木用のCSR構造＋Edge実距離配列（`domain/routing.py:
    SearchGraphStatics`）を、`_get_or_build_lazy_graph`と同じタイル集合キーで
    キャッシュする。`tile_set`がNoneならキャッシュを経由せず毎回構築する。
    戻り値の2つ目はキャッシュヒットしたかどうか（ログ用）。

    `lazy_graph`は呼び出し元（`prepare`）が`_ensure_lazy_graph_consistent`で検証済みの
    ものである前提のため、`LazyGraphEdgeMismatchError`の検知・再構築ロジックは持たない
    （整合性検証は一対全木を使わない`preview_segment`も含む`_build_search_graph`側の
    責務として分離している）。
    """
    if tile_set is not None:
        cached = search_graph_cache.get_search_statics(tile_set)
        if cached is not None:
            return cached, True
    statics = await asyncio.to_thread(build_search_graph_statics, lazy_graph, graph)
    if tile_set is not None:
        search_graph_cache.set_search_statics(tile_set, statics)
    return statics, False


async def _get_or_build_reverse_search_statics(
    tile_set: frozenset[tuple[int, int, int]] | None, lazy_graph: LazyRoadGraph, graph: RoadGraphLike
) -> tuple[SearchGraphStatics, bool]:
    """目的地からの後ろ向き木用の転置CSR（`domain/routing.py: SearchGraphStatics`、
    `reverse=True`）を、`_get_or_build_search_statics`と同じタイル集合キーでキャッシュする。
    目的地ルートのvia-node方式選定（`select_via_nodes`）だけが呼ぶ——
    周回生成・`preview_segment`は後ろ向き木を使わないため構築しない。`lazy_graph`は
    呼び出し元（`prepare`）が`_ensure_lazy_graph_consistent`で検証済みのものである前提
    （`_get_or_build_search_statics`と同じ契約、再構築ロジックは持たない）。
    """
    if tile_set is not None:
        cached = search_graph_cache.get_reverse_search_statics(tile_set)
        if cached is not None:
            return cached, True
    statics = await asyncio.to_thread(build_search_graph_statics, lazy_graph, graph, reverse=True)
    if tile_set is not None:
        search_graph_cache.set_reverse_search_statics(tile_set, statics)
    return statics, False


def _median_detour_ratio(context: _RoadGraphContext, node_indices: np.ndarray, length_m: np.ndarray) -> float:
    """起点から`node_indices`（`lazy_graph`のNode index）への道なり距離`length_m`と直線距離の
    比の中央値を返す。対象が無い・直線距離0のみならNaN。"""
    if len(node_indices) == 0:
        return float("nan")
    origin_coordinates = context.graph.nodes[context.origin_node]
    straight_km = haversine_distance_km_array(
        context.node_lat[node_indices], context.node_lon[node_indices], origin_coordinates
    )
    with np.errstate(invalid="ignore", divide="ignore"):
        ratios = np.where(straight_km > 0, np.asarray(length_m, dtype=float) / 1000 / straight_km, np.nan)
    if np.all(np.isnan(ratios)):
        return float("nan")
    return float(np.nanmedian(ratios))


def _learn_detour_ratio(context: _RoadGraphContext, measured: float) -> float:
    """実測の迂回率が有効なら探索範囲（タイル集合）の学習値として保存し、そのまま返す。
    無効（NaN・非正）なら合成に使っている現在の値（学習値または既定値）を返す。"""
    if not math.isfinite(measured) or measured <= 0:
        return context.composer.detour_ratio
    if context.tile_set is not None:
        search_graph_cache.set_detour_ratio(context.tile_set, measured)
    return measured


def _estimate_distances_m(
    graph: RoadGraphLike,
    node_lat: np.ndarray,
    node_lon: np.ndarray,
    target_node_id: str,
) -> list[float]:
    """グラフ上の全Node（`node_lat`/`node_lon`と同じ行順）から`target_node_id`への
    直線距離（m）をnumpyで1回だけベクトル計算する。`_build_estimate_cost_fn`
    と`_origin_estimate_fn`が共有する。

    Edge Costは常に`cost >= distance_m`を満たす（`docs/decisions/t12-routing-scale.md`
    原則1「不変条件1」、ペナルティ倍率は常に1以上）ため、直線距離は実際のコストを
    過大評価しない下界＝admissibleなヒューリスティックになる。
    """
    target_node = graph.nodes[target_node_id]
    return (haversine_distance_km_array(node_lat, node_lon, target_node) * 1000).tolist()


def _origin_estimate_fn(context: _RoadGraphContext) -> Callable[[int], float]:
    """復路探索（目的地＝起点）のA*ヒューリスティック。起点は1リクエストで固定のため
    初回だけ`_estimate_distances_m`で計算し、以降の候補はcontextに保持した配列を共有する。
    """
    if context.origin_estimate is None:
        context.origin_estimate = _estimate_distances_m(
            context.graph, context.node_lat, context.node_lon, context.origin_node
        )
    return context.origin_estimate.__getitem__


def _build_estimate_cost_fn(
    graph: RoadGraphLike,
    node_lat: np.ndarray,
    node_lon: np.ndarray,
    target_node_id: str,
) -> Callable[[int], float]:
    """`shortest_path_node_ids_lazy`へ渡すA*のestimate_cost_fnを、
    目的地ノード`target_node_id`への直線距離（m）として組み立てる。

    レグごとに目的地が変わるたび`_estimate_distances_m`を呼び直し、
    `list.__getitem__`をそのまま返す——Pythonの関数フレームを作らないA*の設計
    （`LazyRoadGraph`のdocstring参照）と揃える。`node_lat`/`node_lon`は
    `lazy_graph.index_to_node_id`と同じ行順（`_build_search_graph`がリクエストにつき
    1回だけ構築、レグごとの再構築はしない）。
    """
    return _estimate_distances_m(graph, node_lat, node_lon, target_node_id).__getitem__


def _order_by_bearing_spread(
    remaining: Sequence[int],
    selected: list[int],
    bearing_by_node: Mapping[int, float],
    closeness_by_node: Mapping[int, float],
) -> list[int]:
    """同点グループの残り候補（Node index）を、採用済み候補との方位角距離の最小値が大きい順
    （同値はリング中心近さ`closeness`昇順、さらにNode index昇順で決定的）に並べて返す。
    採用済みが無ければリング中心近さ順。`select_diverse_by_overlap`の`prefer`として
    1件採用するたびに呼ばれるため、計算量はO(残り候補数×採用済み件数)を採用回数ぶん。
    """
    if not selected:
        return sorted(remaining, key=lambda node_index: (closeness_by_node[node_index], node_index))
    bearings = np.array([bearing_by_node[node_index] for node_index in remaining], dtype=float)
    placed = np.array([bearing_by_node[node_index] for node_index in selected], dtype=float)
    diffs = np.abs(bearings[:, None] - placed[None, :])
    diffs = np.minimum(diffs, 360.0 - diffs)
    min_dist = diffs.min(axis=1)
    closeness = np.array([closeness_by_node[node_index] for node_index in remaining], dtype=float)
    order = np.lexsort((np.asarray(remaining, dtype=np.int64), closeness, -min_dist))
    return [remaining[i] for i in order]


def _loop_edge_lengths_by_physical_segment(
    graph: RoadGraphLike, edge_ids: list[str]
) -> dict[frozenset[str], float]:
    """周回1件ぶんのEdge列（`TracedLoop.data`）を、進行方向を無視した物理区間キー
    （`{from_node_id, to_node_id}`のfrozenset）→距離(m)の辞書へ変換する
    （`is_loop_too_similar`が使う）。同じ物理区間を指すfwd/bwd Edge（逆方向Edge）を同一キーへ
    正規化することで、「同じ周回の逆回り」の比較を可能にする。存在しないedge_idは無視する
    （`evaluate_loops`の防御的フォールバックと同じ理由で理論上ありうるレース対策）。
    """
    result: dict[frozenset[str], float] = {}
    for edge_id in edge_ids:
        edge = graph.edges.get(edge_id)
        if edge is None:
            continue
        key = frozenset({edge.from_node_id, edge.to_node_id})
        result[key] = edge.distance_m
    return result


def _reverse_traced_edges(
    edges_in_path: list[EdgeLike], lazy_graph: LazyRoadGraph, graph: RoadGraphLike
) -> list[EdgeLike] | None:
    """順方向の経路`edges_in_path`（起点→...→起点）を逆順に辿った場合の、対応する
    逆方向Edge列を構築する。経路中に一方通行（逆方向Edgeが存在しない）
    区間が1つでもあれば物理的に逆走不可能なため`None`を返す。

    経路上のEdgeだけに対する遅延引きとして`lazy_graph.edge_index_by_node_pair`
    （並行Edge解消後、`build_lazy_road_graph`が既に構築済み）で`(to_index, from_index)`→
    edge_indexを引き、`lazy_graph.edge_ids`でedge_idへ変換、`graph`（`context.graph`、
    フル解像度のトポロジ）から実際のEdgeを引く。並行Edge（同じNode対を複数のEdgeが
    結ぶ稀なケース）は`build_lazy_road_graph`の決定的な解消規則に従う。
    `geometry`だけは逆方向Edge自体（lean、空プレースホルダ）からではなく、
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
    代数的に導出する。標高は地形の物理量で進行方向に依存しないため、
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
    順方向で既に取得済みの値から代数的に導出する（`_reverse_elevation_attribute`
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
    """候補のsegmentsから、距離加重平均の合成difficultyを求める（逆回り候補との
    比較指標）。`RouteGenerator._with_overall_difficulty`と同じ計算だが、
    あちらは候補ごとに採否が確定した最終候補へ`overall_difficulty`を付与する後処理
    （エンジン非依存の戦略層）なのに対し、ここは同じ候補の順方向・逆回りのどちらを
    残すかをエンジン内部で決めるための指標であり、計算するタイミング・対象が異なる
    （同じ指標を2箇所で使うが、役割が違うため無理に共通化しない）。
    """
    if not candidate.segments:
        return None
    return distance_weighted_difficulty([(s.difficulty, s.distance_km) for s in candidate.segments])


def _pick_better_candidate(forward: RouteCandidate, reverse: RouteCandidate) -> RouteCandidate:
    """順方向・逆回り候補のうち、`_route_composite_difficulty`が小さい（走りやすい）方を
    採用する。逆回り側が算出不能（segments欠損等）なら順方向を採用する
    （比較不能を「逆回りの方が良い」とは解釈しない、安全側）。
    """
    forward_difficulty = _route_composite_difficulty(forward)
    reverse_difficulty = _route_composite_difficulty(reverse)
    if reverse_difficulty is not None and (forward_difficulty is None or reverse_difficulty < forward_difficulty):
        return reverse
    return forward


def _bbox_around_point(center: Coordinates, radius_km: float) -> BoundingBox:
    """centerを中心とした半径radius_kmの円を覆う矩形bboxを求める（周回ルートの探索範囲。
    折返し点候補がどの方位に選ばれても1回のRoad Graph取得でカバーできるよう、起点1つに
    対して1回だけ計算する）。"""
    lat_margin_deg = radius_km / KM_PER_DEGREE_LATITUDE
    lon_margin_deg = radius_km / (KM_PER_DEGREE_LATITUDE * max(math.cos(math.radians(center.latitude)), 1e-6))
    return BoundingBox(
        min_latitude=center.latitude - lat_margin_deg,
        max_latitude=center.latitude + lat_margin_deg,
        min_longitude=center.longitude - lon_margin_deg,
        max_longitude=center.longitude + lon_margin_deg,
    )


def _bbox_covering_points(points: list[Coordinates], margin_km: float) -> BoundingBox:
    """複数地点すべてを覆う外接矩形に、margin_kmの余裕を足したbboxを求める
    （`preview_segment`の起点・終点2点用）。`_bbox_around_point`と異なり中心・半径ではなく
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

    # 最終集約（sum/min/max・空ならNone・小数1桁丸め）はelevation_aggregation.pyへ集約する。
    return {
        "elevation_gain_m": sum_or_none(gains),
        "min_elevation_m": min_or_none(elevations),
        "max_elevation_m": max_or_none(elevations),
    }


