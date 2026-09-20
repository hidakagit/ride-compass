"""Road Graph + 辺基準グラフ探索（A*/一対全Dijkstra、lazy評価）の自前ルーティングエンジン。

`RouteGenerator`（services/route_generator.py）の`LoopRoutingEngine`契約を実装する。
Road Graph・Evaluation Engine・Route Engine（domain/routing.py）を使って経由地点間の
経路を自前で計算する。ルート生成の唯一のエンジン実装。

設計の骨子（詳細はdocs/modules/backend/routing-engine.md参照）:
- **Road Graphの取得は1リクエストにつき1回だけ**: 候補ごとに個別のbboxで問い合わせず、
  起点を中心とした単一の円（折返し点候補をすべて覆う半径、`RouteGenerator.
  TURNAROUND_RADIUS_RATIO`）でRoad Graphを`prepare`で1回だけ取得し、全候補で共有する。
- **周回候補は8方位固定ではなく、公開軸の重み駆動のフロンティア方式で生成する**。
  `select_loop_turnarounds`が起点からの一対全最短経路木（`domain/routing.py:
  build_turn_expanded_tree`、numbaでJITした自前の探索）で「往路の実距離が目標の半分付近」のNode群
  （リング）を求め、往路の距離加重平均difficultyの昇順に折返し点候補を選ぶ
  （似た往路は`select_diverse_by_overlap`で間引く）。`trace_loop_from_turnaround`が
  往路（木の経路そのもの、再探索しない）に、往路Edge＋逆方向Edgeのコストを一時的に
  `RETRACE_PENALTY_MULTIPLIER`倍へ差し替えて探索した復路（A*）を継いで周回にする。
  経由地・目的地指定ルート（`trace_loop`）は指定地点列を順にA*で結ぶ。
- **標高（勾配）は探索フェーズで読んだ材料に入っている**。経路確定後の表示・
  スコアリングも同じ材料から取り、外部へ取りに行く経路は持たない（標高タイルが
  覆っていない区間はgradient軸だけ「データ無し」になり、他の軸で評価は継続する）。
- 風は**到達時刻ごとの予報**を使う（時刻ビン別のコスト配列を持ち、探索が到達時刻を
  ラベルとして運ぶ）。時刻別の予報が無いときだけ1本のスナップショットへ落ちる。
- **Edgeコストは「タイル単位の静的スコア行列＋リクエスト時ベクトル計算」で求める**:
  タイル読込時（`GraphService._get_or_build_tile_materials`）に「Edge×公開軸」の
  静的スコア行列（`domain/evaluation.py: StaticEdgeScoreMatrix`、風など動的軸の列は
  NaN）を1回だけ構築してキャッシュし、リクエスト時にその行列＋動的軸（風、
  `evaluate_dynamic_axis_arrays`）＋重みベクトルからコスト配列を**bbox全体ぶん1回だけ**
  numpyで合成する。探索（`domain/routing.py: turn_expanded_shortest_path`・
  `build_turn_expanded_tree`）へはこのコスト配列をnumpy配列のまま渡す——探索中に
  PythonのコールバックもEdgeごとのオブジェクトも作らない。同一Node間の並行Edgeは、`build_lazy_road_graph`が
  edge_idの昇順で先頭を採用して解消する——`LazyRoadGraph`はタイル集合だけで決まる
  キャッシュのため、リクエストごとに変わるコストを解消の基準にできない。この割り切りにより、
  並行Edgeのうち一方だけが0次フィルタで除外される稀なケースでは、許可される側ではなく
  edge_idの小さい側が選ばれ、そのNode対が到達不能になりうる（判断理由の詳細は
  docs/tasks/T537.md参照）。
- `_build_segment_details`（区間表示）も探索と同じコスト配列・スコア行列から
  `axis_difficulties`を引く（探索と表示の二重計算を避ける）。
- 候補ごとの復路探索（`trace_loop_from_turnaround`）・経由地ルートの`trace_loop`は
  直列実行する（`trace_loop_from_turnaround`は共有コスト配列を一時的に書き換えるため、
  並列化とは両立しない）。
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
from collections.abc import Container, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np

from app.domain.time_zone import JST
from app.domain.cycling_speed import (
    ROLLING_RESISTANCE_MATERIAL_ID,
    RiderProfile,
    crr_for_surface,
    travel_seconds,
)
from app.domain.traffic import stop_count_material_ids, POI_COUNT_KINDS, highway_rank, stop_seconds
from app.domain.tuning import tuning_value
from app.domain.attributes import EdgeMaterialArrays, ElevationAttribute
from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    REQUEST_DYNAMIC_MATERIAL_IDS,
    dynamic_axis_topological_order,
)
from app.domain.axis_display import axis_material_shares
from app.domain.difficulty import distance_weighted_difficulty
from app.domain.dynamic_way_values import map_value_kind
from app.domain.errors import RoutingError
from app.domain.dynamic_materials import DynamicAxisRequestContext, evaluate_dynamic_axis_arrays
from app.domain.evaluation import (
    StaticEdgeScoreMatrix,
    axis_contributions_at_row,
    axis_weighted_sums,
    compose_costs_from_axis_matrix,
)
from app.domain.hard_filters import compute_hard_filter_excluded, compute_routable_node_ids
from app.domain.route_preference import RoutePreference
from app.domain.geo import (
    KM_PER_DEGREE_LATITUDE,
    bearing_between,
    bearing_between_array,
    haversine_distance_km,
    haversine_distance_km_array,
)
from app.domain.graph import EdgeLike, LeanEdge, RoadGraphLike
from app.domain.material_catalog import is_known_material
from app.domain.region import BoundingBox
from app.domain.route import (
    Coordinates,
    RouteCandidate,
    RouteSegment,
    RouteSegmentDetail,
    aggregate_segments_into_bins,
    merge_material_category_shares,
)
from app.domain.twilight import is_night
from app.domain.routing import (
    LazyGraphEdgeMismatchError,
    LazyRoadGraph,
    NodeSpatialIndex,
    SearchGraphStatics,
    build_lazy_road_graph,
    build_node_spatial_index,
    build_search_graph_statics,
    current_turn_cost,
    NodeJunction,
    TurnCostSpec,
    TurnExpandedStructure,
    TurnExpandedTree,
    build_turn_expanded_structure,
    build_turn_expanded_tree,
    combine_forward_backward_at_nodes,
    edge_bearings,
    find_missing_lazy_graph_edge_id,
    find_nearest_node_indexed,
    overlap_ratio,
    pareto_layer_index,
    select_diverse_by_overlap,
    turn_expanded_path_edge_indices,
    turn_expanded_path_from_state,
    turn_expanded_path_from_state_to_source,
    turn_expanded_shortest_path,
)
from app.domain.weather import WeatherConditions
from app.domain.wind import (
    ASSUMED_SPEED_KMH,
    ROUTE_DETOUR_RATIO,
    WindForecastSeries,
    estimate_passage_hours,
    kmh_to_ms,
    wind_components,
)
from app.infrastructure import search_graph_cache
from app.services.elevation_aggregation import max_or_none, min_or_none, sum_or_none
from app.services.graph_service import GraphService
from app.services.route_generator import LoopTurnaround, TracedLoop, candidate_identity
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
# 一対全探索のコスト上限に掛ける余裕。Edge単位の丸めの積み上がりで上限ぎりぎりのNodeを
# 取りこぼさないため。
COST_LIMIT_SLACK = 1.01
# レグの中を時刻で区切るビンの幅（h）と本数の上限。**風の予報が1時間刻みのため、幅もそれに
# 揃え、ビンはその開始時刻で評価する**——`WindForecastSeries.sample`が最も近い正時を引くため、
# 幅を細かくしても隣のビンが同じ予報時刻を引くだけで、合成の回数だけが増える。目安として、
# 目標30kmの周回はレグ0.75時間で1本（時刻ビンを張らないのと同じ費用）、100km級で3本になる。
TIME_BIN_HOURS = 1.0
MAX_TIME_BINS = 4
# 候補選定（`pareto_layer_index`）で「実質同じ」とみなす粒度。距離は往路実距離200m
# （周回全長では約400m差、体感で選び分ける単位より細かい）、難易度は他の集計値と同じ
# 小数1桁。細かすぎると互いに非劣解な候補が全件残ってフィルタとして働かず、粗すぎると
# 候補が減りすぎる。
PARETO_DISTANCE_QUANTUM_M = 200.0
PARETO_DIFFICULTY_QUANTUM = 0.1

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

#: 目的地が起点から到達できないとき、「到達できる最寄りNode」へ寄せてよい上限（km）。
#: 補正の狙いは、タップした先が本線から孤立した小塊だった場合にすぐ近くの本線へ移すこと
#: なので、それより遠くへ動かすと利用者が指した覚えのない場所を通るルートになる
#: （補正後の座標は`corrected_destination`として返すが、動いたことが分かっても
#: 指した場所とは別物である事実は変わらない）。
MAX_DESTINATION_CORRECTION_KM = 1.0


@dataclass
class LegCostArrays:
    """1レグぶんの合成済みコスト配列一式。`cost_lazy`は`lazy_graph.edge_ids`順（探索が使う
    行順）、それ以外は`score_matrix.edge_ids`（`full_edge_row`）順の表示用配列。レグごとに違うのは風（各Edgeの通過予定時刻の風）だけで、静的軸の列は共有する。"""

    label: str
    cost_lazy: np.ndarray
    difficulty_array: np.ndarray
    axis_arrays: dict[str, np.ndarray]
    # 区間ごとの「データのある軸の重みの合計」。軸別寄与度（表示用）はこれと`axis_arrays`から
    # `axis_contributions_at`が読むときに1行だけ求める——全区間ぶん作っても、読むのは
    # 経路上の数百区間だけのため。
    weight_sums: np.ndarray
    weights: dict[str, float]
    # 折れ点を通す前の生値（`full_edge_row`順）。静的スコア行列の列をそのまま指すため
    # レグ間で同じ配列を共有する（風のようにレグごとに変わる値は持たない）。
    axis_raw_arrays: dict[str, np.ndarray]
    # `full_edge_row`順の材料id→配列。動的材料（`evaluate_dynamic_material_arrays`が返す
    # 全材料が対象、全行NaNの材料はキーを持たない）と、内訳表示用の静的材料
    # （`route_facing_material_ids`、静的スコア行列の列）の両方を持つ。区間表示・
    # `material_values`の集計が、探索コストの合成と同じ入力から求めた値を読むために保持する。
    material_arrays: dict[str, np.ndarray]
    # `full_edge_row`順のcategorical材料id→値の配列（静的スコア行列の列をそのまま指すため
    # レグ間で共有する）。区間表示の内訳が値ごとの延長割合を出すために保持する。
    categorical_material_arrays: dict[str, np.ndarray]
    # 区間ごとの所要時間（秒）。`travel_seconds_lazy`は`cost_lazy`と同じ行順で、探索の
    # コストの下地になる。ターンの待ちは遷移ごとに決まるためどちらにも含まない。
    travel_seconds_full: np.ndarray
    travel_seconds_lazy: np.ndarray
    # レグの中を経過時間で区切ったビンごとの配列（`(ビン, Edge)`、`cost_lazy`と同じ列順）。
    # 到達時刻をラベルとして持ち回れる探索はこちらを使い、**風をレグ内の実際の経過時間で
    # 引き直す**。時変化しないレグは1本（`cost_lazy`と同じ内容）。
    cost_bins_lazy: np.ndarray
    travel_bins_lazy: np.ndarray
    # ビン1本あたりの秒。ビンが1本のときは無限大（常にビン0を引く）。
    bin_seconds: float

    def axis_contributions_at(self, row: int) -> dict[str, float]:
        """その区間の軸別寄与度（`full_edge_row`順の行番号で引く）。"""
        return axis_contributions_at_row(self.axis_arrays, self.weights, self.weight_sums, row)


def _representative_bin(bin_count: int, duration_hours: float | None) -> int:
    """表示と、時刻ラベルを持てない探索が使う代表ビンの添字。レグの中間地点が入るビン。"""
    if bin_count <= 1 or duration_hours is None:
        return 0
    return min(bin_count - 1, int((duration_hours / 2) / TIME_BIN_HOURS))


class _LegCostComposer:
    """bbox全体ぶんのコスト配列を、レグ（基準点・時刻オフセット・向き）ごとに合成する。
    静的スコア行列・重み・0次フィルタ・lazy_graph行順の対応表はリクエスト内で共通のため
    1回だけ用意し、`compose`はレグごとに変わる風の列だけを引き直して合成する。
    **風の時別系列が無いときだけ**、出発時点のスナップショットで合成した1本（`snapshot`）を
    全レグで共有する（追加コストゼロ）。系列があれば軸の重みが0でも時刻で引き直す
    ——理由は`__init__`の`self.time_varying`のコメント参照。"""

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
        self._axis_raw_arrays = {
            axis_id: score_matrix.axis_raw_values[:, i]
            for i, axis_id in enumerate(score_matrix.raw_axis_ids)
        }
        # 内訳として見せる静的材料の値（`route_facing_material_ids`の列をそのまま指す）。
        self._static_material_arrays = {
            material_id: score_matrix.material_values[:, i]
            for i, material_id in enumerate(score_matrix.material_ids)
        }
        # 同じくcategorical材料（値が文字列のため別の列で運ぶ、
        # `route_facing_categorical_material_ids`）。
        self._categorical_material_arrays = {
            material_id: score_matrix.categorical_material_values[:, i]
            for i, material_id in enumerate(score_matrix.categorical_material_ids)
        }
        self._static_axis_scores = score_matrix.axis_arrays()
        # 時刻で変わる（風に依存する）公開軸と、それ以外。ビンごとの合成では後者の重み付き和を
        # 使い回す——合成の時間は軸数にほぼ比例するため、毎回全軸を足し直すと本数ぶん効く。
        dynamic_axes = set(dynamic_axis_topological_order(AXIS_DEFINITIONS))
        self._time_varying_axis_ids = [a for a in score_matrix.axis_ids if a in dynamic_axes]
        self._fixed_axis_ids = [a for a in score_matrix.axis_ids if a not in dynamic_axes]
        self._weights = weights
        self._penalty_strength = penalty_strength
        self._hard_filter_excluded = hard_filter_excluded
        self._weather = weather
        self._wind_series = wind_series
        self.start = start
        self.speed_kmh = speed_kmh
        self._lazy_row_index = lazy_row_index
        # lazy行順の配列をfull_edge_row順へ戻す並べ替え表（`_lazy_row_index`の逆）。
        # `_lazy_row_index`は全単射ではない——同一Node間の並行Edgeは`build_lazy_road_graph`が
        # 1本だけ採るため、探索用グラフに載らないEdgeがある。載らない行は-1にする。
        self._full_row_index = np.full(len(score_matrix.distance_m), -1, dtype=np.int64)
        self._full_row_index[lazy_row_index] = np.arange(len(lazy_row_index))
        self._lazy_hard_filter_excluded: np.ndarray | None = None
        self._lens_axis_id = lens_axis_id
        # 通過予定時刻の推定に使う迂回率（道なり距離÷直線距離）。探索範囲ごとの学習値が
        # あればそれ、無ければ`ROUTE_DETOUR_RATIO`。`compose`の引数で個別に上書きできる。
        self.detour_ratio = detour_ratio
        # 風の時別系列があれば常に時変化合成する。風は軸（主観的な避けたさ）である前に
        # **走行モデルの入力**（向かい風で実際に遅くなる）のため、軸の重みが0でも時刻で
        # 引き直す必要がある。
        self.time_varying = wind_series is not None
        self._cache: dict[tuple, LegCostArrays] = {}
        self._fixed_axis_sums_cache: tuple[np.ndarray, np.ndarray] | None = None

    def _travel_time_seconds(
        self, material_arrays: dict[str, np.ndarray], headwind_ms: np.ndarray, crosswind_ms: np.ndarray
    ) -> np.ndarray:
        """区間ごとの所要時間（秒）を`full_edge_row`順で返す。

        走行モデル（`domain/cycling_speed.py`）で勾配・風の成分・路面・巡航速度から求めた
        走行時間に、その区間にある停止要因の待ち（`domain/traffic.py: stop_seconds`）を
        足したもの。
        ターンの待ちは遷移ごとに決まるためここには含まない（探索側が足す）。
        0次フィルタで除外された区間は無限大にする（探索から見た通行可否をコストの下地だけで
        表すため）。
        """
        profile = RiderProfile(cruise_speed_kmh=self.speed_kmh)
        distance_m = self._score_matrix.distance_m
        # 勾配は静的スコア行列が生配列として常に持つ（0次フィルタの勾配しきい値と同じ列）。
        # `material_arrays`は「内訳として見せる材料」だけのため、勾配軸が分解されていない
        # 構成では欠ける。
        grade = np.nan_to_num(self._score_matrix.gradient_percent) / 100.0
        crr = crr_for_surface(material_arrays.get(ROLLING_RESISTANCE_MATERIAL_ID), len(distance_m))
        travel = travel_seconds(distance_m, profile, grade, headwind_ms, crosswind_ms, crr)
        stops = np.zeros(len(distance_m))
        # 材料idの綴りは`stop_count_material_ids()`が単一の情報源。ここで組み立て直すと、
        # 向こうで綴りを変えたときにここだけがNoneを引き、全区間の停止の待ちが無言で0秒になる。
        for kind, material_id in zip(POI_COUNT_KINDS, stop_count_material_ids()):
            per_km = material_arrays.get(material_id)
            if per_km is not None:
                stops += np.nan_to_num(per_km) * (distance_m / 1000.0) * stop_seconds(kind)
        return np.where(self._hard_filter_excluded, np.inf, travel + stops)

    @property
    def lazy_hard_filter_excluded(self) -> np.ndarray:
        """0次フィルタ除外フラグを`lazy_graph.edge_ids`の行順（探索へ渡すコスト配列と
        同じ行順）で返す。

        `compose`が作る`cost_lazy`は除外Edgeを`inf`にした状態でこの行順へ並べ替えてあり、
        探索から見た通行可否はそのコスト配列だけが表しているため、コストを使わず距離だけで
        木を張る経路は同じ除外を自分で適用する必要がある。
        """
        if self._lazy_hard_filter_excluded is None:
            self._lazy_hard_filter_excluded = self._hard_filter_excluded[self._lazy_row_index]
        return self._lazy_hard_filter_excluded

    def compose(
        self,
        label: str,
        anchor: Coordinates | None,
        offset_hours: float,
        direction: int,
        duration_hours: float | None = None,
        passage_hours: np.ndarray | None = None,
    ) -> LegCostArrays:
        """`direction=+1`なら起点から離れていく・`-1`なら向かっていくレグとして、
        そのレグを走る時刻の風でコスト配列を合成する。

        `anchor`は**在るかどうかだけ**を見る（起点が決まっていないリクエストでは風を
        時刻で変えられないため、1本のスナップショットへ落ちる）。座標の値は使わない
        ——風の予報は起点1地点ぶんを`WeatherService`が既に引いており、ここでは方位だけが
        Edgeごとに効く。

        `duration_hours`（このレグに何時間かかる見込みか）を渡すと、レグの中を
        `TIME_BIN_HOURS`ごとのビンへ分けた配列（`cost_bins_lazy`）も併せて作る。到達時刻を
        ラベルとして持ち回れる探索はビンを引き、**経過時間の推定ではなく実際の経過時間**で
        風を評価する。`cost_lazy`等の代表値（表示と、時刻ラベルを持てない後ろ向き木が使う）は
        レグの中央のビン。

        `duration_hours`を渡さない場合はビン1本＝レグ全体を開始時刻で評価する。時刻ラベルを
        持てない探索（目的地から遡る木）だけは、前向き木が出した実際の到達時間を
        `passage_hours`（`full_edge_row`順）として渡す。
        """
        bin_count = self._bin_count(duration_hours)
        edge_count = len(self._score_matrix.distance_m)
        # `direction=-1`の`offset_hours`はレグの終了時刻のため、開始時刻へ直す。
        leg_start = offset_hours if direction > 0 else offset_hours - (duration_hours or 0.0)
        if not self.time_varying or anchor is None:
            key: tuple = ("snapshot",)
            bin_count = 1
        elif passage_hours is not None:
            key = ("passage", round(offset_hours, 3), direction, float(np.nansum(passage_hours)))
            bin_count = 1
        else:
            # 代表ビンもキーに入れる——同じ開始時刻・同じビン数でも、見込み所要時間が違えば
            # 代表（表示が読むビン）は変わりうる。
            key = (round(leg_start, 3), bin_count, _representative_bin(bin_count, duration_hours))
        cached = self._cache.get(key)
        if cached is not None:
            # 同じ内容を使い回すのは正しい（風が時刻で変わらないレグは1本で足りる）が、
            # 黙って返すと合成のログがレグの数だけ出ず、運用側から「復路の合成が走って
            # いない」と見える。使い回した事実を残す。
            logger.info("compose_leg_costs leg=%s mode=reused key=%s", label, key[0])
            return cached

        started = time.monotonic()
        if not self.time_varying or anchor is None:
            bins = [self._compose_at(None)]
        elif passage_hours is not None:
            bins = [self._compose_at(passage_hours)]
        else:
            bins = [
                self._compose_at(np.full(edge_count, leg_start + k * TIME_BIN_HOURS))
                for k in range(bin_count)
            ]

        # 代表はレグの中間地点が入るビン（ビンはレグの見込み時間より長く張られることがあり、
        # 単純な中央の添字だと終盤のビンへ寄る）。
        representative = bins[_representative_bin(len(bins), duration_hours)]
        leg = LegCostArrays(
            label=label,
            cost_lazy=representative.cost_lazy,
            difficulty_array=representative.difficulty_array,
            axis_arrays=representative.axis_arrays,
            weight_sums=representative.weight_sums,
            weights=self._weights,
            axis_raw_arrays=self._axis_raw_arrays,
            material_arrays=representative.material_arrays,
            categorical_material_arrays=self._categorical_material_arrays,
            travel_seconds_full=representative.travel_seconds_full,
            travel_seconds_lazy=representative.travel_seconds_lazy,
            cost_bins_lazy=np.vstack([b.cost_lazy for b in bins]),
            travel_bins_lazy=np.vstack([b.travel_seconds_lazy for b in bins]),
            bin_seconds=TIME_BIN_HOURS * 3600.0 if len(bins) > 1 else np.inf,
        )
        self._cache[key] = leg
        logger.info(
            "compose_leg_costs leg=%s mode=%s bins=%d compose_ms=%d",
            label, "time_varying" if self.time_varying and anchor is not None else "snapshot",
            len(bins), round((time.monotonic() - started) * 1000),
        )
        return leg

    @property
    def _fixed_axis_sums(self) -> tuple[np.ndarray, np.ndarray]:
        """時刻で変わらない軸の`(重み付きスコアの和, 重みの和)`。

        使うのは探索へ渡すだけのビン（代表以外の時刻ビン）で、レグが1本のビンに収まる
        リクエストでは一度も要らない。求めるのに軸数ぶんの走査が要るため、要求されるまで
        遅らせる。
        """
        if self._fixed_axis_sums_cache is None:
            self._fixed_axis_sums_cache = axis_weighted_sums(
                {axis_id: self._static_axis_scores[axis_id] for axis_id in self._fixed_axis_ids},
                self._weights, len(self._score_matrix.distance_m),
            )
        return self._fixed_axis_sums_cache

    def to_full_row_order(self, lazy_values: np.ndarray) -> np.ndarray:
        """lazy行順（探索が使う並び）の配列を`full_edge_row`順へ戻す。

        探索用グラフに載らないEdge（並行Edgeのうち採られなかった方）はNaNになる。
        """
        values = np.asarray(lazy_values, dtype=float)
        result = np.full(len(self._full_row_index), np.nan)
        mapped = self._full_row_index >= 0
        result[mapped] = values[self._full_row_index[mapped]]
        return result

    def _bin_count(self, duration_hours: float | None) -> int:
        """レグを何本の時刻ビンへ分けるか。見込み所要時間が無ければ1本。

        上限（`MAX_TIME_BINS`）を置くのは、ビン1本ごとにbbox全体のコスト合成が1回走るため
        ——長距離ほど風の変化を細かく追えるが、そのぶん生成が遅くなる。
        """
        if duration_hours is None or not self.time_varying:
            return 1
        return int(min(MAX_TIME_BINS, max(1, math.ceil(duration_hours / TIME_BIN_HOURS))))

    def _compose_at(self, passage: np.ndarray | None) -> LegCostArrays:
        """指定した通過時刻（`None`は出発時点のスナップショット）で1本ぶん合成する。"""
        dynamic_context = DynamicAxisRequestContext(
            bearing_deg=self._score_matrix.bearing_deg, weather=self._weather,
            travel_speed_ms=kmh_to_ms(self.speed_kmh),
            wind_series=self._wind_series, start=self.start, passage_hours=passage,
        )
        resolved = evaluate_dynamic_axis_arrays(self._static_axis_scores, dynamic_context)
        wind_inputs = dynamic_context.wind_inputs()
        if wind_inputs is None:
            headwind = crosswind = np.zeros(len(self._score_matrix.bearing_deg))
        else:
            headwind, crosswind = wind_components(*wind_inputs, self._score_matrix.bearing_deg)
        material_arrays = {
            # 静的材料は静的スコア行列の列をそのまま指すためレグ間で共有する
            # （動的材料と違いレグごとに変わらない）。
            **self._static_material_arrays,
            **{
                material_id: resolved[material_id]
                for material_id in REQUEST_DYNAMIC_MATERIAL_IDS
                if material_id in resolved and not np.all(np.isnan(resolved[material_id]))
            },
        }
        travel = self._travel_time_seconds(material_arrays, headwind, crosswind)
        # evaluate_dynamic_axis_arraysは内部軸も含めうるため、公開軸のみへ絞って合成する。
        # 合成へ渡すのは時刻で変わる軸だけにし、それ以外は先に求めた重み付き和を使い回す
        # （合成の時間は軸数にほぼ比例する）。表示が読む`axis_arrays`は全軸を持たせる。
        published = {axis_id: resolved[axis_id] for axis_id in self._score_matrix.axis_ids}
        time_varying = {axis_id: resolved[axis_id] for axis_id in self._time_varying_axis_ids}
        composed = compose_costs_from_axis_matrix(
            self._score_matrix.distance_m, time_varying, self._weights, self._penalty_strength,
            base=travel, static_sums=self._fixed_axis_sums, with_contributions=False,
        )
        cost_array, difficulty_array = composed.cost, composed.difficulty
        cost_array = np.where(self._hard_filter_excluded, np.inf, cost_array)
        lazy_cost = cost_array[self._lazy_row_index]
        lazy_travel = travel[self._lazy_row_index]
        return LegCostArrays(
            label="",
            cost_lazy=lazy_cost,
            difficulty_array=difficulty_array,
            axis_arrays=published,
            weight_sums=composed.weight_sums,
            weights=self._weights,
            axis_raw_arrays=self._axis_raw_arrays,
            material_arrays=material_arrays,
            categorical_material_arrays=self._categorical_material_arrays,
            travel_seconds_full=travel,
            travel_seconds_lazy=lazy_travel,
            cost_bins_lazy=lazy_cost.reshape(1, -1),
            travel_bins_lazy=lazy_travel.reshape(1, -1),
            bin_seconds=np.inf,
        )


@dataclass
class _RoadGraphContext:
    """prepareで構築し、全方位のtrace_loop/evaluate_loopsで共有するリクエスト単位の状態。"""

    graph: RoadGraphLike
    # 材料の列（`domain/attributes.py: EdgeMaterialArrays`）。Edge単位の材料アクセスは探索コスト算出の
    # ホットパスからは外れているが、`_build_segment_details`の表示用フィールド
    # （surface等）取得には引き続き使う。
    materials: EdgeMaterialArrays
    accident_years_covered: int
    weather: WeatherConditions | None
    origin_node: str
    # 1リクエスト内で繰り返し呼ばれるfind_nearest_node相当（prepareの起点・trace_loopの
    # 各経由地と目的地・preview_segmentの両端）を都度線形探索せず使い回すための索引
    # （domain/routing.py参照）。
    node_index: NodeSpatialIndex
    # 探索用グラフ（Node/Edge payloadは整数index、domain/routing.py: LazyRoadGraph参照）。
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
    # domain/routing.py: SearchGraphStatics参照）。探索へはcost_lazyをそのまま渡す。
    statics: SearchGraphStatics
    # 状態＝有向Edge・辺＝ターンの遷移構造（`statics.csr`から導く。起点にもコストにも
    # 依存しないためリクエスト内で共有する）。
    turn_structure: TurnExpandedStructure
    # origin_nodeのlazy_graph上のNode index（一対全木の起点）。
    origin_index: int
    # `select_via_nodes`が目的地からの後ろ向き木（転置CSR）をタイル集合キーで
    # キャッシュ・取得するために保持する（`_SearchGraph.tile_set`と同じ値、`SearchGraphStatics`
    # と違い後ろ向き木は目的地ルートでしか使わないため`prepare`では構築しない）。
    tile_set: frozenset[tuple[int, int, int]] | None
    # 復路探索（折返し点→起点）のA*ヒューリスティック配列。目的地が常に起点の
    # ため、リクエストで1回だけ計算し全候補で共有する（初回の復路探索時に遅延構築）。
    origin_estimate: np.ndarray | None = None
    # select_via_nodesが目的地を最寄りのアクセス可能なNodeへ補正した場合の
    # 実際の座標（補正が無ければNone）。RouteGenerator.last_no_candidates_reasonと同じ
    # side channel——Protocolの戻り値型（list[TracedLoop]）を変えずにRouteGenerator側へ
    # 伝える。
    destination_correction: Coordinates | None = None
    # 候補0件になった原因がどちら側にあるか（"origin"＝起点から1Nodeも到達できない、
    # "destination"＝到達はできるが目的地の近くに届くNodeが無い）。
    # destination_correctionと同じside channelで、利用者へ出す文面を分けるために使う。
    no_candidates_side: str | None = None


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
    materials: EdgeMaterialArrays
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
    # `materials`（`EdgeMaterialArrays`）への依存を持たない。
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
        weather_service: WeatherService,
        route_preference: RoutePreference,
        penalty_strength: float = 1.0,
        max_average_grade_percent: float | None = None,
        hard_filters: frozenset[str] | None = None,
        assumed_speed_kmh: float = ASSUMED_SPEED_KMH,
        lens_axis_id: str | None = None,
        turn_cost: TurnCostSpec | None = None,
    ):
        self._graph_service = graph_service
        # 地図のレンズが表示を要求している軸id（無ければNone）。重み0の軸でも区間表示の
        # ために風の時変化合成を行う判定にだけ使う（探索コストには影響しない）。
        self._lens_axis_id = lens_axis_id
        # 仮定巡航速度（km/h、リクエスト単位で上書き可）。各Edgeの通過予定時刻・区間の
        # 到達予想時刻・所要時間の算出に使う。
        self._assumed_speed_kmh = assumed_speed_kmh
        self._weather_service = weather_service
        self._route_preference = route_preference
        # コスト式`所要時間 × (1 + P × difficulty/100)`のP＝「主観 vs 時間」の換算レート。
        # 既定1.0は「difficulty 100の道は体感で所要時間2倍」の意味。
        self._penalty_strength = penalty_strength
        # T12 ADR原則5: 0次ハードフィルタの勾配しきい値（%、既定None＝
        # 除外しない）。domain/evaluation.py: is_edge_allowed参照。
        self._max_average_grade_percent = max_average_grade_percent
        # 0次ハードフィルタ名（no_bicycle/motorway/trunk）の個別ON/OFF上書き
        # （既定None＝DEFAULT_HARD_FILTERS＝全フィルタ有効）。
        self._hard_filters = hard_filters
        # 交差点でのターンの費用（秒）。較正中はリクエストで上書きして試せる。
        self._turn_cost = turn_cost if turn_cost is not None else current_turn_cost()

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
        にし、探索本体へは合成済みのnumpy配列をそのまま渡すだけにする）。
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
        # way_tags・elevation_attribute・is_designatedは、材料の列へ
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
            score_matrix.hard_filter_flags,
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
        lazy_graph = await _ensure_lazy_graph_consistent(tile_set, lazy_graph, graph, full_edge_row)
        graph_ms = round((time.monotonic() - graph_started) * 1000)

        # lazy_graph.edge_ids（並行Edge解消後）の各行が`score_matrix`のどの行かの対応表。
        # レグごとのcost_lazyはこの索引でnumpyのfancy indexingにより並べ替える。
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
        `compute_routable_node_ids`は`EdgeMaterialArrays`へ一切
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

        turn_started = time.monotonic()
        turn_structure, turn_cached = await _get_or_build_turn_structure(
            search.tile_set, statics, search.lazy_graph, search.graph, self._turn_cost
        )
        logger.info(
            "prepare turn_structure build states=%d transitions=%d turn_ms=%d turn_structure_cached=%s",
            turn_structure.state_count, len(turn_structure.target_state),
            round((time.monotonic() - turn_started) * 1000), turn_cached,
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
            turn_structure=turn_structure,
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

        # 探索はターンの費用を含む辺基準（状態＝有向区間）で行うため、一対全木と同じCSR構造が
        # 要る（2点間探索だけの経路でも`SearchGraphStatics`を構築する）。
        statics, _ = await _get_or_build_search_statics(search.tile_set, search.lazy_graph, search.graph)
        turn_structure, _ = await _get_or_build_turn_structure(
            search.tile_set, statics, search.lazy_graph, search.graph, self._turn_cost
        )
        edges = await asyncio.to_thread(
            turn_expanded_shortest_path,
            turn_structure, search.outbound.cost_lazy,
            _heuristic_seconds(
                _estimate_distances_m(search.graph, search.node_lat, search.node_lon, destination_node)
            ),
            _origin_states(statics, search.lazy_graph.node_id_to_index[origin_node]),
            search.lazy_graph.node_id_to_index[destination_node],
        )
        if edges is None:
            return None
        edge_ids = [search.lazy_graph.edge_ids[index] for index in edges]
        if not edge_ids:
            return None

        # prepareと同じレイジー取得（prepareがlean=Trueで読み込んだ
        # search.graphのEdgeはgeometryが空プレースホルダのため、この経路ぶんだけ取得し直す）。
        hydrated = await self._graph_service.get_edges_with_geometry(edge_ids)
        edges_in_path: list[EdgeLike] = [hydrated.get(edge_id) or search.graph.edges[edge_id] for edge_id in edge_ids]

        distance_km = round(sum(edge.distance_m for edge in edges_in_path) / 1000, 2)
        geometry, _ = _concat_edge_geometries(edges_in_path)
        # ここだけは走行モデル（勾配・風・路面で速度が変わる）を通さず、仮定巡航速度の
        # ままで概算する。区間の疎通確認が用途で、探索を経ずEdge列の長さしか持たないため。
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
        # （lazy_graph.edge_ids順）のため、探索へはコスト配列をそのまま渡す。
        # A*ヒューリスティックは
        # レグごとに目的地（to_node）が変わるため、レグごとにnumpyで1回だけベクトル計算し直す。
        # 探索は`asyncio.to_thread`で包まず直列に行う（モジュールdocstring参照）。
        # レグごとに、レグ起点を基準点・それまでの累積実距離を時刻オフセットとして
        # コスト配列を合成する（レグ0は起点から離れる往路レグそのもの）。
        def _trace_segments() -> list[list[int]] | None:
            segment_paths: list[list[int]] = []
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
                segment_path = turn_expanded_shortest_path(
                    context.turn_structure, leg.cost_bins_lazy,
                    _heuristic_seconds(
                        _estimate_distances_m(context.graph, context.node_lat, context.node_lon, to_node)
                    ),
                    _origin_states(context.statics, context.lazy_graph.node_id_to_index[from_node]),
                    context.lazy_graph.node_id_to_index[to_node],
                    leg.travel_bins_lazy, leg.bin_seconds,
                )
                if segment_path is None:
                    return None
                segment_paths.append(segment_path)
                cumulative_m += sum(
                    context.graph.edges[context.lazy_graph.edge_ids[index]].distance_m
                    for index in segment_path
                )
            return segment_paths

        trace_started = time.monotonic()
        segment_paths = _trace_segments()
        trace_wall_ms = round((time.monotonic() - trace_started) * 1000)
        logger.info("trace_loop direction=%s wall_ms=%d", bearing, trace_wall_ms)
        if segment_paths is None:
            raise RoutingError(f"direction {bearing}: no path found between waypoints")

        edge_ids = [context.lazy_graph.edge_ids[index] for segment in segment_paths for index in segment]
        if not edge_ids:
            raise RoutingError(f"direction {bearing}: resulting path has no edges")
        distance_km = round(sum(context.graph.edges[edge_id].distance_m for edge_id in edge_ids) / 1000, 2)
        leg_of_edge = [
            leg_index for leg_index, segment_path in enumerate(segment_paths) for _ in segment_path
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

        1. 起点からの一対全最短経路木（`domain/routing.py: build_turn_expanded_tree`、
           軸重み付きコスト）を1回だけ求める。探索はコスト上限
           （リング上限の距離を最低速度で秒へ直し×(1+P)。リング内のNodeを取りこぼさない
           上界）で打ち切る。
        2. 木に沿った往路の**実距離**が`[(目標-許容)/LOOP_TO_OUTBOUND_RATIO_MIN,
           (目標+許容)/LOOP_TO_OUTBOUND_RATIO_MAX]`に入るNodeを「リング」として抽出する
           （最短実距離ではなく軸コスト最適経路の実距離で定義する——重みを極端に振った
           設定ほど往路が遠回りするため、最短実距離基準だと往路だけで目標の半分を超え
           距離フィルタで全滅する。比の範囲は復路が往路より長くなりやすい実測に基づく）。
        3. 往路の時間加重平均difficulty `(cost/seconds - 1)/P`（コスト式の逆算、
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
        statics = context.statics
        # 往路レグを、見込み所要時間（目標距離の半分÷巡航速度）ぶんの時刻ビンで組み直す。
        # 木は出発からの経過時間を持ち回れるため、風を推定ではなく実際の経過時間で引ける。
        outbound = context.composer.compose(
            "outbound", context.origin, 0.0, +1,
            duration_hours=distance_km / 2 / context.composer.speed_kmh,
        )
        context.legs = [outbound]
        # コストは秒（体感の所要時間）のため、上限もリング上限の距離を秒へ直して決める。
        # 走行モデルが出しうる最も遅い速度（押して歩く）で割ることで、リング内のNodeを
        # 取りこぼさない上界になる（`cost <= 所要時間 × (1+P)`かつ
        # `所要時間 <= 距離 ÷ 最低速度`）。
        cost_limit = (
            ring_upper_m / kmh_to_ms(tuning_value("speed.walking_kmh"))
            * (1.0 + max(self._penalty_strength, 0.0)) * COST_LIMIT_SLACK
        )

        tree_started = time.monotonic()
        tree = await asyncio.to_thread(
            build_turn_expanded_tree,
            context.turn_structure, outbound.cost_bins_lazy, statics.edge_length_m,
            _origin_states(statics, context.origin_index), statics.csr.node_count,
            cost_limit=cost_limit, edge_seconds=outbound.travel_bins_lazy,
            bin_seconds=outbound.bin_seconds,
        )
        tree_ms = round((time.monotonic() - tree_started) * 1000)

        length = tree.node_length_m
        in_ring = (length >= ring_lower_m) & (length <= ring_upper_m)
        in_ring[context.origin_index] = False
        ring = np.flatnonzero(in_ring)
        if len(ring) == 0:
            logger.info(
                "select_turnarounds ring_nodes=0 reached=%d ring_km=[%.1f,%.1f] tree_ms=%d",
                int(np.isfinite(tree.node_cost).sum()), ring_lower_m / 1000, ring_upper_m / 1000, tree_ms,
            )
            return []

        ring_length = length[ring]
        # 迂回率（道なり距離÷直線距離）の実測中央値を学習値として保存する。周回の合成自体は
        # 使わない（レグはビンの開始時刻で評価する）が、直線距離を走行時間へ直す係数として
        # 目的地ルートの到着予定時刻が読む。
        detour_ratio_median = _median_detour_ratio(context, ring, ring_length)
        _learn_detour_ratio(context, detour_ratio_median)
        # 復路レグ: 起点へ向かうレグとして、周回の総所要時間（目標距離÷仮定速度）を起点への
        # 到着予定時刻に置いて合成する（距離フィルタが目標±許容を強制するため定数扱いできる）。
        inbound = context.composer.compose(
            "inbound", context.origin, distance_km / context.composer.speed_kmh, -1,
            duration_hours=distance_km / 2 / context.composer.speed_kmh,
        )
        context.legs = [context.legs[0], inbound]
        if self._penalty_strength > 0:
            # コスト式`所要時間 × (1 + P × difficulty/100)`の逆算。
            with np.errstate(invalid="ignore", divide="ignore"):
                difficulty = (tree.node_cost[ring] / tree.node_seconds[ring] - 1.0) / self._penalty_strength * 100.0
            difficulty = np.where(np.isfinite(difficulty), difficulty, 0.0)
        else:
            # P=0はコスト＝所要時間（難易度を一切考慮しない）なので全候補同点。
            difficulty = np.zeros(len(ring))
        difficulty_key = np.round(difficulty, 1)
        closeness_key = np.abs(ring_length - ring_center_m)
        # 「リング中心からのずれ」「往路difficulty」の2指標で非優越ソートし、パレート層の
        # 順に並べる。難易度だけで並べると、難易度が距離加重「平均」であるために遠回りして
        # 難所を避けた候補が常に上位を占め、「目標距離ちょうどだが難所を通る」候補が一覧に
        # 現れない（ユーザーには選ぶ余地が無くなる）。第1層だけでは候補が2〜3件にしか
        # ならないため、プールが埋まるまで層を重ねる（pareto_layer_index参照）。
        # 第1指標に往路実距離そのものではなくリング中心からのずれを使うのは、周回では
        # 距離が「短いほど良い」ではなく「目標に近いほど良い」ためで、これにより目標より
        # 短すぎる往路（起点のすぐ近くで折り返す周回）も長すぎる往路も対称に扱われる。
        pareto_layer = pareto_layer_index(
            closeness_key, difficulty,
            quantum_a=PARETO_DISTANCE_QUANTUM_M, quantum_b=PARETO_DIFFICULTY_QUANTUM,
            max_items=pool_size,
        )
        # 層に入らなかった候補（-1）は従来どおりの難易度順で最後尾へ回す。
        layer_key = np.where(pareto_layer >= 0, pareto_layer, np.iinfo(np.int32).max)
        order = np.lexsort((ring, closeness_key, difficulty_key, layer_key))[:MAX_RING_CANDIDATES_EXAMINED]
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
        # 同点グループの区切りはdifficulty_keyだけでなくパレート非劣解かどうかも見る
        # ——非劣解群の末尾と劣解群の先頭が同じdifficulty_keyを持つとき、両者を同点として
        # 混ぜると劣解が非劣解より先に試されうる（orderの主キーである非劣解優先が崩れる）。
        group_key = np.stack([layer_key[order].astype(np.int64), difficulty_key[order]])
        tie_groups = [
            group.tolist()
            for group in np.split(ranked, np.flatnonzero(np.any(np.diff(group_key, axis=1) != 0, axis=0)) + 1)
        ]

        def prefer(remaining: Sequence[int], selected: list[int]) -> list[int]:
            return _order_by_bearing_spread(remaining, selected, bearing_by_node, closeness_by_node)

        lazy_graph = context.lazy_graph
        outbound_cache: dict[int, list[int] | None] = {}

        def outbound_edges(node_index: int) -> list[int] | None:
            if node_index not in outbound_cache:
                outbound_cache[node_index] = turn_expanded_path_edge_indices(tree, node_index)
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
        後ろ向き木（遷移の向きを反転した辺基準の木）を各1回求めれば、
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
        # 往路レグを、起点→目的地の見込み所要時間ぶんの時刻ビンで組み直す。
        outbound = context.composer.compose(
            "outbound", context.origin, 0.0, +1,
            duration_hours=(
                context.composer.detour_ratio * haversine_distance_km(context.origin, destination)
                / context.composer.speed_kmh
            ),
        )
        context.legs = [outbound]
        forward_tree = await asyncio.to_thread(
            build_turn_expanded_tree,
            context.turn_structure, outbound.cost_bins_lazy, context.statics.edge_length_m,
            _origin_states(context.statics, context.origin_index), context.statics.csr.node_count,
            edge_seconds=outbound.travel_bins_lazy, bin_seconds=outbound.bin_seconds,
        )

        if not np.isfinite(forward_tree.node_cost[destination_index]):
            corrected_node = find_nearest_node_indexed(
                context.node_index, destination,
                predicate=lambda node_id: np.isfinite(
                    forward_tree.node_cost[lazy_graph.node_id_to_index[node_id]]
                ),
                max_distance_km=MAX_DESTINATION_CORRECTION_KM,
            )
            if corrected_node is None:
                # Noneは「この距離の中にアクセス可能なNodeが無い」。到達Node数が0なら壊れて
                # いるのは目的地ではなく起点側（またはコスト配列）であり、そちらを名指ししないと
                # 調査が空振りする。
                reached_nodes = int(np.count_nonzero(np.isfinite(forward_tree.node_cost)))
                if reached_nodes == 0:
                    finite_cost_ratio = float(np.mean(np.isfinite(outbound.cost_bins_lazy)))
                    context.no_candidates_side = "origin"
                    logger.warning(
                        "select_via_nodes origin reaches no node origin_node=%s out_edges=%d "
                        "finite_cost_ratio=%.3f nodes=%d",
                        context.origin_node,
                        int(_origin_states(context.statics, context.origin_index).size),
                        finite_cost_ratio,
                        int(forward_tree.node_cost.size),
                    )
                else:
                    context.no_candidates_side = "destination"
                    logger.warning(
                        "select_via_nodes no accessible node near destination destination_node=%s "
                        "reached_nodes=%d/%d",
                        destination_node, reached_nodes, int(forward_tree.node_cost.size),
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

        # 迂回率は前向き木（起点から1km以上先の到達Node）の実測中央値を使い、学習値として保存する。
        reached = np.flatnonzero(np.isfinite(forward_tree.node_cost) & (forward_tree.node_length_m >= 1000.0))
        detour_ratio_median = _median_detour_ratio(context, reached, forward_tree.node_length_m[reached])
        inbound_detour_ratio = _learn_detour_ratio(context, detour_ratio_median)
        # 後ろ向き木は目的地へ向かうレグ: 目的地を基準点に、到着予定時刻を
        # 「起点〜目的地の直線距離×迂回率÷仮定速度」に置いて合成する。
        arrival_hours = (
            inbound_detour_ratio * haversine_distance_km(context.origin, destination) / context.composer.speed_kmh
        )
        # 後ろ向き木は時刻ラベルを持てない（目的地から遡るため各状態の到達時刻が決まらない）。
        # 代わりに、前向き木が出した「起点からその区間へ実際に到達する時間」を通過時刻として
        # 渡す——直線距離からの推定より実態に近く、候補は伸び率の上限内に収まるため
        # ずれもその範囲に収まる。前向き木が届かない区間だけ直線距離の推定へ落とす。
        forward_seconds_lazy = forward_tree.node_seconds[context.turn_structure.edge_from]
        forward_hours = context.composer.to_full_row_order(forward_seconds_lazy) / 3600.0
        fallback_hours = estimate_passage_hours(
            context.composer._score_matrix.mid_lat, context.composer._score_matrix.mid_lon,
            destination, arrival_hours, -1, context.composer.speed_kmh,
            detour_ratio=inbound_detour_ratio,
        )
        inbound = context.composer.compose(
            "inbound", destination, arrival_hours, -1,
            passage_hours=np.where(np.isfinite(forward_hours), forward_hours, fallback_hours),
        )
        context.legs = [context.legs[0], inbound]
        backward_tree = await asyncio.to_thread(
            build_turn_expanded_tree,
            context.turn_structure, inbound.cost_lazy, context.statics.edge_length_m,
            _destination_states(context.turn_structure, destination_index),
            context.statics.csr.node_count, reverse=True, edge_seconds=inbound.travel_seconds_lazy,
        )
        tree_ms = round((time.monotonic() - tree_started) * 1000)

        # Nodeで単に前向き＋後ろ向きを足すと、そのNodeで曲がる費用が抜ける。
        junction_started = time.monotonic()
        junction = combine_forward_backward_at_nodes(
            context.turn_structure, forward_tree, backward_tree, context.statics.csr.node_count
        )
        junction_ms = round((time.monotonic() - junction_started) * 1000)
        # 目的地そのものを経由Nodeとする経路（＝経由せず直行する経路）も候補に含める。
        # junctionは「入る区間×出る区間」の対で作るため、そこで終わる経路は現れない。
        _add_terminal_candidate(junction, forward_tree, destination_index)
        combined_cost = junction.cost
        combined_length = junction.length_m
        combined_seconds = junction.seconds
        reachable = np.isfinite(combined_cost)
        if not np.any(reachable):
            # 改善計画docs/logging.md「候補0件はWARNINGへ昇格し、原因の内訳を同じ行に含める」:
            # 前向き木・後ろ向き木のどちらがどれだけ到達できているかを内訳として出す
            # （前向きのみ0なら起点側、後ろ向きのみ0なら目的地側の孤立を疑える）。
            logger.warning(
                "select_via_nodes reachable=0 forward_reached=%d backward_reached=%d "
                "destination_reached_by_forward=%s origin_reached_by_backward=%s tree_ms=%d",
                int(np.isfinite(forward_tree.node_cost).sum()), int(np.isfinite(backward_tree.node_cost).sum()),
                bool(np.isfinite(forward_tree.node_cost[destination_index])),
                bool(np.isfinite(backward_tree.node_cost[context.origin_index])),
                tree_ms,
            )
            return []

        best_index = int(np.argmin(np.where(reachable, combined_cost, np.inf)))
        best_length_m = float(combined_length[best_index])
        within_stretch = reachable & (combined_length <= best_length_m * ALTERNATIVE_MAX_STRETCH)
        # 打ち切りは**並べてから**行う（周回の折返し点選定と同じ規則）。Node index順で先に
        # 切ると、良い候補が後ろのindexに居るだけで検討対象から外れる。
        candidates = np.flatnonzero(within_stretch)

        if self._penalty_strength > 0:
            with np.errstate(invalid="ignore", divide="ignore"):
                difficulty = (
                    (combined_cost[candidates] / combined_seconds[candidates] - 1.0)
                    / self._penalty_strength * 100.0
                )
            difficulty = np.where(np.isfinite(difficulty), difficulty, 0.0)
        else:
            # P=0はコスト＝所要時間（難易度を一切考慮しない）なので全候補同点。
            difficulty = np.zeros(len(candidates))
        difficulty_key = np.round(difficulty, 1)
        # 周回の折返し点選定と同じく、経路長・difficultyのパレート非劣解を先に並べる
        # （難易度は距離加重平均のため、遠回りするほど下がる。目的地ルートは目標距離を
        # 持たずALTERNATIVE_MAX_STRETCH倍以内という上限だけが効くぶん、難易度単独で
        # 並べると伸び率上限いっぱいの遠回りが上位を占めやすい）。
        pareto_layer = pareto_layer_index(
            combined_length[candidates], difficulty,
            quantum_a=PARETO_DISTANCE_QUANTUM_M, quantum_b=PARETO_DIFFICULTY_QUANTUM,
            max_items=max_routes,
        )
        layer_key = np.where(pareto_layer >= 0, pareto_layer, np.iinfo(np.int32).max)
        order = np.lexsort((candidates, difficulty_key, layer_key))
        ranked = candidates[order][:MAX_VIA_NODE_CANDIDATES_EXAMINED].tolist()
        if len(candidates) > MAX_VIA_NODE_CANDIDATES_EXAMINED:
            logger.warning(
                "via-node候補を打ち切りました within_stretch=%d examined=%d "
                "（上位から順に見るため、打ち切られたのは並べた後の下位）",
                len(candidates), MAX_VIA_NODE_CANDIDATES_EXAMINED,
            )
        if best_index in ranked:
            ranked.remove(best_index)
        ranked.insert(0, best_index)

        full_edges_cache: dict[int, list[int] | None] = {}
        forward_edge_count: dict[int, int] = {}

        def full_edges(node_index: int) -> list[int] | None:
            if node_index not in full_edges_cache:
                forward_state = int(junction.forward_state[node_index])
                backward_state = int(junction.backward_state[node_index])
                forward_edges = (
                    turn_expanded_path_from_state(forward_tree, forward_state) if forward_state >= 0 else None
                )
                # backward_stateが-1なのは目的地そのものを指す場合で、後ろ向きの区間は無い。
                backward_edges = (
                    turn_expanded_path_from_state_to_source(backward_tree, backward_state)
                    if backward_state >= 0 else []
                )
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
            "best_km=%.1f detour_ratio_median=%.2f tree_ms=%d junction_ms=%d",
            int(reachable.sum()), len(candidates), len(ranked), len(traced), max_routes,
            best_length_m / 1000, detour_ratio_median, tree_ms, junction_ms,
        )
        return traced

    async def select_fastest_route(
        self, context: _RoadGraphContext, destination: Coordinates
    ) -> TracedLoop | None:
        """所要時間が最短の経路を1本返す（主観的な軸の重みを一切使わない基準線）。

        コスト配列に区間ごとの所要時間（走行モデル＋停止の待ち）を、遷移にはターンの待ちを
        そのまま秒で渡すため、得られるのは**時間最短**の経路になる。利用者の好み（軸の重み）を
        すべて0にしたときの経路であり、候補が基準線に対して何を犠牲に何を得たかを読むための
        物差しになる。

        **軸の重みは使わないが、0次フィルタ（`no_bicycle`・`motorway`・`trunk`・
        `max_average_grade_percent`）は使う**——これらは好みではなく通行可否・走行可否の
        表明であり、所要時間を優先する経路でも越えてよいものではない。除外Edgeの所要時間を
        `inf`にすることで表現する（軸コスト経路で`cost_lazy`が`inf`になっているのと同じ意味）。

        `select_via_nodes`の後に呼ぶ前提（目的地の再スナップ結果
        `context.destination_correction`を引き継ぐ）。

        レグは経路の所要時間が半分になる位置で割る——他の候補と同じく往路レグ・復路レグへ
        概ね半分ずつ割れ、レグごとに時刻の異なる風の評価が候補間で揃う。
        """
        lazy_graph = context.lazy_graph
        destination = context.destination_correction or destination
        destination_node = find_nearest_node_indexed(context.node_index, destination)
        if destination_node is None:
            return None
        destination_index = lazy_graph.node_id_to_index[destination_node]

        started = time.monotonic()
        outbound = context.legs[0]
        time_bins = outbound.travel_bins_lazy
        edges = await asyncio.to_thread(
            turn_expanded_shortest_path,
            context.turn_structure, time_bins,
            _heuristic_seconds(
                _estimate_distances_m(context.graph, context.node_lat, context.node_lon, destination_node)
            ),
            _origin_states(context.statics, context.origin_index), destination_index,
            time_bins, outbound.bin_seconds,
        )
        if not edges:
            logger.warning("select_fastest_route no path to destination=%s", destination_node)
            return None

        # 往路レグ・復路レグへ概ね半分ずつ割る（レグごとに時刻の異なる風の評価が候補間で
        # 揃うよう、他の候補と同じ扱いにする）。区切りは所要時間の半分。
        seconds = [float(outbound.travel_seconds_lazy[index]) for index in edges]
        half_seconds = sum(seconds) / 2
        cumulative = 0.0
        split = len(edges)
        for position, value in enumerate(seconds):
            cumulative += value
            if cumulative >= half_seconds:
                split = position + 1
                break
        forward_edges = edges[:split]
        backward_edges = edges[split:]
        edge_ids = [lazy_graph.edge_ids[index] for index in forward_edges + backward_edges]
        if not edge_ids:
            return None
        distance_km = round(sum(context.graph.edges[edge_id].distance_m for edge_id in edge_ids) / 1000, 2)
        leg_of_edge = [0] * len(forward_edges) + [1] * len(backward_edges)

        logger.info(
            "select_fastest_route fastest_km=%.1f edges=%d forward_edges=%d elapsed_ms=%d",
            distance_km, len(edge_ids), len(forward_edges), round((time.monotonic() - started) * 1000),
        )
        return TracedLoop(bearing=None, distance_km=distance_km, data=edge_ids, leg_of_edge=leg_of_edge)

    async def trace_loop_from_turnaround(self, context: _RoadGraphContext, turnaround: LoopTurnaround) -> TracedLoop:
        """往路（一対全木上の経路、`select_loop_turnarounds`で確定済み）に、往路と別の
        復路（折返し点→起点のA*）を継いで周回にする。

        復路探索の間だけ、往路Edge＋同一Node対の逆方向Edgeのコストを
        `RETRACE_PENALTY_MULTIPLIER`倍に**差し替え**、探索後に元へ戻す（コスト配列全体の
        コピーは1回10ms超[56万Edge]でプール分積み上がるため、差し替え＋復元で
        O(往路Edge数×時刻ビン数)にする）。時刻ビンを張った復路では全ビンの同じ列を
        まとめて差し替える——どの時刻に通っても「往路をなぞる」ことに変わりはない。この差し替えはawaitを挟まない同期区間で完結するため、
        asyncioの協調スケジューリング下では他コルーチンから見えない。**将来
        `asyncio.to_thread`等で復路探索を並列化する場合は、共有`cost_lazy`を書き換える
        この方式は成立しない**（tests/test_road_graph_engine.pyの回帰テスト参照）。
        倍率は有限のため、復路が往路を戻る以外に道が無い区間（袋小路・起点付近の
        単一の道）は自然にそのまま通れる。
        """
        data: _TurnaroundData = turnaround.data
        lazy_graph = context.lazy_graph
        graph = context.graph
        # 復路レグのコスト配列（select_loop_turnaroundsが合成済み。無ければ往路と共有）。
        inbound_leg = context.legs[1] if len(context.legs) > 1 else context.legs[0]
        cost_bins = inbound_leg.cost_bins_lazy

        penalized: set[int] = set(data.outbound_edge_indices)
        for edge_index in data.outbound_edge_indices:
            edge = graph.edges[lazy_graph.edge_ids[edge_index]]
            reverse_index = lazy_graph.edge_index_by_node_pair.get(
                (lazy_graph.node_id_to_index[edge.to_node_id], lazy_graph.node_id_to_index[edge.from_node_id])
            )
            if reverse_index is not None:
                penalized.add(reverse_index)

        trace_started = time.monotonic()
        penalized_columns = np.fromiter(penalized, dtype=np.int64, count=len(penalized))
        original = cost_bins[:, penalized_columns].copy()
        try:
            cost_bins[:, penalized_columns] = original * RETRACE_PENALTY_MULTIPLIER
            return_edge_index_list = turn_expanded_shortest_path(
                context.turn_structure, cost_bins, _heuristic_seconds(_origin_estimate(context)),
                _origin_states(context.statics, lazy_graph.node_id_to_index[data.node_id]),
                context.origin_index,
                inbound_leg.travel_bins_lazy, inbound_leg.bin_seconds,
            )
        finally:
            cost_bins[:, penalized_columns] = original
        trace_wall_ms = round((time.monotonic() - trace_started) * 1000)
        if return_edge_index_list is None:
            raise RoutingError(f"turnaround bearing={turnaround.bearing}: no return path found")

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

    def build_traced_from_edge_ids(
        self, context: _RoadGraphContext, edge_ids: list[str], destination: Coordinates | None = None,
    ) -> TracedLoop:
        """クライアントが組み立てたEdge id列を、評価できる経路として検証して`TracedLoop`にする。

        区間の乗り換え（docs/tasks/T621.md）で使う。フロントは候補の`edge_ids`から
        「Aの前半＋Bの後半」を作って送り返すため、**このグラフに実在し・順につながり・
        起点から始まり・目的地へ着く**ことをここで確かめる（送られた列をそのまま信じると、
        評価は成功するのに経路として成立しないルートが候補一覧へ並ぶ）。

        終点は`destination`を渡したときだけ見る。起点と同じ`find_nearest_node_indexed`で
        解くため、比べる相手は元の候補が実際に終わったNodeになる——目的地がメインの
        道路網から孤立していてbackendが補正した場合、フロントは補正後の地点を条件として
        持ち直しており（`page.tsx`の`corrected_destination`）、合成もその地点で送られる。

        レグはこの経路自身の距離の半分で切る。合成経路はvia-nodeを持たないため前向き木・
        後ろ向き木の境目が無く、レグが表す「走り始めの時刻帯／走り終わりの時刻帯」の
        近似が入れ替わる点として中間を採る。**レグ番号を振る側が、その番号のレグを
        `context.legs`へ用意する**——`prepare`が作るのは往路レグだけで、復路レグは探索
        （折返し点の選定・経由Nodeの選定）が作る。合成経路はどちらの探索も通らない。
        """
        graph = context.graph
        if not edge_ids:
            raise RoutingError("経路が空です")
        unknown = [edge_id for edge_id in edge_ids if edge_id not in graph.edges]
        if unknown:
            raise RoutingError(
                f"経路に未知のEdgeが含まれています count={len(unknown)} first={unknown[0]}"
            )
        edges = [graph.edges[edge_id] for edge_id in edge_ids]
        if edges[0].from_node_id != context.origin_node:
            raise RoutingError(
                f"経路が起点から始まっていません expected={context.origin_node} actual={edges[0].from_node_id}"
            )
        for index, (current, following) in enumerate(zip(edges, edges[1:])):
            if current.to_node_id != following.from_node_id:
                raise RoutingError(
                    f"経路がつながっていません index={index} "
                    f"to_node={current.to_node_id} next_from_node={following.from_node_id}"
                )
        if destination is not None:
            destination_node = find_nearest_node_indexed(context.node_index, destination)
            if destination_node is not None and edges[-1].to_node_id != destination_node:
                raise RoutingError(
                    f"経路が目的地に着いていません expected={destination_node} "
                    f"actual={edges[-1].to_node_id}"
                )

        total_m = sum(edge.distance_m for edge in edges)
        leg_of_edge, travelled_m = [], 0.0
        for edge in edges:
            leg_of_edge.append(0 if travelled_m < total_m / 2 else 1)
            travelled_m += edge.distance_m
        if max(leg_of_edge) > 0 and len(context.legs) < 2:
            total_hours = total_m / 1000 / context.composer.speed_kmh
            context.legs = [
                context.legs[0],
                context.composer.compose(
                    "inbound", context.origin, total_hours, -1, duration_hours=total_hours / 2
                ),
            ]
        return TracedLoop(
            bearing=None, distance_km=round(total_m / 1000, 2), data=edge_ids, leg_of_edge=leg_of_edge
        )

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
        elevation_attributes = self._elevation_attributes(context, edges_in_path)
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
        reverse_candidate = self._build_candidate(
            context, traced, reverse_edges, reverse_elevation_attributes, start_time, _reverse_leg_assignment(leg_of_edge)
        )
        return _pick_better_candidate(forward_candidate, reverse_candidate)

    def _elevation_attributes(
        self, context: "_RoadGraphContext", edges_in_path: list[EdgeLike]
    ) -> dict[str, ElevationAttribute]:
        """経路の区間ぶんの標高属性。探索フェーズで読んだ材料がそのまま持っている。

        取り込んだ範囲の全区間ぶんを派生バッチが埋めるため、ここで外部へ取りに行く経路は
        無い（欠けているのは標高タイルが覆っていない区間だけで、そこは値なしのまま）。
        """
        found = {}
        for edge in edges_in_path:
            attribute = context.materials.elevation_attribute(edge.edge_id)
            if attribute is not None:
                found[edge.edge_id] = attribute
        return found

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
        geometry, edge_point_offsets = _concat_edge_geometries(edges_in_path)
        elevation_stats = _aggregate_elevation(edges_in_path, elevation_attributes)
        segments = self._build_segment_details(edges_in_path, elevation_attributes, context, start_time, leg_of_edge)
        # categorical材料の延長割合はEdge単位のsegmentsから畳む。ビンの代表値を1つ選ぶ形だと
        # 割合が500m単位へ量子化されるため、集約より前に計算する
        # （`domain/route.py: BIN_DROPPED_DICT_FIELDS`参照）。
        material_category_shares = merge_material_category_shares(segments)
        # APIレスポンスとして返すsegmentsは約500m単位に集約する（Edge単位のままだと
        # 30km級で150〜230件になりペイロード・フロント描画コストが嵩む）。
        segments = aggregate_segments_into_bins(segments)

        return RouteCandidate(
            **candidate_identity(traced.bearing),
            distance_km=traced.distance_km,
            geometry=geometry,
            edge_ids=[edge.edge_id for edge in edges_in_path],
            edge_point_offsets=edge_point_offsets,
            node_ids=(
                [edges_in_path[0].from_node_id, *(edge.to_node_id for edge in edges_in_path)]
                if edges_in_path else []
            ),
            segments=segments,
            material_category_shares=material_category_shares,
            estimated_duration_seconds=self._estimate_duration_seconds(context, edges_in_path, leg_of_edge),
            **elevation_stats,
        )

    def _estimate_duration_seconds(
        self, context: _RoadGraphContext, edges: list[EdgeLike], leg_of_edge: list[int]
    ) -> float | None:
        """候補の所要時間（秒）＝ 区間の走行時間 ＋ 停止の待ち ＋ ターンの待ち。

        区間ごとの秒は、探索のコストの下地になっている配列（`LegCostArrays.
        travel_seconds_full`、走行モデル＋停止の待ち）をそのまま読む——表示の所要時間と
        探索が使う所要時間を別々に計算すると、片方だけ直したときに静かに食い違う。
        ターンは経路の遷移ごとの秒（`TurnExpandedStructure`）を足す。

        行を引けない区間（タイル境界等で静的スコア行列に無い）は巡航速度で走ったものとして
        数える——0にすると所要時間が実態より短く出る。
        """
        if not edges:
            return None
        fallback_ms = kmh_to_ms(context.composer.speed_kmh)
        total = 0.0
        for edge, leg_index in zip(edges, leg_of_edge):
            leg = context.legs[leg_index]
            row = context.full_edge_row.get(edge.edge_id)
            seconds = leg.travel_seconds_full[row] if row is not None else np.inf
            total += float(seconds) if np.isfinite(seconds) else edge.distance_m / fallback_ms
        return total + self._turn_seconds_along(context, edges)

    def _turn_seconds_along(self, context: _RoadGraphContext, edges: list[EdgeLike]) -> float:
        """経路に沿ったターンの待ち（秒）の合計。遷移は`TurnExpandedStructure`から引く。

        探索グラフに無いEdge（クライアント由来のedge_id列を受ける区間の乗り換えで起こりうる）
        は、そこで経路が切れたものとして扱い、**その前後の遷移だけ**を数えない。経路全体を
        捨てると合成ルートだけターン分（都市部30kmで数分〜十数分規模）が丸ごと消え、元候補
        より不当に速く見える。捨てた事実はWARNINGで残す（docs/logging.md）。
        """
        structure = context.turn_structure
        lazy_graph = context.lazy_graph
        states: list[int | None] = []
        for edge in edges:
            pair = (
                lazy_graph.node_id_to_index.get(edge.from_node_id),
                lazy_graph.node_id_to_index.get(edge.to_node_id),
            )
            states.append(lazy_graph.edge_index_by_node_pair.get(pair) if None not in pair else None)
        unknown = sum(1 for state in states if state is None)
        if unknown:
            logger.warning(
                "ターンの待ちを一部数えられません edges=%d unknown=%d "
                "（探索グラフに無い区間の前後の遷移を除外して合計します）",
                len(edges), unknown,
            )
        total = 0.0
        for previous, following in zip(states, states[1:]):
            if previous is None or following is None:
                continue
            for entry in range(structure.indptr[previous], structure.indptr[previous + 1]):
                if structure.target_state[entry] == following:
                    total += float(structure.turn_seconds[entry])
                    break
        return total

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
                axis_raw_values: dict[str, float] = {}
                composite_difficulty_value: float | None = None
                material_values: dict[str, float] = static_material_values
                material_categories: dict[str, str] = {}
            else:
                axis_scores = {
                    axis_id: float(arr[row])
                    for axis_id, arr in leg.axis_arrays.items()
                    if not math.isnan(arr[row])
                }
                axis_contributions = leg.axis_contributions_at(row)
                # 折れ点を通す前の生値。静的スコア行列が持つ列をそのまま読む
                # （動的材料を参照する軸は行列側で除外済み）。
                axis_raw_values = {
                    axis_id: float(arr[row])
                    for axis_id, arr in leg.axis_raw_arrays.items()
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
                # categorical材料は数値として平均できないため、区間ごとの値をそのまま持ち、
                # ルート集約側（merge_material_category_shares）で延長割合へ畳む。
                material_categories = {
                    material_id: str(raw)
                    for material_id, array in leg.categorical_material_arrays.items()
                    if material_id in active_material_ids and (raw := array[row]) is not None
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
                    axis_raw_values=axis_raw_values,
                    axis_contributions=axis_contributions,
                    material_values=material_values,
                    material_categories=material_categories,
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
    material_ids: set[str] = set()
    for axis_id, weight in weights.items():
        if weight <= 0:
            continue
        definition = AXIS_DEFINITIONS.get(axis_id)
        if definition is None:
            continue
        material_ids.update(m for m in definition.materials if is_known_material(m))
        # 軸参照を辿った先の材料（合成軸の内訳、`axis_material_shares`）。
        # `definition.materials`は1段しか見ないため、これが無いと車の圧迫感のように
        # 内部軸を経由する軸の内訳が1件も運ばれない。
        material_ids.update(entry.material_id for entry in axis_material_shares(definition))
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

    並行Edge（同一Node間の複数Edge）はedge_idの昇順で先頭を採る——コストはリクエストごと
    （軸重み・風・0次フィルタ）に変わるため、タイル集合だけで決まるこのキャッシュとは
    「cost最小を採用」方式が両立しない。2つの並行Edgeのうち一方だけがこのリクエストの
    0次フィルタで除外される稀なケースでは、`(u,v)`ペア自体が到達不能になりうる。実データでの並行Edge自体が稀なうえ、その中でさらに片方だけ
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
    tile_set: frozenset[tuple[int, int, int]] | None,
    lazy_graph: LazyRoadGraph,
    graph: RoadGraphLike,
    score_matrix_rows: Container[str],
) -> LazyRoadGraph:
    """`lazy_graph.edge_ids`が`graph.edges`の部分集合であることを検証し、崩れていれば
    タイル集合キャッシュ3種を破棄して`lazy_graph`ごと`graph`から作り直す
    （`prepare`・`preview_segment`共通の`_build_search_graph`が呼ぶ）。

    `_lazy_graph_cache`と`_search_statics_cache`はLRU上限に達すると独立に最古のエントリを
    追い出すため、再split（`save_graph`のedge_id再割当）を挟むと「`lazy_graph`はキャッシュ
    ヒットで古いまま」という状態が起こりうる。放置すると、直後の
    `full_edge_row[edge_id] for edge_id in lazy_graph.edge_ids`（`_build_search_graph`）や
    `domain/routing.py: build_search_graph_statics`が同種のKeyErrorを起こす。この関数は
    `domain/routing.py: find_missing_lazy_graph_edge_id`（CSR構築を伴わない軽量版チェック）
    で不整合の有無だけを先に確認し、無ければ`lazy_graph`をそのまま返す。呼び出し側は
    以降このメソッドの戻り値を使うこと（引数の`lazy_graph`を使い続けると同じKeyError相当を
    再現する）。
    """
    missing = await asyncio.to_thread(
        find_missing_lazy_graph_edge_id, lazy_graph, graph, also_required_in=score_matrix_rows
    )
    if missing is None:
        return lazy_graph
    if tile_set is not None:
        logger.warning("search_graph_cache stale_lazy_graph tile_set_size=%d rebuilding", len(tile_set))
        search_graph_cache.invalidate_tile_set(tile_set)
    lazy_graph = await asyncio.to_thread(build_lazy_road_graph, graph)
    if tile_set is not None:
        search_graph_cache.set_lazy_graph(tile_set, lazy_graph)
    still_missing = await asyncio.to_thread(
        find_missing_lazy_graph_edge_id, lazy_graph, graph, also_required_in=score_matrix_rows
    )
    if still_missing is not None:
        # `graph`から作り直しても解消しない＝ずれているのは静的スコア行列側
        # （材料とは別キャッシュ・別世代）。ここで黙って進むと`full_edge_row`引きが
        # KeyErrorになり、原因の分からない500として現れる。
        raise LazyGraphEdgeMismatchError(
            f"score_matrix does not cover edge_id '{still_missing}' present in the rebuilt graph"
            " (tile_score_matrix_cache is stale relative to graph_material_cache)"
        )
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


async def _get_or_build_turn_structure(
    tile_set: frozenset[tuple[int, int, int]] | None,
    statics: SearchGraphStatics,
    lazy_graph: LazyRoadGraph,
    graph: RoadGraphLike,
    turn_cost: TurnCostSpec,
) -> tuple[TurnExpandedStructure, bool]:
    """状態＝有向区間の遷移構造を、タイル集合とターンの費用をキーにキャッシュする。

    遷移とターンの費用は道路網の形と`turn_cost`だけで決まり、リクエストごとのコスト配列には
    依存しないため`SearchGraphStatics`と同じ寿命で持てる。構築は本番規模で数百msかかる。
    """
    key = (tile_set, turn_cost) if tile_set is not None else None
    if key is not None:
        cached = search_graph_cache.get_turn_structure(key)
        if cached is not None:
            return cached, True
    node_signals, node_ranks = _node_intersection_attributes(graph, lazy_graph)
    structure = await asyncio.to_thread(
        build_turn_expanded_structure,
        statics.csr, lazy_graph, edge_bearings(graph, lazy_graph),
        _edge_highway_ranks(graph, lazy_graph), turn_cost,
        node_signals, node_ranks,
    )
    if key is not None:
        search_graph_cache.set_turn_structure(key, structure)
    return structure, False


def _node_intersection_attributes(
    graph: RoadGraphLike, lazy_graph: LazyRoadGraph
) -> tuple[np.ndarray, np.ndarray]:
    """`lazy_graph.index_to_node_id`順の（信号の有無, 集まる道の最大階級）。

    どちらも`road_nodes`の事前集計列（`precompute_road_node_intersections.py`と、
    交差点分割が自分の作ったノードへ行う穴埋め）で、ターンの費用が「信号が無いのに上位の道を
    渡る」場合だけ待ちを足すために読む。どちらも受けていないノードは既定値（信号なし・
    階級0）で、そのときの結果はこの列の導入前と同じになる。
    """
    nodes = graph.nodes
    signals = np.fromiter(
        ((node.has_traffic_signals if (node := nodes.get(node_id)) else False)
         for node_id in lazy_graph.index_to_node_id),
        dtype=bool, count=len(lazy_graph.index_to_node_id),
    )
    ranks = np.fromiter(
        ((node.max_highway_rank if (node := nodes.get(node_id)) else 0)
         for node_id in lazy_graph.index_to_node_id),
        dtype=np.int64, count=len(lazy_graph.index_to_node_id),
    )
    return signals, ranks


def _edge_highway_ranks(graph: RoadGraphLike, lazy_graph: LazyRoadGraph) -> np.ndarray:
    """`lazy_graph.edge_ids`順の道路階級（`domain/traffic.py: highway_rank`）。交差点で
    「自分より上位の道と交わるか」を比べるためだけに使う。"""
    return np.fromiter(
        (highway_rank(edge.highway if (edge := graph.edges.get(edge_id)) else None)
         for edge_id in lazy_graph.edge_ids),
        dtype=np.int64, count=len(lazy_graph.edge_ids),
    )


def _origin_states(statics: SearchGraphStatics, node_index: int) -> np.ndarray:
    """`node_index`から出る有向Edge（＝辺基準の木の始点となる状態）。"""
    csr = statics.csr
    return csr.entry_edge_index[csr.indptr[node_index]:csr.indptr[node_index + 1]].astype(np.int64)


def _add_terminal_candidate(
    junction: NodeJunction, forward: TurnExpandedTree, destination_index: int
) -> None:
    """目的地そのものを経由Nodeとする候補（＝どこも経由せず目的地で終わる経路）を足す。

    `combine_forward_backward_at_nodes`は「入る区間×出る区間」の対でNodeを繋ぐため、
    そこで終わる経路は現れない。後ろ向きの区間が無いことは`backward_state=-1`で表す。

    **`NodeJunction`の全フィールドを揃えて書く**——1つでも繋ぎ目側の値が残ると、コストと
    所要時間が別々の経路のものになり、`(cost/seconds - 1)/P`で逆算するdifficultyが壊れる。
    """
    state = int(forward.node_best_state[destination_index])
    if state < 0:
        return
    junction.cost[destination_index] = forward.node_cost[destination_index]
    junction.length_m[destination_index] = forward.node_length_m[destination_index]
    junction.seconds[destination_index] = forward.node_seconds[destination_index]
    junction.forward_state[destination_index] = state
    junction.backward_state[destination_index] = -1


def _destination_states(structure: TurnExpandedStructure, node_index: int) -> np.ndarray:
    """`node_index`へ入る有向Edge（＝逆向きの辺基準木の始点となる状態）。"""
    return np.flatnonzero(structure.edge_to == node_index)


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
    直線距離（m）をnumpyで1回だけベクトル計算する。2点間探索のA*ヒューリスティック
    （`_heuristic_seconds`が秒へ直す）の素材になる。
    """
    target_node = graph.nodes[target_node_id]
    return (haversine_distance_km_array(node_lat, node_lon, target_node) * 1000).tolist()


def _heuristic_seconds(straight_m: np.ndarray | list[float]) -> np.ndarray:
    """Nodeごとの直線距離（m）を、所要時間の下界（秒）へ直す。

    実経路は直線より長く、実際の速度は下りの上限以下のため、これは真の
    所要時間を上回らない＝A*のヒューリスティックとして使える（admissible）。主観的割増は
    1以上の倍率のため、割増を含むコストに対しても下界であり続ける。
    """
    return np.asarray(straight_m, dtype=float) / kmh_to_ms(tuning_value("speed.max_descent_kmh"))


def _origin_estimate(context: _RoadGraphContext) -> np.ndarray:
    """復路探索（目的地＝起点）のA*ヒューリスティック。起点は1リクエストで固定のため
    初回だけ`_estimate_distances_m`で計算し、以降の候補はcontextに保持した配列を共有する。
    """
    if context.origin_estimate is None:
        context.origin_estimate = _estimate_distances_m(
            context.graph, context.node_lat, context.node_lon, context.origin_node
        )
    return context.origin_estimate


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


def _reverse_leg_assignment(leg_of_edge: list[int]) -> list[int]:
    """逆回り候補のレグ割当てを求める（先に走る側が往路配列）。

    `context.legs`は走行順にレグ番号を振った時間帯別のコスト配列のため、Edge列の反転と
    同時にレグ番号自体も`max_leg - leg`へ振り直す必要がある（並びだけを反転させると、
    走り始めを帰着時刻の風、走り終わりを出発時刻の風で評価することになる）。
    """
    if not leg_of_edge:
        return []
    max_leg = max(leg_of_edge)
    return [max_leg - leg for leg in reversed(leg_of_edge)]


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


def _concat_edge_geometries(edges: list[EdgeLike]) -> tuple[dict, list[int]]:
    """経路上のEdge群を、ひとつながりのGeoJSON LineStringとEdgeの境界点の位置へ変換する。

    隣接するEdgeの境界点（前Edgeの終端＝次Edgeの始端）は重複させないため、**座標列だけ
    からはどこがEdgeの境目か復元できない**。Edge単位で決めた区間を地図へ帯として描く
    （docs/tasks/T621.md）ために境界の位置を併せて返す。

    2つ目の戻り値は`len(edges) + 1`件で、`coordinates[offsets[i]:offsets[j] + 1]`が
    Edge i〜j-1のひとつながりの形状になる。**同じ関数が両方を作る**——別々に組み立てると
    ずれても型でも例外でも現れず、地図上で帯だけが1点ずれる。
    """
    coordinates: list[list[float]] = []
    offsets: list[int] = []
    for edge in edges:
        points = [[lon, lat] for lat, lon in edge.geometry]
        if coordinates and points and coordinates[-1] == points[0]:
            points = points[1:]
        offsets.append(max(len(coordinates) - 1, 0))
        coordinates.extend(points)
    offsets.append(max(len(coordinates) - 1, 0))
    return {"type": "LineString", "coordinates": coordinates}, offsets


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


