"""Road Graph + 辺基準グラフ探索（A*/一対全Dijkstra、lazy評価）の自前ルーティングエンジン。

`RouteGenerator`が探索を委譲する先。構造と各段の役割は
docs/modules/backend/routing-engine.mdが持つ。ここには、このファイルを変更するときに
破ってはいけないことだけを書く。

- **Road Graphの取得は1リクエストにつき1回だけ。** 候補ごとにbboxで問い合わせず、
  `prepare`が取った1つのグラフを全候補で共有する。
- **Edgeコストはbbox全体ぶんを1回だけnumpyで合成し、探索へは配列のまま渡す。**
  探索中にPythonのコールバックもEdgeごとのオブジェクトも作らない。
- **候補ごとの探索は直列に実行する。** `trace_loop_from_turnaround`が共有のコスト配列を
  一時的に書き換えるため、並列化と両立しない。
- **区間表示は探索と同じコスト配列・スコア行列から引く。** 二重に計算しない。
- **標高・風は探索フェーズで読んだ材料の中にある。** 経路確定後に外部へ取りに行かない。

割り切り: 同一Node間の並行Edgeは`build_lazy_road_graph`が元の行の小さい1本へ解消する
（トポロジはリクエストごとに変わるコストに依らず決める）。そのため並行Edgeの一方だけが0次
フィルタで除外されると、許可される側ではなく行の小さい側が残り、そのNode対が到達不能になりうる。

区間は探索用グラフの番号（`LazyRoadGraph`の区間）、ノードは探索範囲の切り出しの番号で持ち、
区間の文字列の鍵（`edge_key`）は経路の区間の分だけ作る。
"""

import asyncio
import itertools
import logging
import math
import time
from collections.abc import Callable, Mapping, Sequence
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
from app.domain.attributes import ElevationAttribute
from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    REQUEST_DYNAMIC_MATERIAL_IDS,
    dynamic_axis_topological_order,
)
from app.domain.axis_raw_value import displayed_material_ids
from app.domain.difficulty import axis_contributions_at_row, axis_weighted_sums, distance_weighted_difficulty
from app.domain.errors import RoutingError
from app.domain.dynamic_materials import DynamicAxisRequestContext, evaluate_dynamic_axis_arrays
from app.domain.evaluation import (
    StaticEdgeScoreMatrix,
    AxisComposition,
    compose_costs_from_axis_matrix,
    difficulty_from_cost,
)
from app.domain.hard_filters import compute_hard_filter_excluded, compute_routable_nodes
from app.domain.material_catalog import GRADIENT_PERCENT
from app.domain.route_preference import RoutePreference
from app.domain.geo import (
    KM_PER_DEGREE_LATITUDE,
    bearing_between,
    bearing_between_array,
    haversine_distance_km,
    haversine_distance_km_array,
    km_per_degree_longitude,
)
from app.domain.graph import LeanEdge, edge_key, node_key, parse_edge_key
from app.domain.region import BoundingBox, bbox_covering_points
from app.domain.road_network import RoadSlice, edge_row_of, elevation_attribute
from app.domain.route import (
    Coordinates,
    RouteCandidate,
    RouteSegment,
    RouteSegmentDetail,
    SegmentWind,
    aggregate_segments_into_bins,
    merge_material_category_shares,
)
from app.domain.twilight import is_night
from app.domain.routing import (
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
    edge_index_between,
    find_nearest_node_indexed,
    overlap_ratio,
    pareto_layer_index,
    select_diverse_by_overlap,
    time_bin_of,
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
from app.domain.loop_routing import LoopTurnaround, TracedLoop, candidate_identity
from app.services.weather_service import WeatherService

# Road Graphを取得するbboxは、起点・経由地2点の外接矩形にこのマージンを足したもの。
# 実際の道なりは直線距離の外接矩形からはみ出ることが多い（川・線路等を迂回する等）ため、
# 探索が失敗しない程度の余裕を持たせる。半径に比例させつつ、最低値を設ける。
BBOX_MARGIN_RATIO = 0.3
BBOX_MARGIN_MIN_KM = 2.0

# preview_segment（起点・終点2点間の単発経路確認）が使うbboxマージン。
# ループ探索のBBOX_MARGIN_MIN_KMと同じ「道なりが直線外接矩形からはみ出る余裕」を
# 単純な固定値で持たせる（previewは距離が事前に分からないため半径比例のロジックは使えない）。
PREVIEW_BBOX_MARGIN_KM = 2.0

# --- フロンティア方式の折返し点選定・復路探索のパラメータ ---
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
# するため、復路は往路と同程度以上に長くなる。上下限は解析的には決まらず、実分布から置く。
# リング（折返し候補の往路実距離の範囲）は、この比で周回全長が目標±許容に
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
# 幅を細かくしても隣のビンが同じ予報時刻を引くだけで、合成の回数だけが増える。
TIME_BIN_HOURS = 1.0
MAX_TIME_BINS = 4
# 候補選定（`pareto_layer_index`）で「実質同じ」とみなす粒度。距離は往路実距離200m
# （周回全長では約400m差、体感で選び分ける単位より細かい）、難易度は他の集計値と同じ
# 小数1桁。細かすぎると互いに非劣解な候補が全件残ってフィルタとして働かず、粗すぎると
# 候補が減りすぎる。
PARETO_DISTANCE_QUANTUM_M = 200.0
PARETO_DIFFICULTY_QUANTUM = 0.1

# --- 目的地ルート（via-node方式、経由地無し）の代替経路選定パラメータ ---
# via-node候補（前向き木＋後ろ向き木の合成経路）の長さが、最も合成コストの低い経路の
# 長さの何倍までを候補にするか。
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
    """1レグぶんの合成済みコスト配列一式。`cost_lazy`は区間の番号順（探索が使う
    行順）、それ以外は切り出した区間の順の表示用配列。レグごとに違うのは風（各Edgeの通過予定時刻の風）だけで、静的軸の列は共有する。"""

    cost_lazy: np.ndarray
    difficulty_array: np.ndarray
    axis_arrays: dict[str, np.ndarray]
    # 区間ごとの「データのある軸の重みの合計」。軸別寄与度（表示用）はこれと`axis_arrays`から
    # `axis_contributions_at`が読むときに1行だけ求める——全区間ぶん作っても、読むのは
    # 経路上の数百区間だけのため。
    weight_sums: np.ndarray
    weights: dict[str, float]
    # 折れ点を通す前の生値（切り出した区間の順）。静的スコア行列の列をそのまま指すため
    # レグ間で同じ配列を共有する（風のようにレグごとに変わる値は持たない）。
    axis_raw_arrays: dict[str, np.ndarray]
    # 切り出した区間の順の材料id→配列。動的材料（`evaluate_dynamic_material_arrays`が返す
    # 全材料が対象、全行NaNの材料はキーを持たない）と、内訳表示用の静的材料
    # （`route_facing_material_ids`、静的スコア行列の列）の両方を持つ。区間表示・
    # `material_values`の集計が、探索コストの合成と同じ入力から求めた値を読むために保持する。
    material_arrays: dict[str, np.ndarray]
    # 切り出した区間の順のcategorical材料id→値の配列（静的スコア行列の列をそのまま指すため
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
    # 各ビンを評価した時刻（出発からの経過[h]）。風の時別予報が無いレグ（出発時点の値で1本）と、区間ごとの
    # 通過時刻で1本に合成したレグは空。**表示用の配列（`difficulty_array`等）は代表ビンのものだけ**なので、
    # ビンが2本以上あるレグの区間は、経路をたどって決めたビンの時刻で経路上の行だけを合成し直して読む
    # （`_LegCostComposer.values_at_rows`）。
    bin_start_hours: tuple[float, ...] = ()
    # 区間ごとの通過時刻（出発からの経過[h]、切り出した区間の順）で1本に合成したレグ（目的地から遡る木）だけが持つ。
    passage_hours: np.ndarray | None = None

    def axis_contributions_at(self, row: int) -> dict[str, float]:
        """その区間の軸別寄与度（切り出した区間の順の行番号で引く）。"""
        return axis_contributions_at_row(self.axis_arrays, self.weights, self.weight_sums, row)


@dataclass
class RowValues:
    """経路上の行だけを、ある時刻で合成し直した表示用の値。配列は`rows`と同じ並びで、`LegCostArrays`と
    同じ名前の属性を持つ（区間の組み立ては、どちらから読んでも同じ書き方になる）。"""

    rows: np.ndarray
    difficulty_array: np.ndarray
    axis_arrays: dict[str, np.ndarray]
    weight_sums: np.ndarray
    weights: dict[str, float]
    material_arrays: dict[str, np.ndarray]

    def axis_contributions_at(self, row: int) -> dict[str, float]:
        return axis_contributions_at_row(self.axis_arrays, self.weights, self.weight_sums, row)


@dataclass(frozen=True)
class _EdgePassage:
    """経路上の1区間を、探索と同じ規則でたどったときの時刻。"""

    # 探索がこの区間に使った時刻ビン。
    time_bin: int
    # 出発から、この区間に入るまでの秒（走行と、曲がる待ちを含む）。到達予想はこれから出す。
    elapsed_seconds: float
    # この区間を走る秒（探索と同じビンの値。有限でなければ巡航速度で走ったものとして数える）。
    seconds: float
    # レグの時刻ビンの範囲の先で、最後のビンをそのまま使った区間。
    beyond_bins: bool


def _representative_bin(bin_count: int, duration_hours: float | None) -> int:
    """表示と、時刻ラベルを持てない探索が使う代表ビンの添字。レグの中間地点が入るビン。

    見込み時間が無ければビンは1本（`_bin_count`）になる。ビンが2本以上あるのに見込み時間が
    無いのは組み立ての誤りで、代表ビンを決められないため送出する。
    """
    if bin_count <= 1:
        return 0
    if duration_hours is None:
        raise ValueError(f"見込み時間が無いのにビンが{bin_count}本ある")
    return min(bin_count - 1, int((duration_hours / 2) / TIME_BIN_HOURS))


def _row_taker(rows: np.ndarray | None) -> Callable[[np.ndarray], np.ndarray]:
    """配列から行`rows`だけを取り出す関数（Noneなら配列をそのまま返す）。"""
    if rows is None:
        return lambda values: values
    return lambda values: values[rows]


@dataclass
class _Evaluated:
    """`_LegCostComposer._evaluate`の途中結果。"""

    published: dict[str, np.ndarray]
    material_arrays: dict[str, np.ndarray]
    travel: np.ndarray
    composed: AxisComposition


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
        # 格子点ごとの系列のとき、各Edgeの中点に最も近い予報の格子点（切り出した区間の順）。
        self._wind_points = (
            None if wind_series is None or wind_series.lattice is None
            else wind_series.lattice.points_of(score_matrix.mid_lat, score_matrix.mid_lon)
        )
        self.start = start
        self.speed_kmh = speed_kmh
        self._lazy_row_index = lazy_row_index
        # lazy行順の配列を切り出した区間の順へ戻す並べ替え表（`_lazy_row_index`の逆）。
        # `_lazy_row_index`は全単射ではない——同一Node間の並行Edgeは`build_lazy_road_graph`が
        # 1本だけ採るため、探索用グラフに載らないEdgeがある。載らない行は-1にする。
        self._full_row_index = np.full(len(score_matrix.distance_m), -1, dtype=np.int64)
        self._full_row_index[lazy_row_index] = np.arange(len(lazy_row_index))
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
        self,
        material_arrays: dict[str, np.ndarray],
        headwind_ms: np.ndarray,
        crosswind_ms: np.ndarray,
        rows: np.ndarray | None = None,
    ) -> np.ndarray:
        """区間ごとの所要時間（秒）を切り出した区間の順で返す。

        走行モデル（`domain/cycling_speed.py`）で勾配・風の成分・路面・巡航速度から求めた
        走行時間に、その区間にある停止要因の待ち（`domain/traffic.py: stop_seconds`）を
        足したもの。
        ターンの待ちは遷移ごとに決まるためここには含まない（探索側が足す）。
        0次フィルタで除外された区間は無限大にする（探索から見た通行可否をコストの下地だけで
        表すため）。`rows`を渡すとその行だけ（引数の配列も同じ並び）で求める。
        """
        take = _row_taker(rows)
        profile = RiderProfile(cruise_speed_kmh=self.speed_kmh)
        distance_m = take(self._score_matrix.distance_m)
        # 勾配は静的スコア行列が生配列として常に持つ（0次フィルタの勾配しきい値と同じ列）。
        # `material_arrays`は「内訳として見せる材料」だけのため、勾配軸が分解されていない
        # 構成では欠ける。
        grade = np.nan_to_num(take(self._score_matrix.gradient_percent)) / 100.0
        crr = crr_for_surface(material_arrays.get(ROLLING_RESISTANCE_MATERIAL_ID), len(distance_m))
        travel = travel_seconds(distance_m, profile, grade, headwind_ms, crosswind_ms, crr)
        stops = np.zeros(len(distance_m))
        # 材料idの綴りは`stop_count_material_ids()`が単一の情報源。ここで組み立て直すと、
        # 向こうで綴りを変えたときにここだけがNoneを引き、全区間の停止の待ちが無言で0秒になる。
        for kind, material_id in zip(POI_COUNT_KINDS, stop_count_material_ids(), strict=True):
            per_km = material_arrays.get(material_id)
            if per_km is not None:
                stops += np.nan_to_num(per_km) * (distance_m / 1000.0) * stop_seconds(kind)
        return np.where(take(self._hard_filter_excluded), np.inf, travel + stops)

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

        `anchor`は座標の値も在るかどうかも使わない（ログへ出すだけ）——風の予報は起点
        1地点ぶんを`WeatherService`が既に引いており、ここでは方位だけがEdgeごとに効く。
        時刻で変えるかどうかは`time_varying`（風の時別系列があるか）だけで決まる。

        `duration_hours`（このレグに何時間かかる見込みか）を渡すと、レグの中を
        `TIME_BIN_HOURS`ごとのビンへ分けた配列（`cost_bins_lazy`）も併せて作る。到達時刻を
        ラベルとして持ち回れる探索はビンを引き、**経過時間の推定ではなく実際の経過時間**で
        風を評価する。`cost_lazy`等の代表値（表示と、時刻ラベルを持てない後ろ向き木が使う）は
        レグの中央のビン。

        `duration_hours`を渡さない場合はビン1本＝レグ全体を開始時刻で評価する。時刻ラベルを
        持てない探索（目的地から遡る木）だけは、前向き木が出した実際の到達時間を
        `passage_hours`（切り出した区間の順）として渡す。
        """
        bin_count = self._bin_count(duration_hours)
        edge_count = len(self._score_matrix.distance_m)
        # `direction=-1`の`offset_hours`はレグの終了時刻のため、開始時刻へ直す。
        leg_start = offset_hours if direction > 0 else offset_hours - (duration_hours or 0.0)
        if not self.time_varying:
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
        if not self.time_varying:
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
            bin_start_hours=(
                tuple(leg_start + k * TIME_BIN_HOURS for k in range(len(bins)))
                if self.time_varying and passage_hours is None
                else ()
            ),
            passage_hours=passage_hours if self.time_varying else None,
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
        """lazy行順（探索が使う並び）の配列を切り出した区間の順へ戻す。

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

    def _evaluate(self, passage: np.ndarray | None, rows: np.ndarray | None = None) -> _Evaluated:
        """指定した通過時刻（`None`は出発時点のスナップショット）で、軸・材料・所要時間・合成を求める。
        `rows`を渡すとその行だけで求める（`passage`も同じ並び）——探索の合成と同じ式を、経路上の数百行へ
        当て直すために使う。"""
        take = _row_taker(rows)
        bearing = take(self._score_matrix.bearing_deg)
        dynamic_context = DynamicAxisRequestContext(
            bearing_deg=bearing, weather=self._weather,
            travel_speed_ms=kmh_to_ms(self.speed_kmh),
            wind_series=self._wind_series, start=self.start, passage_hours=passage,
            wind_points=None if self._wind_points is None else take(self._wind_points),
        )
        static_scores = (
            self._static_axis_scores if rows is None
            else {axis_id: values[rows] for axis_id, values in self._static_axis_scores.items()}
        )
        resolved = evaluate_dynamic_axis_arrays(static_scores, dynamic_context)
        wind_inputs = dynamic_context.wind_inputs()
        if wind_inputs is None:
            headwind = crosswind = np.zeros(len(bearing))
        else:
            headwind, crosswind = wind_components(*wind_inputs, bearing)
        material_arrays = {
            # 静的材料は静的スコア行列の列をそのまま指すためレグ間で共有する
            # （動的材料と違いレグごとに変わらない）。
            **{material_id: take(values) for material_id, values in self._static_material_arrays.items()},
            **{
                material_id: resolved[material_id]
                for material_id in REQUEST_DYNAMIC_MATERIAL_IDS
                if material_id in resolved and not np.all(np.isnan(resolved[material_id]))
            },
        }
        travel = self._travel_time_seconds(material_arrays, headwind, crosswind, rows)
        # evaluate_dynamic_axis_arraysは内部軸も含めうるため、公開軸のみへ絞って合成する。
        # 合成へ渡すのは時刻で変わる軸だけにし、それ以外は先に求めた重み付き和を使い回す
        # （合成の時間は軸数にほぼ比例する）。表示が読む`axis_arrays`は全軸を持たせる。
        published = {axis_id: resolved[axis_id] for axis_id in self._score_matrix.axis_ids}
        time_varying = {axis_id: resolved[axis_id] for axis_id in self._time_varying_axis_ids}
        fixed_sums, fixed_weights = self._fixed_axis_sums
        composed = compose_costs_from_axis_matrix(
            take(self._score_matrix.distance_m), time_varying, self._weights, self._penalty_strength,
            base=travel, static_sums=(take(fixed_sums), take(fixed_weights)),
        )
        return _Evaluated(published=published, material_arrays=material_arrays, travel=travel, composed=composed)

    def values_at_rows(self, rows: np.ndarray, passage_hours: np.ndarray) -> RowValues:
        """経路上の行`rows`（切り出した区間の順の行番号）だけを、行ごとの通過時刻`passage_hours`で合成し直す。"""
        evaluated = self._evaluate(np.asarray(passage_hours, dtype=float), np.asarray(rows, dtype=np.int64))
        return RowValues(
            rows=np.asarray(rows, dtype=np.int64),
            difficulty_array=evaluated.composed.difficulty,
            axis_arrays=evaluated.published,
            weight_sums=evaluated.composed.weight_sums,
            weights=self._weights,
            material_arrays=evaluated.material_arrays,
        )

    @property
    def distance_m(self) -> np.ndarray:
        """切り出した区間の順の長さ（m）。"""
        return self._score_matrix.distance_m

    @property
    def bearing_deg(self) -> np.ndarray:
        """切り出した区間の順の方位（度、NaN=決まらない）。"""
        return self._score_matrix.bearing_deg

    @property
    def mid_lat(self) -> np.ndarray:
        return self._score_matrix.mid_lat

    @property
    def mid_lon(self) -> np.ndarray:
        return self._score_matrix.mid_lon

    def lazy_row(self, full_row: int) -> int:
        """切り出した区間の順の行番号を、探索が使う行順（`cost_lazy`の並び）へ直す。"""
        return int(self._full_row_index[full_row])

    @property
    def wind_unavailable(self) -> bool:
        """風の予報が無く、所要時間を無風で計算しているか（時別系列も出発時点の値も無い）。"""
        return self._weather is None and self._wind_series is None

    def missing_travel_data_share(self, rows: np.ndarray) -> float | None:
        """切り出した区間の順の行`rows`のうち、所要時間の計算で勾配か停止要因の件数の値が無く、既定（平地・待ち無し）で
        数えた区間の距離の割合。`_travel_time_seconds`が欠けを置き換えるのと同じ列を見る。距離の合計が0ならNone。"""
        distance = self._score_matrix.distance_m[rows]
        total = float(distance.sum())
        if total <= 0:
            return None
        missing = np.isnan(self._score_matrix.gradient_percent[rows])
        for material_id in stop_count_material_ids():
            per_km = self._static_material_arrays.get(material_id)
            if per_km is not None:
                missing |= np.isnan(per_km[rows])
        return round(float(distance[missing].sum()) / total, 4)

    def winds_at(
        self, rows: list[int], passage_hours: list[float | None], beyond_bins: list[bool]
    ) -> list[SegmentWind | None]:
        """区間（切り出した区間の順の行`rows`）ごとの通過時刻（出発からの経過[h]、Noneは出発時点の値を使った区間）で
        引いた風。`beyond_bins`はレグの時刻ビンの範囲の先で、最後のビンをそのまま使った区間。"""
        winds: list[SegmentWind | None] = [None] * len(passage_hours)
        timed = [i for i, passage in enumerate(passage_hours) if passage is not None]
        if self._wind_series is not None and timed:
            timed_hours = np.array([passage_hours[i] for i in timed], dtype=float)
            points = None if self._wind_points is None else self._wind_points[[rows[i] for i in timed]]
            speed, direction = self._wind_series.sample(self.start, timed_hours, points)
            times, clamped = self._wind_series.sampled_times(self.start, timed_hours)
            for j, i in enumerate(timed):
                winds[i] = SegmentWind(
                    speed_ms=round(float(speed[j]), 1),
                    direction_deg=round(float(direction[j]), 1),
                    forecast_at=times[j].isoformat(timespec="minutes"),
                    extended=bool(clamped[j]) or beyond_bins[i],
                )
        if self._weather is not None:
            for i, passage in enumerate(passage_hours):
                if passage is None:
                    winds[i] = SegmentWind(
                        speed_ms=round(self._weather.wind_speed_ms, 1),
                        direction_deg=round(self._weather.wind_direction_deg, 1),
                    )
        return winds

    def _compose_at(self, passage: np.ndarray | None) -> LegCostArrays:
        """指定した通過時刻（`None`は出発時点のスナップショット）で1本ぶん合成する。"""
        evaluated = self._evaluate(passage)
        published, material_arrays, travel, composed = (
            evaluated.published, evaluated.material_arrays, evaluated.travel, evaluated.composed,
        )
        cost_array, difficulty_array = composed.cost, composed.difficulty
        cost_array = np.where(self._hard_filter_excluded, np.inf, cost_array)
        lazy_cost = cost_array[self._lazy_row_index]
        lazy_travel = travel[self._lazy_row_index]
        return LegCostArrays(
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

    # 探索範囲の切り出し。ノードの番号・区間の元の行はこれが決める。
    road: RoadSlice
    weather: WeatherConditions | None
    # 起点のノード番号（`road`の切り出しの番号）。
    origin_node: int
    # 1リクエスト内で繰り返す最寄りNodeの探索（prepareの起点・trace_loopの
    # 各経由地と目的地・preview_segmentの両端）を都度線形探索せず使い回すための索引
    # （domain/routing.py参照）。
    node_index: NodeSpatialIndex
    # 探索用グラフ（区間は番号、domain/routing.py: LazyRoadGraph参照）。
    lazy_graph: LazyRoadGraph
    # レグごとのコスト配列を合成する部品と、合成済みのレグ配列（添字0=往路[起点から離れる
    # レグ]、周回・目的地ルートは1=復路[基準点へ向かうレグ]、経由地ルートはレグ番号順）。
    # `TracedLoop.leg_of_edge`がこの添字を指す。
    composer: _LegCostComposer
    legs: list[LegCostArrays]
    # 周回の復路レグ・目的地ルートの後ろ向き木の基準点に使う起点座標。
    origin: Coordinates
    # A*のヒューリスティック（`_estimate_distances_m`）を、レグごとの目的地に対して
    # numpyで1回だけベクトル計算するための、ノード番号順の緯度・経度配列。
    node_lat: np.ndarray
    node_lon: np.ndarray
    # prepare実行時点で起点が市民薄明の外（夜間）だったかどうか。レグのコスト配列の
    # 構築時に使った値と同じものを_build_segment_details（表示用difficulty）でも使い、探索コストと
    # 表示を一致させる（詳細はprepare()参照）。
    night_active: bool
    # 一対全最短経路木用のCSR構造＋Edge実距離配列（domain/routing.py: SearchGraphStatics参照）。
    statics: SearchGraphStatics
    # 状態＝有向Edge・辺＝ターンの遷移構造（`statics.csr`から導く。起点にもコストにも
    # 依存しないためリクエスト内で共有する）。
    turn_structure: TurnExpandedStructure
    # 探索範囲を覆うタイル集合。学習した迂回率の鍵に使う。
    tile_set: frozenset[tuple[int, int, int]]
    # 復路探索（折返し点→起点）のA*ヒューリスティック配列。目的地が常に起点の
    # ため、リクエストで1回だけ計算し全候補で共有する（初回の復路探索時に遅延構築）。
    origin_estimate: list[float] | None = None
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
    """

    road: RoadSlice
    lazy_graph: LazyRoadGraph
    # bboxを覆うタイル集合（学習した迂回率の鍵）。
    tile_set: frozenset[tuple[int, int, int]]
    weather: WeatherConditions | None
    night_active: bool
    # _RoadGraphContextと同じ意味（フィールドdocstring参照）。`outbound`は基準点（起点側の
    # 座標）から離れていくレグとして合成済みの配列。
    composer: _LegCostComposer
    outbound: LegCostArrays
    node_lat: np.ndarray
    node_lon: np.ndarray
    # 0次フィルタ除外配列（`compute_hard_filter_excluded`、切り出した区間の順。cost_arrayをinfに
    # するのに使ったのと同じ配列）。routable Node判定にこの配列をそのまま使い回す。
    hard_filter_excluded: np.ndarray


@dataclass(frozen=True)
class _TurnaroundData:
    """`LoopTurnaround.data`（本エンジン固有）: 折返し点のノード番号と、一対全木上の往路
    （区間の番号列）。`trace_loop_from_turnaround`が復路探索に使う。"""

    node: int
    outbound_edge_indices: list[int]
    outbound_length_m: float


class RoadGraphEngine:
    def __init__(
        self,
        graph_service: GraphService,
        weather_service: WeatherService,
        route_preference: RoutePreference,
        penalty_strength: float,
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
        # 既定を持たない——省略時の値は呼ぶ側が`resolve_penalty_strength`で較正値から読む。
        self._penalty_strength = penalty_strength
        # 0次ハードフィルタの勾配しきい値（%、既定None＝除外しない）。
        # `domain/hard_filters.py: compute_hard_filter_excluded`参照。
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
        （`prepare`・`preview_segment`共通）。夜間の判定と、風の時別予報が無いときの風（出発時点の値）は
        `wind_and_night_origin`（周回ならその起点、区間確認なら起点側の座標）を基準にする
        ——探索中は到達時刻が未確定のため出発時刻の近似として使う簡略化はどちらの用途でも
        変わらない（モジュールdocstring参照）。時別予報は`bbox`を覆う格子点ごとに引く。

        `GraphService.get_search_slice`が返す`StaticEdgeScoreMatrix`（切り出した区間の静的
        Edge×公開軸スコア行列）に対し、動的軸（風、`evaluate_dynamic_axis_arrays`）と重み
        ベクトルを適用してコスト配列を**bbox全体ぶん1回だけ**numpyで合成する。探索本体へは
        合成済みのnumpy配列をそのまま渡すだけにする。
        """
        stage_started = time.monotonic()
        built = await self._graph_service.get_search_slice(bbox)
        materials_ms = round((time.monotonic() - stage_started) * 1000)
        if built is None:
            return None
        road, score_matrix, tile_set = built
        if road.edge_count == 0:
            return None

        weather_started = time.monotonic()
        weather = await self._weather_service.get_conditions(wind_and_night_origin)
        # 探索範囲を覆う格子点ごとの時別風予報（MSMのローカルファイルから読む。外部API呼び出しは無い）。
        wind_series = await self._weather_service.get_wind_forecast_lattice(bbox)
        weather_ms = round((time.monotonic() - weather_started) * 1000)
        # 通過予定時刻の基準（出発時刻）。時別系列はJSTのローカル時刻のため揃える。
        start = now.astimezone(JST).replace(tzinfo=None)
        # 時間帯依存軸（time_scope="night_only"）の動的化。区間ごとの到達時刻は探索中は未確定の
        # ため（風と同じモジュールdocstringの制約）、出発地点の座標・呼び出し時点を出発時刻の
        # 近似として採用し、起点が市民薄明の外（夜間）ならnight_only軸の重みをそのまま、日中なら
        # 0倍にしたRoutePreferenceのコピーを探索コストへ渡す（self._route_preference自体は
        # 書き換えない、リクエスト間で共有される状態のため）。
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

        graph_started = time.monotonic()
        lazy_graph = await asyncio.to_thread(build_lazy_road_graph, road.edge_from, road.edge_to, road.node_count)
        graph_ms = round((time.monotonic() - graph_started) * 1000)

        # 迂回率は同じ探索範囲で前回の往路木から学習した値があればそれを使う（無ければ既定値）。
        learned_detour_ratio = search_graph_cache.get_detour_ratio(tile_set)
        composer = _LegCostComposer(
            score_matrix, weights, self._penalty_strength, hard_filter_excluded, weather, wind_series,
            start, self._assumed_speed_kmh, lazy_graph.edge_rows,
            detour_ratio=learned_detour_ratio if learned_detour_ratio is not None else ROUTE_DETOUR_RATIO,
            lens_axis_id=self._lens_axis_id,
        )
        outbound = composer.compose("outbound", wind_and_night_origin, 0.0, +1)
        cost_ms = round((time.monotonic() - cost_started) * 1000) - graph_ms
        # 重み付き軸がすべてNaNのEdge比率（探索コストはbbox内平均difficultyで補完される。
        # 実際の発生頻度を把握するためのサマリ）。
        missing_axis_mask = np.isnan(outbound.difficulty_array)
        missing_axis_distance_ratio = float(
            score_matrix.distance_m[missing_axis_mask].sum() / float(score_matrix.distance_m.sum())
        )

        total_ms = round((time.monotonic() - stage_started) * 1000)
        logger.info(
            "_build_search_graph edges=%d nodes=%d materials_ms=%d weather_ms=%d cost_ms=%d graph_ms=%d "
            "total_ms=%d wind_time_varying=%s speed_kmh=%.1f detour_ratio=%.2f(%s) "
            "missing_axis_edges=%d missing_axis_distance_ratio=%.3f",
            road.edge_count, road.node_count, materials_ms, weather_ms, cost_ms, graph_ms, total_ms,
            composer.time_varying, self._assumed_speed_kmh, composer.detour_ratio,
            "learned" if learned_detour_ratio is not None else "default",
            int(missing_axis_mask.sum()), missing_axis_distance_ratio,
        )

        return _SearchGraph(
            road=road,
            lazy_graph=lazy_graph,
            tile_set=tile_set,
            weather=weather,
            night_active=night_active,
            composer=composer,
            outbound=outbound,
            node_lat=road.node_lat,
            node_lon=road.node_lon,
            hard_filter_excluded=hard_filter_excluded,
        )

    async def _build_search_structures(
        self, search: _SearchGraph
    ) -> tuple[NodeSpatialIndex, SearchGraphStatics, TurnExpandedStructure]:
        """最寄りNodeの索引・CSR・ターン構造を組む（`prepare`・`preview_segment`共通）。

        索引の候補は実際に経路探索可能な（Hard Constraint通過後も区間が1本以上残る）Nodeに
        絞る。絞らないと、幹線道路（highway=trunk等）にしか接続していない地理的最近傍Node
        （駅前が国道の交差点に直接面する場所が実例）が選ばれ、そこがHard Constraint除外後の
        グラフ上では孤立点になるため、すべての折返し点・経由地への探索が"no path found"で失敗する。
        """
        started = time.monotonic()
        road = search.road
        routable = compute_routable_nodes(road.edge_from, road.edge_to, search.hard_filter_excluded, road.node_count)
        node_index = await asyncio.to_thread(build_node_spatial_index, search.node_lat, search.node_lon, routable)
        index_ms = round((time.monotonic() - started) * 1000)
        statics = build_search_graph_statics(search.lazy_graph, search.composer.distance_m)
        turn_started = time.monotonic()
        turn_structure = await asyncio.to_thread(self._build_turn_structure, search, statics)
        logger.info(
            "prepare structures edges=%d states=%d transitions=%d index_ms=%d turn_ms=%d",
            road.edge_count, turn_structure.state_count, len(turn_structure.target_state),
            index_ms, round((time.monotonic() - turn_started) * 1000),
        )
        return node_index, statics, turn_structure

    def _build_turn_structure(self, search: _SearchGraph, statics: SearchGraphStatics) -> TurnExpandedStructure:
        """状態＝有向区間の遷移構造。信号の有無・集まる道の最大階級はノードの事前集計列、
        区間の道路階級は`highway`の語彙から引く（`domain/traffic.py: highway_rank`）。"""
        road, lazy_graph = search.road, search.lazy_graph
        network = road.network
        rank_of_code = np.array([highway_rank(highway) for highway in network.highway_vocab], dtype=np.int64)
        edge_rank = rank_of_code[network.edge_highway[road.rows[lazy_graph.edge_rows]]]
        return build_turn_expanded_structure(
            statics.csr, lazy_graph,
            edge_bearings(lazy_graph, search.composer.bearing_deg, search.node_lat, search.node_lon),
            edge_rank, self._turn_cost,
            np.asarray(network.node_has_signals[road.nodes], dtype=bool),
            np.asarray(network.node_max_rank[road.nodes], dtype=np.int64),
        )

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
            # ため、周回探索の円を覆う矩形ではなく、preview_segmentと
            # 同じ「複数点の外接矩形+固定マージン」を使う。
            bbox = bbox_covering_points([origin, *waypoints], PREVIEW_BBOX_MARGIN_KM)
        else:
            # 起点を中心とした円を覆う矩形。折返し点がどの方位に選ばれても、この1回の取得で足りる。
            margin_km = max(BBOX_MARGIN_MIN_KM, radius_km * BBOX_MARGIN_RATIO)
            bbox = bbox_covering_points([origin], radius_km + margin_km)

        search = await self._build_search_graph(bbox, origin, now)
        if search is None:
            return None
        node_index, statics, turn_structure = await self._build_search_structures(search)
        origin_node = find_nearest_node_indexed(node_index, origin)
        if origin_node is None:
            return None

        return _RoadGraphContext(
            road=search.road,
            weather=search.weather,
            origin_node=origin_node,
            node_index=node_index,
            lazy_graph=search.lazy_graph,
            composer=search.composer,
            legs=[search.outbound],
            origin=origin,
            node_lat=search.node_lat,
            node_lon=search.node_lon,
            night_active=search.night_active,
            statics=statics,
            turn_structure=turn_structure,
            tile_set=search.tile_set,
        )

    async def preview_segment(
        self, origin: Coordinates, destination: Coordinates, now: datetime | None = None
    ) -> RouteSegment | None:
        """起点・終点2点間の単発区間確認（`/api/routes/preview`）。

        1回の最短経路探索のみを行う。探索コストは生成と同じ評価軸重み付きを使う——単純
        最短距離にすると、ここで見える経路と生成が返す経路が食い違う。

        経路が見つからない場合はNone。
        """
        now = now or datetime.now(timezone.utc)
        bbox = bbox_covering_points([origin, destination], PREVIEW_BBOX_MARGIN_KM)

        search = await self._build_search_graph(bbox, origin, now)
        if search is None:
            return None
        node_index, statics, turn_structure = await self._build_search_structures(search)
        origin_node = find_nearest_node_indexed(node_index, origin)
        destination_node = find_nearest_node_indexed(node_index, destination)
        if origin_node is None or destination_node is None:
            return None

        edges = await asyncio.to_thread(
            turn_expanded_shortest_path,
            turn_structure, search.outbound.cost_lazy,
            _heuristic_seconds(_estimate_distances_m(search.node_lat, search.node_lon, destination_node)),
            _origin_states(statics, origin_node),
            destination_node,
            search.outbound.travel_seconds_lazy,
        )
        if not edges:
            return None

        # 探索用グラフの区間は形を持たないため、この経路ぶんだけ取り直す。
        # 渡すのはidではなく枝そのもの——取り直しは道と区間の番号で引くため。
        topology = [_lean_edge(search.road, search.lazy_graph, index) for index in edges]
        hydrated = await self._graph_service.get_edges_with_geometry(topology)
        edges_in_path: list[LeanEdge] = [hydrated[edge.edge_id] for edge in topology]

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

        `waypoints`は[起点, 中間経由地..., 終点]。起点は`prepare`がスナップ済みのNodeを
        そのまま使い、中間経由地はここでスナップする。戻り値の`data`は経路上の区間の番号列で、
        実ジオメトリはまだ持たない。
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
            snapped = find_nearest_node_indexed(context.node_index, end_point)
            if snapped is None:
                raise RoutingError(f"direction {bearing}: could not snap destination to road graph")
            end_node = snapped
        node_sequence = [context.origin_node, *interior_nodes, end_node]

        # A*ヒューリスティックはレグごとに目的地が変わるため、レグごとにnumpyで1回だけ
        # 計算し直す。レグ0は`prepare`が合成済みの往路レグそのもの。
        def _trace_segments() -> list[list[int]] | None:
            segment_paths: list[list[int]] = []
            context.legs = context.legs[:1]
            cumulative_m = 0.0
            for leg_index, (from_node, to_node) in enumerate(zip(node_sequence, node_sequence[1:])):
                if leg_index == 0:
                    leg = context.legs[0]
                else:
                    leg = context.composer.compose(
                        f"leg{leg_index}", _node_coordinates(context, from_node),
                        cumulative_m / 1000 / context.composer.speed_kmh, +1,
                    )
                    context.legs.append(leg)
                segment_path = turn_expanded_shortest_path(
                    context.turn_structure, leg.cost_bins_lazy,
                    _heuristic_seconds(_estimate_distances_m(context.node_lat, context.node_lon, to_node)),
                    _origin_states(context.statics, from_node),
                    to_node,
                    leg.travel_bins_lazy, leg.bin_seconds,
                )
                if segment_path is None:
                    return None
                segment_paths.append(segment_path)
                cumulative_m += float(context.statics.edge_length_m[segment_path].sum())
            return segment_paths

        trace_started = time.monotonic()
        segment_paths = _trace_segments()
        trace_wall_ms = round((time.monotonic() - trace_started) * 1000)
        logger.info("trace_loop direction=%s wall_ms=%d", bearing, trace_wall_ms)
        if segment_paths is None:
            raise RoutingError(f"direction {bearing}: no path found between waypoints")

        path = [index for segment in segment_paths for index in segment]
        if not path:
            raise RoutingError(f"direction {bearing}: resulting path has no edges")
        leg_of_edge = [
            leg_index for leg_index, segment_path in enumerate(segment_paths) for _ in segment_path
        ]
        return TracedLoop(bearing=bearing, distance_km=_path_km(context, path), data=path, leg_of_edge=leg_of_edge)

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
           距離フィルタで全滅する）。
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
            _origin_states(statics, context.origin_node), statics.csr.node_count,
            cost_limit=cost_limit, edge_seconds=outbound.travel_bins_lazy,
            bin_seconds=outbound.bin_seconds,
        )
        tree_ms = round((time.monotonic() - tree_started) * 1000)

        length = tree.node_length_m
        in_ring = (length >= ring_lower_m) & (length <= ring_upper_m)
        in_ring[context.origin_node] = False
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
        difficulty = difficulty_from_cost(tree.node_cost[ring], tree.node_seconds[ring], self._penalty_strength)
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
        # 層に入らなかった候補（-1）は難易度順で最後尾へ回す。
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
        origin_node = _node_coordinates(context, context.origin_node)
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

        outbound_cache: dict[int, list[int] | None] = {}

        def outbound_edges(node_index: int) -> list[int] | None:
            if node_index not in outbound_cache:
                outbound_cache[node_index] = turn_expanded_path_edge_indices(tree, node_index)
            return outbound_cache[node_index]

        # 近接判定は、緯度経度を起点基準の平面km座標へ1回だけ変換し（bboxの広さなら等距
        # 円筒近似で足りる）、平方距離をPythonのfloat演算で比べる——候補ごとにnumpyの
        # haversineを呼ぶと、1回あたりの呼び出し費用が候補数ぶん積み上がる。`far_enough`が
        # 引くのは`ranked`のNodeだけなので、座標変換もそのぶんに限る。
        min_separation_sq = MIN_TURNAROUND_SEPARATION_KM ** 2
        lat0 = float(context.node_lat[context.origin_node])
        km_per_deg_lon = km_per_degree_longitude(lat0)
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

        # 閾値を昇順に渡すと、埋まらなかったときの緩和までを1回の呼び出しで行う。
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
            bearing = int(round(bearing_between(origin_node, _node_coordinates(context, node_index)))) % 360
            turnarounds.append(
                LoopTurnaround(
                    bearing=bearing,
                    outbound_difficulty=float(difficulty_by_node[node_index]),
                    data=_TurnaroundData(
                        node=node_index, outbound_edge_indices=edges,
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
           合成コスト最小のNode（"最良路"）の長さの`ALTERNATIVE_MAX_STRETCH`倍以内の
           Nodeだけを候補にする。
        2. 平均difficulty`(合成コスト/経由路長-1)/P`昇順に並べる。ただし最良路のNodeは常に
           先頭へ回す——合成コスト最小であっても、伸び率の許す範囲でより平均difficultyの
           低い経路が他に存在すれば難易度順ではそちらが上位に来うるため、「最良路は必ず
           結果に含まれる」をランキングとは独立に保証する。
        3. `select_diverse_by_overlap`で、前向き経路・後ろ向き経路が同じEdgeを共有する
           Node（行って戻る形になり経路として成立しない）を除外しつつ、採用済み候補との
           重複率が閾値超のものを飛ばして`max_routes`件採る。

        目的地に一番近いNodeが、メインの道路網から孤立した小さな塊
        （歩道橋・私有地内通路等、次数1以上ではあるが起点からは実質到達できない場所）に
        スナップされていると、後ろ向き木が起点側とほぼ重ならず毎回0件になる。前向き木で
        実際に届くかをここで確認し、届かなければ「前向き木が届くNode」だけに絞って
        最寄りへ再スナップする（`context.destination_correction`に実際の座標を残す）。
        """
        destination_index = find_nearest_node_indexed(context.node_index, destination)
        if destination_index is None:
            logger.warning("select_via_nodes destination_node=None (not snapped to routable graph)")
            return []

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
            _origin_states(context.statics, context.origin_node), context.statics.csr.node_count,
            edge_seconds=outbound.travel_bins_lazy, bin_seconds=outbound.bin_seconds,
        )

        if not np.isfinite(forward_tree.node_cost[destination_index]):
            corrected_node = find_nearest_node_indexed(
                context.node_index, destination,
                allowed=np.isfinite(forward_tree.node_cost),
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
                        _node_key_of(context.road, context.origin_node),
                        int(_origin_states(context.statics, context.origin_node).size),
                        finite_cost_ratio,
                        int(forward_tree.node_cost.size),
                    )
                else:
                    context.no_candidates_side = "destination"
                    logger.warning(
                        "select_via_nodes no accessible node near destination destination_node=%s "
                        "reached_nodes=%d/%d",
                        _node_key_of(context.road, destination_index), reached_nodes,
                        int(forward_tree.node_cost.size),
                    )
                return []
            destination_index = corrected_node
            destination = _node_coordinates(context, destination_index)
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
            context.composer.mid_lat, context.composer.mid_lon,
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
            # 前向き木・後ろ向き木のどちらがどれだけ到達できているかを内訳として出す
            # （前向きのみ0なら起点側、後ろ向きのみ0なら目的地側の孤立を疑える）。
            logger.warning(
                "select_via_nodes reachable=0 forward_reached=%d backward_reached=%d "
                "destination_reached_by_forward=%s origin_reached_by_backward=%s tree_ms=%d",
                int(np.isfinite(forward_tree.node_cost).sum()), int(np.isfinite(backward_tree.node_cost).sum()),
                bool(np.isfinite(forward_tree.node_cost[destination_index])),
                bool(np.isfinite(backward_tree.node_cost[context.origin_node])),
                tree_ms,
            )
            return []

        best_index = int(np.argmin(np.where(reachable, combined_cost, np.inf)))
        best_length_m = float(combined_length[best_index])
        within_stretch = reachable & (combined_length <= best_length_m * ALTERNATIVE_MAX_STRETCH)
        # 打ち切りは**並べてから**行う（周回の折返し点選定と同じ規則）。Node index順で先に
        # 切ると、良い候補が後ろのindexに居るだけで検討対象から外れる。
        candidates = np.flatnonzero(within_stretch)

        difficulty = difficulty_from_cost(combined_cost[candidates], combined_seconds[candidates], self._penalty_strength)
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
                if forward_edges is None:
                    full_edges_cache[node_index] = None
                else:
                    # 行って戻る形（前向き・後ろ向きが同じ物理区間を通る）の判定は、
                    # is_loop_too_similarと同じ進行方向を無視した物理区間キーで行う——
                    # 同じ道でも逆方向Edge（別のedge_id/index）を通れば単純なEdge index
                    # 集合の比較では検出できないため。
                    forward_segments = _loop_edge_lengths_by_physical_segment(context, forward_edges)
                    backward_segments = _loop_edge_lengths_by_physical_segment(context, backward_edges)
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
            forward_count = forward_edge_count[node_index]
            leg_of_edge = [0] * forward_count + [1] * (len(edges) - forward_count)
            traced.append(TracedLoop(
                bearing=None, distance_km=_path_km(context, edges), data=edges, leg_of_edge=leg_of_edge))

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

        **軸の重みは使わないが、0次フィルタは使う**——あれは好みではなく通行可否・走行可否の
        表明で、所要時間を優先する経路でも越えてよいものではない。除外Edgeの所要時間を
        `inf`にすることで表現する。

        `select_via_nodes`の後に呼ぶこと。目的地の再スナップ結果を引き継ぐ。

        レグは経路の所要時間が半分になる位置で割る——他の候補と同じく往路・復路へ概ね
        半分ずつ割れ、レグごとに時刻の異なる風の評価が候補間で揃う。
        """
        destination = context.destination_correction or destination
        destination_index = find_nearest_node_indexed(context.node_index, destination)
        if destination_index is None:
            return None

        started = time.monotonic()
        outbound = context.legs[0]
        time_bins = outbound.travel_bins_lazy
        edges = await asyncio.to_thread(
            turn_expanded_shortest_path,
            context.turn_structure, time_bins,
            _heuristic_seconds(_estimate_distances_m(context.node_lat, context.node_lon, destination_index)),
            _origin_states(context.statics, context.origin_node), destination_index,
            time_bins, outbound.bin_seconds,
        )
        if not edges:
            logger.warning("select_fastest_route no path to destination=%s", _node_key_of(context.road, destination_index))
            return None

        seconds = [float(outbound.travel_seconds_lazy[index]) for index in edges]
        half_seconds = sum(seconds) / 2
        # 走行時間は必ず有限（`speed_ms`が押して歩く速度を下限に置く）ため、累積が半分を
        # 越える位置が必ずある。
        split = next(
            position
            for position, total in enumerate(itertools.accumulate(seconds), 1)
            if total >= half_seconds
        )
        forward_edges = edges[:split]
        backward_edges = edges[split:]
        path = forward_edges + backward_edges
        distance_km = _path_km(context, path)
        leg_of_edge = [0] * len(forward_edges) + [1] * len(backward_edges)

        logger.info(
            "select_fastest_route fastest_km=%.1f edges=%d forward_edges=%d elapsed_ms=%d",
            distance_km, len(path), len(forward_edges), round((time.monotonic() - started) * 1000),
        )
        return TracedLoop(bearing=None, distance_km=distance_km, data=path, leg_of_edge=leg_of_edge)

    async def trace_loop_from_turnaround(self, context: _RoadGraphContext, turnaround: LoopTurnaround) -> TracedLoop:
        """往路（一対全木上の経路、`select_loop_turnarounds`で確定済み）に、往路と別の
        復路（折返し点→起点のA*）を継いで周回にする。

        復路探索の間だけ、往路Edge＋同一Node対の逆方向Edgeのコストを
        `RETRACE_PENALTY_MULTIPLIER`倍へ**差し替え**、探索後に元へ戻す。配列ごとコピーすると
        候補の数だけbbox全体ぶんの複製を払うため、触るのは往路Edgeの列だけにする。時刻ビンを
        張った復路では全ビンの同じ列をまとめて差し替える——どの時刻に通っても「往路をなぞる」
        ことに変わりはない。

        **差し替えはawaitを挟まない同期区間で完結させること。** 共有のコスト配列を書き換える
        ため、この間に他のコルーチンへ制御が渡ると別の候補が書き換え後の値を見る。

        倍率は有限のため、復路が往路を戻る以外に道が無い区間（袋小路・起点付近の単一の道）は
        そのまま通れる。
        """
        data: _TurnaroundData = turnaround.data
        lazy_graph = context.lazy_graph
        # 復路レグのコスト配列（select_loop_turnaroundsが合成済み。無ければ往路と共有）。
        inbound_leg = context.legs[1] if len(context.legs) > 1 else context.legs[0]
        cost_bins = inbound_leg.cost_bins_lazy

        penalized: set[int] = set(data.outbound_edge_indices)
        for edge_index in data.outbound_edge_indices:
            reverse_index = edge_index_between(
                context.statics.csr, int(lazy_graph.edge_to[edge_index]), int(lazy_graph.edge_from[edge_index])
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
                _origin_states(context.statics, data.node),
                context.origin_node,
                inbound_leg.travel_bins_lazy, inbound_leg.bin_seconds,
            )
        finally:
            cost_bins[:, penalized_columns] = original
        trace_wall_ms = round((time.monotonic() - trace_started) * 1000)
        if return_edge_index_list is None:
            raise RoutingError(f"turnaround bearing={turnaround.bearing}: no return path found")

        if not return_edge_index_list:
            raise RoutingError(f"turnaround bearing={turnaround.bearing}: return path has no edges")
        return_edge_indices = np.array(return_edge_index_list, dtype=np.int64)
        retrace = overlap_ratio(return_edge_indices, np.fromiter(penalized, dtype=np.int64), context.statics.edge_length_m)
        path = [*data.outbound_edge_indices, *return_edge_index_list]
        leg_of_edge = [0] * len(data.outbound_edge_indices) + [1] * len(return_edge_index_list)
        distance_km = _path_km(context, path)
        logger.debug(
            "trace_loop_from_turnaround bearing=%d outbound_km=%.1f loop_km=%.1f retrace_ratio=%.2f wall_ms=%d",
            turnaround.bearing, data.outbound_length_m / 1000, distance_km, retrace, trace_wall_ms,
        )
        return TracedLoop(bearing=turnaround.bearing, distance_km=distance_km, data=path, leg_of_edge=leg_of_edge)

    def build_traced_from_edge_ids(
        self, context: _RoadGraphContext, edge_ids: list[str], destination: Coordinates | None = None,
    ) -> TracedLoop:
        """クライアントが組み立てたEdge id列を、評価できる経路として検証して`TracedLoop`にする。

        区間の乗り換えで使う。フロントは候補の`edge_ids`から
        「Aの前半＋Bの後半」を作って送り返すため、**このグラフに実在し・順につながり・
        起点から始まり・目的地へ着く**ことをここで確かめる（送られた列をそのまま信じると、
        評価は成功するのに経路として成立しないルートが候補一覧へ並ぶ）。

        終点は`destination`を渡したときだけ見る。起点と同じ`find_nearest_node_indexed`で
        解くため、比べる相手は元の候補が実際に終わったNodeになる——目的地がメインの
        道路網から孤立していて補正した場合も、補正後の地点が条件として返っており、合成も
        その地点で送られてくる。

        レグはこの経路自身の距離の半分で切る。合成経路はvia-nodeを持たないため前向き木・
        後ろ向き木の境目が無く、レグが表す「走り始めの時刻帯／走り終わりの時刻帯」の
        近似が入れ替わる点として中間を採る。**レグ番号を振る側が、その番号のレグを
        `context.legs`へ用意する**——`prepare`が作るのは往路レグだけで、復路レグは探索
        （折返し点の選定・経由Nodeの選定）が作る。合成経路はどちらの探索も通らない。
        """
        if not edge_ids:
            raise RoutingError("経路が空です")
        resolved = [_lazy_index_of(context, edge_id) for edge_id in edge_ids]
        unknown = [edge_id for edge_id, index in zip(edge_ids, resolved, strict=True) if index is None]
        if unknown:
            raise RoutingError(
                f"経路に未知のEdgeが含まれています count={len(unknown)} first={unknown[0]}"
            )
        path = [index for index in resolved if index is not None]
        lazy_graph = context.lazy_graph
        tails = [int(lazy_graph.edge_from[index]) for index in path]
        heads = [int(lazy_graph.edge_to[index]) for index in path]
        if tails[0] != context.origin_node:
            raise RoutingError(
                f"経路が起点から始まっていません expected={_node_key_of(context.road, context.origin_node)} "
                f"actual={_node_key_of(context.road, tails[0])}"
            )
        for index, (head, following_tail) in enumerate(zip(heads, tails[1:])):
            if head != following_tail:
                raise RoutingError(
                    f"経路がつながっていません index={index} to_node={_node_key_of(context.road, head)} "
                    f"next_from_node={_node_key_of(context.road, following_tail)}"
                )
        if destination is not None:
            destination_node = find_nearest_node_indexed(context.node_index, destination)
            if destination_node is not None and heads[-1] != destination_node:
                raise RoutingError(
                    f"経路が目的地に着いていません expected={_node_key_of(context.road, destination_node)} "
                    f"actual={_node_key_of(context.road, heads[-1])}"
                )

        lengths = context.statics.edge_length_m[path].tolist()
        total_m = sum(lengths)
        leg_of_edge, travelled_m = [], 0.0
        for length in lengths:
            leg_of_edge.append(0 if travelled_m < total_m / 2 else 1)
            travelled_m += length
        if max(leg_of_edge) > 0 and len(context.legs) < 2:
            total_hours = total_m / 1000 / context.composer.speed_kmh
            context.legs = [
                context.legs[0],
                context.composer.compose(
                    "inbound", context.origin, total_hours, -1, duration_hours=total_hours / 2
                ),
            ]
        return TracedLoop(
            bearing=None, distance_km=round(total_m / 1000, 2), data=path, leg_of_edge=leg_of_edge
        )

    def is_loop_too_similar(
        self, context: _RoadGraphContext, candidate: TracedLoop, accepted: list[TracedLoop]
    ) -> bool:
        """`candidate`が`accepted`のいずれかと、周回全体（往路＋復路）で
        `LOOP_MAX_OVERLAP_RATIO`を超えて重複するか。進行方向を無視して
        比較するため、「同じ周回の逆回り」（往路と復路が入れ替わっただけ）や「往路は違うが
        復路が同じ裏道へ収束する」周回のどちらも同じ判定で弾ける。`TracedLoop.data`は
        区間の番号列（往路＋復路、`trace_loop_from_turnaround`/`trace_loop`参照）。
        """
        candidate_lengths = _loop_edge_lengths_by_physical_segment(context, candidate.data)
        if not candidate_lengths:
            return False
        total = sum(candidate_lengths.values())
        if total <= 0:
            return False
        for other in accepted:
            other_keys = _loop_edge_lengths_by_physical_segment(context, other.data)
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
        # 実ジオメトリは距離フィルタを通った候補ぶんだけを、全候補まとめて1回で取り直す
        # （棄却済み候補ぶんは問い合わせない）。引けない区間があれば落とす——探索が通った
        # 区間の実体がDBに無いということで、線の欠けた経路を配るより落ちる方がよい。
        topology = {
            index: _lean_edge(context.road, context.lazy_graph, index)
            for index in dict.fromkeys(index for t in traced for index in t.data)
        }
        hydrated = await self._graph_service.get_edges_with_geometry(list(topology.values()))
        edges_by_candidate: list[list[LeanEdge]] = [
            [hydrated[topology[index].edge_id] for index in t.data] for t in traced
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
        self, context: _RoadGraphContext, traced: TracedLoop, edges_in_path: list[LeanEdge], start_time: datetime
    ) -> RouteCandidate:
        """1候補ぶんの周回を組み立てる。

        同じ周回の逆回りは追加のI/Oなしで合成できるため、合成して**難易度の小さい方だけ**を
        残す（両方向を別候補として並べない）。逆走は勾配・風で評点が変わるため常に意味がある。
        一方通行Edgeが1つでもあれば成立しないので、その場合は順方向のみ。

        経由地ルート（`bearing`がNone）は訪問順序そのものが要件のため、逆回りを作らない。
        """
        path: list[int] = traced.data
        elevation_by_edge = self._elevation_by_edge(context, edges_in_path, path)
        leg_of_edge = traced.leg_of_edge
        forward_candidate = self._build_candidate(
            context, traced, edges_in_path, path, elevation_by_edge, start_time, leg_of_edge
        )

        if traced.bearing is None:
            return forward_candidate

        reversed_path = _reverse_traced_edges(edges_in_path, path, context)
        if reversed_path is None:
            return forward_candidate
        reverse_edges, reverse_path = reversed_path
        reverse_elevation_by_edge = _reverse_elevation_by_edge(
            edges_in_path, reverse_edges, elevation_by_edge
        )
        reverse_candidate = self._build_candidate(
            context, traced, reverse_edges, reverse_path, reverse_elevation_by_edge, start_time,
            _reverse_leg_assignment(leg_of_edge),
        )
        return _pick_better_candidate(forward_candidate, reverse_candidate)

    def _elevation_by_edge(
        self, context: "_RoadGraphContext", edges_in_path: list[LeanEdge], path: list[int]
    ) -> dict[str, ElevationAttribute]:
        """経路の区間ぶんの標高属性。探索フェーズで読んだ材料がそのまま持っている。

        取り込んだ範囲の全区間ぶんを派生バッチが埋めるため、ここで外部へ取りに行く経路は
        無い（欠けているのは標高タイルが覆っていない区間だけで、そこは値なしのまま）。
        """
        found = {}
        for edge, index in zip(edges_in_path, path, strict=True):
            attribute = elevation_attribute(context.road.network, _network_row(context, index), edge.edge_id)
            if attribute is not None:
                found[edge.edge_id] = attribute
        return found

    def _build_candidate(
        self,
        context: _RoadGraphContext,
        traced: TracedLoop,
        edges_in_path: list[LeanEdge],
        path: list[int],
        elevation_by_edge: dict[str, ElevationAttribute],
        start_time: datetime,
        leg_of_edge: list[int],
    ) -> RouteCandidate:
        # 区間と標高属性を引数で受けるのは、逆回り候補も同じ組み立てを通すため。
        # distance_km・bearingは同じ物理経路なので順方向の`traced`のものをそのまま使う。
        geometry, edge_point_offsets = _concat_edge_geometries(edges_in_path)
        elevation_stats = _aggregate_elevation(edges_in_path, elevation_by_edge)
        segments, segment_categories = self._build_segment_details(
            edges_in_path, path, elevation_by_edge, context, start_time, leg_of_edge
        )
        rows = np.asarray([_slice_row(context, index) for index in path], dtype=np.int64)
        # categorical材料の延長割合は**集約より前に**Edge単位の値から畳む。集約後に
        # 計算すると、ビンの代表値を1つ選ぶ形になり割合がビンの粒度へ量子化される。
        material_category_shares = merge_material_category_shares(
            zip((segment.distance_km for segment in segments), segment_categories)
        )
        # 返すsegmentsは集約する。Edge単位のままだとペイロードとフロントの描画費用が嵩む。
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
            estimated_duration_seconds=self._estimate_duration_seconds(context, edges_in_path, path, leg_of_edge),
            wind_unavailable=context.composer.wind_unavailable,
            missing_travel_data_share=context.composer.missing_travel_data_share(rows) if len(rows) else None,
            **elevation_stats,
        )

    def _estimate_duration_seconds(
        self, context: _RoadGraphContext, edges: list[LeanEdge], path: list[int], leg_of_edge: list[int]
    ) -> float | None:
        """候補の所要時間（秒）＝ 区間の走行時間 ＋ 停止の待ち ＋ ターンの待ち。経路を探索と同じ規則で
        たどった時刻（`_route_passages`）の終わりで、区間の到達予想と同じ時計を使う。"""
        if not edges:
            return None
        last = self._route_passages(context, edges, path, leg_of_edge)[-1]
        return last.elapsed_seconds + last.seconds

    def _route_passages(
        self, context: _RoadGraphContext, edges: list[LeanEdge], path: list[int], leg_of_edge: list[int]
    ) -> list[_EdgePassage]:
        """経路を探索と同じ規則でたどり、区間ごとに時刻ビンと出発からの秒を決める。

        探索（`domain/routing.py`の前向きDijkstra・A*）はレグの中の経過時間でビンを選ぶ: レグの最初の区間は
        ビン0、次の区間は前の区間を抜けた時点（曲がる待ちを足す前）の経過時間のビン。区間ごとの秒は、探索の
        コストの下地になっている配列（`LegCostArrays.travel_bins_lazy`、走行モデル＋停止の待ち）を
        そのビンで読む——表示の時刻と探索の時刻を別々に計算すると、片方だけ直したときに静かに食い違う。
        出発からの秒は、レグをまたいで走行と曲がる待ち（`TurnExpandedStructure`）を積む。

        走行時間が有限でない区間は巡航速度で走ったものとして数える——0にすると所要時間が
        実態より短く出る。
        """
        fallback_ms = kmh_to_ms(context.composer.speed_kmh)
        waits = self._turn_waits_along(context, path)
        passages: list[_EdgePassage] = []
        elapsed = 0.0
        leg_elapsed = 0.0
        previous_leg: int | None = None
        for i, (edge, index, leg_index) in enumerate(zip(edges, path, leg_of_edge)):
            leg = context.legs[leg_index]
            if leg_index != previous_leg:
                leg_elapsed = 0.0
                previous_leg = leg_index
            bin_count = leg.travel_bins_lazy.shape[0]
            time_bin = time_bin_of(leg_elapsed, leg.bin_seconds, bin_count)
            seconds = float(
                leg.travel_seconds_full[_slice_row(context, index)] if bin_count == 1
                else leg.travel_bins_lazy[time_bin, index]
            )
            if not np.isfinite(seconds):
                seconds = edge.distance_m / fallback_ms
            passages.append(_EdgePassage(
                time_bin=time_bin, elapsed_seconds=elapsed, seconds=seconds,
                beyond_bins=bin_count > 1 and leg_elapsed >= bin_count * leg.bin_seconds,
            ))
            wait = waits[i] if i < len(waits) else 0.0
            leg_elapsed += seconds + (wait if i + 1 < len(edges) and leg_of_edge[i + 1] == leg_index else 0.0)
            elapsed += seconds + wait
        return passages

    def _turn_waits_along(self, context: _RoadGraphContext, path: list[int]) -> list[float]:
        """経路に沿った遷移ごとのターンの待ち（秒、区間の数−1個）。遷移は`TurnExpandedStructure`から引く。
        区間の番号がそのまま探索の状態。"""
        structure = context.turn_structure
        states = path
        waits: list[float] = []
        for previous, following in zip(states, states[1:]):
            wait = 0.0
            for entry in range(structure.indptr[previous], structure.indptr[previous + 1]):
                if structure.target_state[entry] == following:
                    wait = float(structure.turn_seconds[entry])
                    break
            waits.append(wait)
        return waits

    def _build_segment_details(
        self,
        edges: list[LeanEdge],
        path: list[int],
        elevation_by_edge: dict,
        context: _RoadGraphContext,
        start_time: datetime,
        leg_of_edge: list[int],
    ) -> tuple[list[RouteSegmentDetail], list[dict[str, str]]]:
        """区間ごとの表示値と、区間ごとのcategorical材料の値（材料id→値）を組み立てる。
        後者は平均できず区間の器（ビンへ畳まれる）に載せられないため、候補全体の延長割合へ
        畳む`_build_candidate`へ並びのまま渡す。

        軸別スコア・合成difficulty・寄与度・材料値は、
        そのEdgeが探索されたレグ（`leg_of_edge`）の合成済み配列（`context.legs`、
        区間の番号から行を引く）からそのまま読み、探索コストと表示を一致させる
        （二重計算を持たない）。到達予想時刻は経路を探索と同じ規則でたどった時刻（`_route_passages`）。
        """
        segments = []
        segment_categories: list[dict[str, str]] = []
        cumulative_km = 0.0
        active_material_ids = displayed_material_ids(context.composer._weights, context.composer._lens_axis_id)
        passages = self._route_passages(context, edges, path, leg_of_edge)
        rows = [_slice_row(context, index) for index in path]
        timed = _values_at_passages(context, rows, leg_of_edge, passages)
        winds = context.composer.winds_at(
            rows,
            [_passage_hours_of(context, row, leg_index, passage)
             for row, leg_index, passage in zip(rows, leg_of_edge, passages)],
            [passage.beyond_bins for passage in passages],
        )

        for index, (edge, row, leg_index) in enumerate(zip(edges, rows, leg_of_edge)):
            leg = context.legs[leg_index]
            # 時刻で変わる値（難易度・軸・材料）は、探索がこの区間に使ったビンの値。ビンが1本のレグはレグの配列、
            # 2本以上のレグは経路上の行だけをそのビンの時刻で合成し直した値（`LegCostArrays.bin_start_hours`参照）。
            values, value_row = timed.get(index, (leg, row))
            distance_km = edge.distance_m / 1000
            elevation_attr = elevation_by_edge.get(edge.edge_id)

            gradient_percent = elevation_attr.average_grade if elevation_attr else None
            # 勾配だけは`leg.material_arrays`ではなくこのループが持つ値から載せる
            # （標高属性として既に引いてあり、改めて計算する必要が無いため）。
            static_material_values = (
                {GRADIENT_PERCENT: round(gradient_percent, 1)}
                if GRADIENT_PERCENT in active_material_ids and gradient_percent is not None
                else {}
            )

            axis_scores = {
                axis_id: float(arr[value_row])
                for axis_id, arr in values.axis_arrays.items()
                if not math.isnan(arr[value_row])
            }
            axis_contributions = values.axis_contributions_at(value_row)
            # 折れ点を通す前の生値。静的スコア行列が持つ列をそのまま読む
            # （動的材料を参照する軸は行列側で除外済み）。
            axis_raw_values = {
                axis_id: float(arr[row])
                for axis_id, arr in leg.axis_raw_arrays.items()
                if not math.isnan(arr[row])
            }
            difficulty_value = values.difficulty_array[value_row]
            composite_difficulty_value = None if math.isnan(difficulty_value) else float(difficulty_value)
            material_values = {
                **static_material_values,
                **{
                    material_id: value
                    for material_id in active_material_ids
                    if (value := _material_value_at(values, material_id, value_row)) is not None
                },
            }
            segment_categories.append({
                material_id: str(raw)
                for material_id, array in leg.categorical_material_arrays.items()
                if material_id in active_material_ids and (raw := array[row]) is not None
            })

            arrival_time = start_time + timedelta(seconds=passages[index].elapsed_seconds)

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
                    axis_difficulties=axis_scores,
                    axis_raw_values=axis_raw_values,
                    axis_contributions=axis_contributions,
                    material_values=material_values,
                    difficulty=composite_difficulty_value,
                    wind=winds[index],
                )
            )
            cumulative_km += distance_km

        return segments, segment_categories


def _values_at_passages(
    context: _RoadGraphContext, rows: list[int], leg_of_edge: list[int], passages: list[_EdgePassage]
) -> dict[int, tuple[RowValues, int]]:
    """ビンが2本以上あるレグの区間を、探索が使ったビンの時刻で合成し直す（区間の添字→（値, 値の中の位置））。
    同じレグ・同じビンの区間はまとめて1回で合成する。"""
    groups: dict[tuple[int, int], list[int]] = {}
    for index, (leg_index, passage) in enumerate(zip(leg_of_edge, passages)):
        if len(context.legs[leg_index].bin_start_hours) > 1:
            groups.setdefault((leg_index, passage.time_bin), []).append(index)
    timed: dict[int, tuple[RowValues, int]] = {}
    for (leg_index, time_bin), indices in groups.items():
        group_rows = np.array([rows[i] for i in indices], dtype=np.int64)
        hours = np.full(len(group_rows), context.legs[leg_index].bin_start_hours[time_bin])
        values = context.composer.values_at_rows(group_rows, hours)
        for position, index in enumerate(indices):
            timed[index] = (values, position)
    return timed


def _passage_hours_of(context: _RoadGraphContext, row: int, leg_index: int, passage: _EdgePassage) -> float | None:
    """その区間の評価に使った通過時刻（出発からの経過[h]）。出発時点の値で合成したレグはNone。"""
    leg = context.legs[leg_index]
    if leg.bin_start_hours:
        return leg.bin_start_hours[passage.time_bin]
    if leg.passage_hours is not None:
        return float(leg.passage_hours[row])
    return None


def _material_value_at(leg: LegCostArrays | RowValues, material_id: str, row: int) -> float | None:
    """レグの合成に使った材料配列から1行を読む（材料データ無し・欠損はNone）。"""
    array = leg.material_arrays.get(material_id)
    if array is None:
        return None
    value = float(array[row])
    return None if math.isnan(value) else value


def _slice_row(context: _RoadGraphContext, index: int) -> int:
    """区間の番号→切り出した区間の行（材料・スコア行列・表示用配列の行）。"""
    return int(context.lazy_graph.edge_rows[index])


def _network_row(context: _RoadGraphContext, index: int) -> int:
    """区間の番号→道路網全体の区間の行。"""
    return int(context.road.rows[context.lazy_graph.edge_rows[index]])


def _node_key_of(road: RoadSlice, node: int) -> str:
    return node_key(int(road.network.node_osm_id[road.nodes[node]]))


def _node_coordinates(context: _RoadGraphContext, node: int) -> Coordinates:
    return Coordinates(latitude=float(context.node_lat[node]), longitude=float(context.node_lon[node]))


def _path_km(context: _RoadGraphContext, path: list[int]) -> float:
    return round(float(context.statics.edge_length_m[path].sum()) / 1000, 2)


def _lean_edge(road: RoadSlice, lazy_graph: LazyRoadGraph, index: int) -> LeanEdge:
    """区間の番号から、形を持たない`LeanEdge`（区間の文字列の鍵・両端のノードの鍵付き）を作る。"""
    network = road.network
    row = int(road.rows[lazy_graph.edge_rows[index]])
    bearing = float(network.bearing_deg[row])
    return LeanEdge(
        edge_id=edge_key(int(network.edge_way_id[row]), int(network.edge_segment[row]), bool(network.edge_forward[row])),
        from_node_id=_node_key_of(road, int(lazy_graph.edge_from[index])),
        to_node_id=_node_key_of(road, int(lazy_graph.edge_to[index])),
        geometry=[],
        distance_m=float(network.distance_m[row]),
        osm_way_id=int(network.edge_way_id[row]),
        segment_index=int(network.edge_segment[row]),
        forward=bool(network.edge_forward[row]),
        highway=network.highway_vocab[int(network.edge_highway[row])],
        bearing_deg=None if math.isnan(bearing) else bearing,
    )


def _lazy_index_of(context: _RoadGraphContext, edge_id: str) -> int | None:
    """区間の文字列の鍵→区間の番号。この探索範囲に無い・探索用グラフに載らない（並行区間の
    採られなかった側）区間はNone。"""
    parsed = parse_edge_key(edge_id)
    if parsed is None:
        return None
    network_row = edge_row_of(context.road.network, *parsed)
    if network_row is None:
        return None
    rows = context.road.rows
    position = int(np.searchsorted(rows, network_row))
    if position >= len(rows) or rows[position] != network_row:
        return None
    index = context.composer.lazy_row(position)
    return index if index >= 0 else None


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
    """起点から`node_indices`（ノード番号）への道なり距離`length_m`と直線距離の
    比の中央値を返す。対象が無い・直線距離0のみならNaN。"""
    if len(node_indices) == 0:
        return float("nan")
    origin_coordinates = _node_coordinates(context, context.origin_node)
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
    search_graph_cache.set_detour_ratio(context.tile_set, measured)
    return measured


def _estimate_distances_m(node_lat: np.ndarray, node_lon: np.ndarray, target_node: int) -> list[float]:
    """全Node（`node_lat`/`node_lon`と同じ行順）からノード`target_node`への直線距離（m）を
    numpyで1回だけベクトル計算する。2点間探索のA*ヒューリスティック
    （`_heuristic_seconds`が秒へ直す）の素材になる。
    """
    target = Coordinates(latitude=float(node_lat[target_node]), longitude=float(node_lon[target_node]))
    return (haversine_distance_km_array(node_lat, node_lon, target) * 1000).tolist()


def _heuristic_seconds(straight_m: np.ndarray | list[float]) -> np.ndarray:
    """Nodeごとの直線距離（m）を、所要時間の下界（秒）へ直す。

    実経路は直線より長く、実際の速度は下りの上限以下のため、これは真の
    所要時間を上回らない＝A*のヒューリスティックとして使える（admissible）。主観的割増は
    1以上の倍率のため、割増を含むコストに対しても下界であり続ける。
    """
    return np.asarray(straight_m, dtype=float) / kmh_to_ms(tuning_value("speed.max_descent_kmh"))


def _origin_estimate(context: _RoadGraphContext) -> list[float]:
    """復路探索（目的地＝起点）のA*ヒューリスティック。起点は1リクエストで固定のため
    初回だけ`_estimate_distances_m`で計算し、以降の候補はcontextに保持した配列を共有する。
    """
    if context.origin_estimate is None:
        context.origin_estimate = _estimate_distances_m(context.node_lat, context.node_lon, context.origin_node)
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
    context: _RoadGraphContext, path: list[int]
) -> dict[frozenset[int], float]:
    """周回1件ぶんの区間の番号列（`TracedLoop.data`）を、進行方向を無視した物理区間キー
    （両端のノード番号のfrozenset）→距離(m)の辞書へ変換する（`is_loop_too_similar`が使う）。
    同じ物理区間を指す順・逆の区間を同一キーへ正規化することで、「同じ周回の逆回り」の比較を
    可能にする。
    """
    # 同じ物理区間を2回通る周回は1回ぶんとして数える（加算しない）。重複率の分母が実際の
    # 周回長より短くなるぶん似ていると判定されやすくなるが、似た周回を並べるより棄却する
    # 側へ倒す。
    lazy_graph = context.lazy_graph
    lengths = context.statics.edge_length_m
    result: dict[frozenset[int], float] = {}
    for index in path:
        result[frozenset({int(lazy_graph.edge_from[index]), int(lazy_graph.edge_to[index])})] = float(lengths[index])
    return result


def _reverse_traced_edges(
    edges_in_path: list[LeanEdge], path: list[int], context: _RoadGraphContext
) -> tuple[list[LeanEdge], list[int]] | None:
    """順方向の経路（起点→...→起点）を逆順に辿った場合の、対応する逆方向の区間の列と
    その番号列を構築する。経路中に一方通行（逆方向の区間が存在しない）区間が1つでもあれば
    物理的に逆走不可能なため`None`を返す。

    `geometry`だけは逆方向の区間自身（形を持たない）からではなく、順方向で取得済みの
    ものを反転して使う——同じ物理区間を逆順に辿るだけなので、取り直す必要が無い。
    進行方向に依存しない値も**逆方向の区間自身から**引く。
    """
    lazy_graph = context.lazy_graph
    reverse_edges: list[LeanEdge] = []
    reverse_path: list[int] = []
    for edge, index in zip(reversed(edges_in_path), reversed(path), strict=True):
        reverse_index = edge_index_between(
            context.statics.csr, int(lazy_graph.edge_to[index]), int(lazy_graph.edge_from[index])
        )
        if reverse_index is None:
            return None
        topology = _lean_edge(context.road, lazy_graph, reverse_index)
        reverse_edges.append(
            LeanEdge(
                edge_id=topology.edge_id,
                from_node_id=topology.from_node_id,
                to_node_id=topology.to_node_id,
                geometry=list(reversed(edge.geometry)),
                distance_m=topology.distance_m,
                osm_way_id=topology.osm_way_id,
                segment_index=topology.segment_index,
                forward=topology.forward,
                highway=topology.highway,
                bearing_deg=topology.bearing_deg,
            )
        )
        reverse_path.append(reverse_index)
    return reverse_edges, reverse_path


def _reverse_elevation_attribute(forward: ElevationAttribute, reverse_edge_id: str) -> ElevationAttribute:
    """順方向のElevationAttributeから、同じ物理的な地形を逆方向に走った場合の値を
    代数的に導出する。標高は地形の物理量で進行方向に依存しないため、
    この変換は厳密に正しい: 獲得標高↔喪失標高の入れ替え、始点/終点標高の入れ替え、
    平均勾配の符号反転、最大/最小勾配の符号反転＋入れ替え（domain/attributes.py:
    elevation_values_sqlが区間の頂点列を進行方向の順で積算するため、逆順に
    辿ると各区間のdiff＝勾配の符号がすべて反転し、max/minも入れ替わる）。
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


def _reverse_elevation_by_edge(
    edges_in_path: list[LeanEdge],
    reverse_edges: list[LeanEdge],
    elevation_by_edge: dict[str, ElevationAttribute],
) -> dict[str, ElevationAttribute]:
    """逆方向Edge列ぶんの`ElevationAttribute`を、順方向の値から代数的に導出する。

    順方向で標高が取れなかったEdgeは逆方向側にもキーを持たせない（欠損をそのまま伝える）。
    """
    result: dict[str, ElevationAttribute] = {}
    for forward_edge, reverse_edge in zip(reversed(edges_in_path), reverse_edges):
        forward_attribute = elevation_by_edge.get(forward_edge.edge_id)
        if forward_attribute is not None:
            result[reverse_edge.edge_id] = _reverse_elevation_attribute(forward_attribute, reverse_edge.edge_id)
    return result


def _route_composite_difficulty(candidate: RouteCandidate) -> float | None:
    """候補のsegmentsから距離加重平均の合成difficultyを求める。順方向と逆回りの比較に使う。

    戦略層が最終候補へ付ける`overall_difficulty`と同じ計算だが、あちらは採否が確定した後の
    後処理で、こちらはその採否自体を決めるためにエンジン内で呼ぶ。
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


def _concat_edge_geometries(edges: list[LeanEdge]) -> tuple[dict, list[int]]:
    """経路上のEdge群を、ひとつながりのGeoJSON LineStringとEdgeの境界点の位置へ変換する。

    隣接するEdgeの境界点（前Edgeの終端＝次Edgeの始端）は重複させないため、**座標列だけ
    からはどこがEdgeの境目か復元できない**。Edge単位で決めた区間を地図へ帯として描く
    ために境界の位置を併せて返す。

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


def _aggregate_elevation(edges: list[LeanEdge], elevation_by_edge: dict) -> dict:
    attrs = [elevation_by_edge.get(edge.edge_id) for edge in edges]
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


