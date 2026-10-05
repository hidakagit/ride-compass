"""レグ（基準点・時刻・向き）ごとのコスト配列の合成。

探索範囲の静的スコア行列・重み・0次フィルタ・風の予報・昼夜から、区間ごとの体感の所要時間（探索のコスト）と、
区間の表示が読む難易度・軸・材料・所要時間を、時刻ビンごとに合成する。外部とはやり取りせず、配列だけを受け取って配列を返す。
探索（`services/road_graph_engine.py`）はここが合成した配列をそのまま読み、区間の表示も同じ配列から読む
（探索コストと表示の一致、design-principles.md構造仕様10）。構造と前提はdocs/modules/backend/routing-engine.md
「レグ別コスト配列」「レグ内の時刻ビン」節が持つ。
"""

import logging
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from app.domain.attributes import CategoricalColumn
from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    REQUEST_DYNAMIC_MATERIAL_IDS,
    dynamic_axis_topological_order,
    time_scoped_weights,
)
from app.domain.cycling_speed import (
    ROLLING_RESISTANCE_MATERIAL_ID,
    RiderProfile,
    SegmentSpeedModel,
    crr_for_surface,
)
from app.domain.difficulty import axis_contributions_at_row, axis_weighted_sums
from app.domain.dynamic_materials import DynamicAxisRequestContext, evaluate_dynamic_axis_arrays
from app.domain.evaluation import AxisComposition, StaticEdgeScoreMatrix, compose_costs_from_axis_matrix
from app.domain.route import Coordinates, SegmentWind
from app.domain.traffic import POI_COUNT_KINDS, stop_count_material_ids, stop_seconds
from app.domain.twilight import night_mask
from app.domain.wind import DepartureWind, WindForecastSeries, kmh_to_ms


# レグの中を時刻で区切るビンの幅（h）と本数の上限。**風の予報が1時間刻みのため、幅もそれに
# 揃え、ビンはその開始時刻で評価する**——`WindForecastSeries.sample`が最も近い正時を引くため、
# 幅を細かくしても隣のビンが同じ予報時刻を引くだけで、合成の回数だけが増える。
TIME_BIN_HOURS = 1.0
MAX_TIME_BINS = 4

logger = logging.getLogger("ridecompass.graph")


@dataclass
class LegCostArrays:
    """1レグぶんの合成済みコスト配列一式。`cost_lazy`は区間の番号順（探索が使う
    行順）、それ以外は切り出した区間の順の表示用配列。レグごとに違うのは通過予定時刻で決まるもの（各Edgeの
    通過予定時刻の風と、時間帯を持つ軸の重み）だけで、静的軸の列は共有する。"""

    cost_lazy: np.ndarray
    difficulty_array: np.ndarray
    axis_arrays: dict[str, np.ndarray]
    # 区間ごとの「データのある軸の重みの合計」。軸別寄与度（表示用）はこれと`axis_arrays`から
    # `axis_contributions_at`が読むときに1行だけ求める——全区間ぶん作っても、読むのは
    # 経路上の数百区間だけのため。
    weight_sums: np.ndarray
    # 合成に使った重み。時間帯を持つ軸（`time_scope`）は、区間ごとの通過時刻で決めた重みの配列
    # （切り出した区間の順、`domain/axis_definitions.py: time_scoped_weights`）。
    weights: Mapping[str, float | np.ndarray]
    # 折れ点を通す前の生値（切り出した区間の順）。静的スコア行列の列をそのまま指すため
    # レグ間で同じ配列を共有する（風のようにレグごとに変わる値は持たない）。
    axis_raw_arrays: dict[str, np.ndarray]
    # 切り出した区間の順の材料id→配列。動的材料（`evaluate_dynamic_material_arrays`が返す
    # 全材料が対象、全行NaNの材料はキーを持たない）と、内訳表示用の静的材料
    # （`route_facing_material_ids`、静的スコア行列の列）の両方を持つ。区間表示・
    # `material_values`の集計が、探索コストの合成と同じ入力から求めた値を読むために保持する。
    material_arrays: dict[str, np.ndarray]
    # 切り出した区間の順のcategorical材料id→語彙への番号の列（静的スコア行列の列をそのまま指すため
    # レグ間で共有する）。区間表示の内訳が値ごとの延長割合を出すために保持する。
    categorical_material_arrays: dict[str, CategoricalColumn]
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
    # （`LegCostComposer.values_at_rows`）。
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
    weights: Mapping[str, float | np.ndarray]
    material_arrays: dict[str, np.ndarray]

    def axis_contributions_at(self, row: int) -> dict[str, float]:
        return axis_contributions_at_row(self.axis_arrays, self.weights, self.weight_sums, row)


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


def _timed_leg_key(leg_start_hours: float, bin_count: int, duration_hours: float | None) -> tuple:
    """時刻で引き直すレグの使い回しの鍵。代表ビンも入れる——同じ開始時刻・同じビン数でも、
    見込み所要時間が違えば代表（表示が読むビン）は変わりうる。"""
    return (round(leg_start_hours, 3), bin_count, _representative_bin(bin_count, duration_hours))


def _row_taker(rows: np.ndarray | None) -> Callable[[np.ndarray], np.ndarray]:
    """配列から行`rows`だけを取り出す関数（Noneなら配列をそのまま返す）。"""
    if rows is None:
        return lambda values: values
    return lambda values: values[rows]


@dataclass
class _Evaluated:
    """`LegCostComposer._evaluate`の途中結果。"""

    published: dict[str, np.ndarray]
    material_arrays: dict[str, np.ndarray]
    travel: np.ndarray
    composed: AxisComposition
    weights: Mapping[str, float | np.ndarray]


class LegCostComposer:
    """bbox全体ぶんのコスト配列を、レグ（基準点・時刻オフセット・向き）ごとに合成する。
    静的スコア行列・重み・0次フィルタ・lazy_graph行順の対応表はリクエスト内で共通のため
    1回だけ用意する。時刻に依らない計算（走行モデルの出力と一定の抵抗・停止の待ち、時刻で変わる軸に
    重みが無ければ合成の難易度と割増の倍率も）はリクエストに1回だけ求め、時刻ビンごとには
    その時刻の風と昼夜に依る計算だけを行う。
    **風の時別系列が無く、時間帯を持つ軸にも重みが無いときだけ**、出発時点のスナップショットで合成した
    1本（`snapshot`）を全レグで共有する（追加コストゼロ）。系列があれば軸の重みが0でも時刻で引き直す
    ——理由は`__init__`の`self.time_varying`のコメント参照。"""

    def __init__(
        self,
        score_matrix: StaticEdgeScoreMatrix,
        weights: dict[str, float],
        penalty_strength: float,
        hard_filter_excluded: np.ndarray,
        departure_wind: DepartureWind | None,
        wind_series: WindForecastSeries | None,
        start: datetime,
        speed_kmh: float,
        lazy_row_index: np.ndarray,
        detour_ratio: float,
        twilight_origin: Coordinates,
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
        # 同じくcategorical材料（語彙への番号の列で別に運ぶ、`route_facing_categorical_material_ids`）。
        self._categorical_material_arrays = dict(
            zip(score_matrix.categorical_material_ids, score_matrix.categorical_material_columns, strict=True)
        )
        self._static_axis_scores = score_matrix.axis_arrays()
        # 時刻で変わる公開軸（風に依存する軸と、時間帯を持つ軸）と、それ以外。ビンごとの合成では後者の
        # 重み付き和を使い回す——合成の時間は軸数にほぼ比例するため、毎回全軸を足し直すと本数ぶん効く。
        dynamic_axes = set(dynamic_axis_topological_order(AXIS_DEFINITIONS))
        time_scoped_axes = {
            axis_id for axis_id in score_matrix.axis_ids
            if (definition := AXIS_DEFINITIONS.get(axis_id)) is not None and definition.time_scope != "always"
        }
        self._time_varying_axis_ids = [
            a for a in score_matrix.axis_ids if a in dynamic_axes or a in time_scoped_axes
        ]
        self._fixed_axis_ids = [a for a in score_matrix.axis_ids if a not in self._time_varying_axis_ids]
        # 重みが0の軸は合成に何も足さないので、時刻で変わる軸がすべて重み0なら合成は時刻に依らない。
        self._composition_is_time_invariant = all(
            weights.get(axis_id, 0.0) == 0.0 for axis_id in self._time_varying_axis_ids
        )
        self._weights = weights
        self._penalty_strength = penalty_strength
        self._hard_filter_excluded = hard_filter_excluded
        self._departure_wind = departure_wind
        self._wind_series = wind_series
        # 各Edgeの中点に最も近い予報の格子点（切り出した区間の順）。
        self._wind_points = (
            None if wind_series is None
            else wind_series.lattice.points_of(score_matrix.mid_lat, score_matrix.mid_lon)
        )
        self.start = start
        # 昼夜を決める地点。探索範囲の中の位置の違いで薄明の時刻がずれるのは数分のため、区間ごとには引かない。
        self._twilight_origin = twilight_origin
        self.speed_kmh = speed_kmh
        self._lazy_row_index = lazy_row_index
        # lazy行順の配列を切り出した区間の順へ戻す並べ替え表（`_lazy_row_index`の逆）。
        # `_lazy_row_index`は全単射ではない——同一Node間の並行Edgeは`build_lazy_road_graph`が
        # 1本だけ採るため、探索用グラフに載らないEdgeがある。載らない行は-1にする。
        self._full_row_index = np.full(len(score_matrix.distance_m), -1, dtype=np.int64)
        self._full_row_index[lazy_row_index] = np.arange(len(lazy_row_index))
        # 通過予定時刻の推定に使う迂回率（道なり距離÷直線距離）。探索範囲ごとの学習値が
        # あればそれ、無ければ`ROUTE_DETOUR_RATIO`。合成には使わず、レグの時刻を置く探索の側が読む。
        self.detour_ratio = detour_ratio
        # 風の時別系列があれば常に時変化合成する。風は軸（主観的な避けたさ）である前に
        # **走行モデルの入力**（向かい風で実際に遅くなる）のため、軸の重みが0でも時刻で
        # 引き直す必要がある。時間帯を持つ軸は重みがあるときだけ、通過時刻の昼夜で合成が変わる。
        self.time_varying = wind_series is not None or any(
            weights.get(axis_id, 0.0) > 0 for axis_id in time_scoped_axes
        )
        self._cache: dict[tuple, LegCostArrays] = {}
        self._fixed_axis_sums_cache: tuple[np.ndarray, np.ndarray] | None = None
        self._travel_inputs_cache: tuple[SegmentSpeedModel, np.ndarray] | None = None
        self._time_invariant_composition_cache: AxisComposition | None = None

    def _travel_inputs(self, rows: np.ndarray | None) -> tuple[SegmentSpeedModel, np.ndarray]:
        """所要時間のうち風に依らない入力: 走行モデル（勾配・路面・巡航速度）と、区間にある停止要因の
        待ちの秒（`domain/traffic.py: stop_seconds`）。どちらも静的材料だけから決まるため、全区間ぶん
        （`rows`がNone）はリクエストに1回だけ求める。`rows`を渡すとその行だけで求める。"""
        if rows is None and self._travel_inputs_cache is not None:
            return self._travel_inputs_cache
        take = _row_taker(rows)

        def static_material(material_id: str) -> np.ndarray | None:
            values = self._static_material_arrays.get(material_id)
            return None if values is None else take(values)

        distance_m = take(self._score_matrix.distance_m)
        # 勾配は静的スコア行列が生配列として常に持つ（0次フィルタの勾配しきい値と同じ列）。
        # 内訳として見せる材料だけを運ぶ`material_arrays`では、勾配軸が分解されていない構成で欠ける。
        grade = np.nan_to_num(take(self._score_matrix.gradient_percent)) / 100.0
        surface = self._categorical_material_arrays[ROLLING_RESISTANCE_MATERIAL_ID]
        crr = crr_for_surface(surface if rows is None else surface.take(rows))
        model = SegmentSpeedModel(RiderProfile(cruise_speed_kmh=self.speed_kmh), grade, crr)
        stops = np.zeros(len(distance_m))
        # 材料idの綴りは`stop_count_material_ids()`が単一の情報源。ここで組み立て直すと、
        # 向こうで綴りを変えたときにここだけがNoneを引き、全区間の停止の待ちが無言で0秒になる。
        for kind, material_id in zip(POI_COUNT_KINDS, stop_count_material_ids(), strict=True):
            per_km = static_material(material_id)
            if per_km is not None:
                stops += np.nan_to_num(per_km) * (distance_m / 1000.0) * stop_seconds(kind)
        if rows is None:
            self._travel_inputs_cache = (model, stops)
        return model, stops

    def _travel_time_seconds(
        self, headwind_ms: np.ndarray, crosswind_ms: np.ndarray, rows: np.ndarray | None
    ) -> np.ndarray:
        """区間ごとの所要時間（秒）を切り出した区間の順で返す。

        走行モデル（`domain/cycling_speed.py`）で勾配・風の成分・路面・巡航速度から求めた
        走行時間に、その区間にある停止要因の待ちを足したもの。
        ターンの待ちは遷移ごとに決まるためここには含まない（探索側が足す）。
        0次フィルタで除外された区間は無限大にする（探索から見た通行可否をコストの下地だけで
        表すため）。`rows`を渡すとその行だけ（引数の配列も同じ並び）で求める。
        """
        take = _row_taker(rows)
        model, stops = self._travel_inputs(rows)
        travel = model.travel_seconds(take(self._score_matrix.distance_m), headwind_ms, crosswind_ms)
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
        時刻で変えるかどうかは`time_varying`（風の時別系列があるか・時間帯を持つ軸に重みがあるか）だけで決まる。

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
            key = _timed_leg_key(leg_start, bin_count, duration_hours)
        cached = self._cache.get(key)
        if cached is not None:
            # 同じ内容を使い回すのは正しい（風が時刻で変わらないレグは1本で足りる）が、
            # 黙って返すと合成のログがレグの数だけ出ず、運用側から「復路の合成が走って
            # いない」と見える。使い回した事実を残す。
            logger.info("compose_leg_costs leg=%s mode=reused key=%s", label, key[0])
            return cached

        started = time.monotonic()
        reused_bins = 0
        if not self.time_varying:
            bins = [self._compose_at(None)]
        elif passage_hours is not None:
            bins = [self._compose_at(passage_hours)]
        else:
            bins = []
            for k in range(bin_count):
                bin_start = leg_start + k * TIME_BIN_HOURS
                # 同じ時刻のビン1本のレグを合成済みなら、それがこのビンと同じ中身になる（周回・目的地ルートの
                # 往路の先頭のビンは、`prepare`が見込み時間なしで合成した1本と同じ時刻から始まる）。
                single = self._cache.get(_timed_leg_key(bin_start, 1, None))
                if single is not None:
                    reused_bins += 1
                    bins.append(single)
                else:
                    bins.append(self._compose_at(np.full(edge_count, bin_start)))

        # 代表はレグの中間地点が入るビン（ビンはレグの見込み時間より長く張られることがあり、
        # 単純な中央の添字だと終盤のビンへ寄る）。
        representative = bins[_representative_bin(len(bins), duration_hours)]
        leg = LegCostArrays(
            cost_lazy=representative.cost_lazy,
            difficulty_array=representative.difficulty_array,
            axis_arrays=representative.axis_arrays,
            weight_sums=representative.weight_sums,
            weights=representative.weights,
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
            "compose_leg_costs leg=%s mode=%s bins=%d reused_bins=%d compose_ms=%d",
            label, "time_varying" if self.time_varying and anchor is not None else "snapshot",
            len(bins), reused_bins, round((time.monotonic() - started) * 1000),
        )
        return leg

    def _fixed_axis_sums(self, rows: np.ndarray | None) -> tuple[np.ndarray, np.ndarray]:
        """時刻で変わらない軸の`(重み付きスコアの和, 重みの和)`。時刻で変わる軸だけをビンごとに足す合成
        （時刻で変わる軸に重みがあるとき）と、経路上の行の合成し直しが使う。`rows`を渡すとその行だけで求める。

        全区間ぶんは軸数ぶんの走査が要るため、要求されるまで遅らせて1回だけ求める——時刻で変わる軸に
        重みが無ければ合成そのものを1回で済ませる（`_time_invariant_composition`）ので、求めない。
        """
        if rows is not None:
            return axis_weighted_sums(
                {axis_id: self._static_axis_scores[axis_id][rows] for axis_id in self._fixed_axis_ids},
                self._weights, len(rows),
            )
        if self._fixed_axis_sums_cache is None:
            self._fixed_axis_sums_cache = axis_weighted_sums(
                {axis_id: self._static_axis_scores[axis_id] for axis_id in self._fixed_axis_ids},
                self._weights, len(self._score_matrix.distance_m),
            )
        return self._fixed_axis_sums_cache

    @property
    def _time_invariant_composition(self) -> AxisComposition:
        """時刻で変わる軸に重みが無いときの、全区間ぶんの合成。下地を1にして合成するので`cost`は割増の
        倍率そのもので、ビンごとのコストは所要時間にこれを掛けるだけになる。"""
        if self._time_invariant_composition_cache is None:
            distance_m = self._score_matrix.distance_m
            self._time_invariant_composition_cache = compose_costs_from_axis_matrix(
                distance_m,
                {axis_id: self._static_axis_scores[axis_id] for axis_id in self._fixed_axis_ids},
                self._weights, self._penalty_strength, base=np.ones(len(distance_m)),
            )
        return self._time_invariant_composition_cache

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
        当て直すために使う。時間帯を持つ軸の重みは、区間ごとの通過時刻（スナップショットは出発時刻）の昼夜で決める。"""
        take = _row_taker(rows)
        bearing = take(self._score_matrix.bearing_deg)
        hours = np.zeros(len(bearing)) if passage is None else passage
        weights = time_scoped_weights(
            self._weights,
            {"night_only": night_mask(self._twilight_origin, self.start, hours)},
        )
        dynamic_context = DynamicAxisRequestContext(
            bearing_deg=bearing, departure_wind=self._departure_wind,
            travel_speed_ms=kmh_to_ms(self.speed_kmh),
            wind_series=self._wind_series, start=self.start, passage_hours=passage,
            wind_points=None if self._wind_points is None else take(self._wind_points),
        )
        static_scores = (
            self._static_axis_scores if rows is None
            else {axis_id: values[rows] for axis_id, values in self._static_axis_scores.items()}
        )
        resolved = evaluate_dynamic_axis_arrays(static_scores, dynamic_context)
        wind = dynamic_context.wind_components_ms
        if wind is None:
            headwind = crosswind = np.zeros(len(bearing))
        else:
            headwind, crosswind = wind
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
        travel = self._travel_time_seconds(headwind, crosswind, rows)
        # evaluate_dynamic_axis_arraysは内部軸も含めうるため、公開軸のみへ絞って合成する。
        # 合成へ渡すのは時刻で変わる軸だけにし、それ以外は先に求めた重み付き和を使い回す
        # （合成の時間は軸数にほぼ比例する）。表示が読む`axis_arrays`は全軸を持たせる。
        published = {axis_id: resolved[axis_id] for axis_id in self._score_matrix.axis_ids}
        if rows is None and self._composition_is_time_invariant:
            invariant = self._time_invariant_composition
            composed = AxisComposition(travel * invariant.cost, invariant.difficulty, invariant.weight_sums)
        else:
            time_varying = {axis_id: resolved[axis_id] for axis_id in self._time_varying_axis_ids}
            composed = compose_costs_from_axis_matrix(
                take(self._score_matrix.distance_m), time_varying, weights, self._penalty_strength,
                base=travel, static_sums=self._fixed_axis_sums(rows),
            )
        return _Evaluated(
            published=published, material_arrays=material_arrays, travel=travel, composed=composed, weights=weights,
        )

    def values_at_rows(self, rows: np.ndarray, passage_hours: np.ndarray) -> RowValues:
        """経路上の行`rows`（切り出した区間の順の行番号）だけを、行ごとの通過時刻`passage_hours`で合成し直す。"""
        evaluated = self._evaluate(np.asarray(passage_hours, dtype=float), np.asarray(rows, dtype=np.int64))
        return RowValues(
            rows=np.asarray(rows, dtype=np.int64),
            difficulty_array=evaluated.composed.difficulty,
            axis_arrays=evaluated.published,
            weight_sums=evaluated.composed.weight_sums,
            weights=evaluated.weights,
            material_arrays=evaluated.material_arrays,
        )

    @property
    def weights(self) -> dict[str, float]:
        """利用者の軸の重み（時間帯を持つ軸も、通過時刻で0にする前の値）。区間に載せる材料の集合はこの重みから決まる。"""
        return self._weights

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
        return self._departure_wind is None and self._wind_series is None

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
        if self._wind_series is not None and self._wind_points is not None and timed:
            timed_hours = np.array([passage_hours[i] for i in timed], dtype=float)
            points = self._wind_points[[rows[i] for i in timed]]
            speed, direction = self._wind_series.sample(self.start, timed_hours, points)
            times, clamped = self._wind_series.sampled_times(self.start, timed_hours)
            for j, i in enumerate(timed):
                winds[i] = SegmentWind(
                    speed_ms=round(float(speed[j]), 1),
                    direction_deg=round(float(direction[j]), 1),
                    forecast_at=times[j].isoformat(timespec="minutes"),
                    extended=bool(clamped[j]) or beyond_bins[i],
                )
        if self._departure_wind is not None:
            # 時刻で引けなかった区間（出発時点の値で合成した区間と、時別系列が無いまま昼夜のために
            # 時刻で合成した区間）は、出発時点の風。
            for i, wind in enumerate(winds):
                if wind is None:
                    winds[i] = SegmentWind(
                        speed_ms=self._departure_wind.speed_ms,
                        direction_deg=self._departure_wind.direction_deg,
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
            weights=evaluated.weights,
            axis_raw_arrays=self._axis_raw_arrays,
            material_arrays=material_arrays,
            categorical_material_arrays=self._categorical_material_arrays,
            travel_seconds_full=travel,
            travel_seconds_lazy=lazy_travel,
            cost_bins_lazy=lazy_cost.reshape(1, -1),
            travel_bins_lazy=lazy_travel.reshape(1, -1),
            bin_seconds=np.inf,
        )


def material_value_at(leg: LegCostArrays | RowValues, material_id: str, row: int) -> float | None:
    """レグの合成に使った材料配列から1行を読む（材料データ無し・欠損はNone）。"""
    array = leg.material_arrays.get(material_id)
    if array is None:
        return None
    value = float(array[row])
    return None if math.isnan(value) else value
