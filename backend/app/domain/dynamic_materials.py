"""動的材料（`REQUEST_DYNAMIC_MATERIAL_IDS`）のリクエスト時評価。

Edgeへ永続保存せず、リクエストのたびに風・走行速度・通過予定時刻から求める材料を
扱う。静的材料（`domain/material_catalog.py`のextractor）とは値の出どころも
更新の頻度も違うため、評価本体（`domain/evaluation.py`）から分けてある。
"""

from datetime import datetime
from dataclasses import dataclass
from typing import Callable, Mapping

import numpy as np

from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    REQUEST_DYNAMIC_MATERIAL_IDS,
    dynamic_axis_topological_order,
    evaluate_axis_array,
)
from app.domain.graph import EdgeLike
from app.domain.weather import WeatherConditions
from app.domain.wind import WindForecastSeries, wind_drag_ratio_array


def compute_dynamic_edge_materials(
    edge: EdgeLike, weather: WeatherConditions | None, travel_speed_ms: float | None
) -> dict[str, float | None]:
    """Edge1本ぶんの動的材料（`REQUEST_DYNAMIC_MATERIAL_IDS`の各材料id→値）を、Edgeの
    進行方向（`edge.bearing_deg`、from_node→to_node）・出発時点の風・走行速度から求める。
    風が無い、またはbearing未計算のEdgeは全材料None（データ無し）。

    `DYNAMIC_MATERIAL_EVALUATORS`（配列版）を長さ1の配列で呼ぶ薄いラッパーのため、
    スカラー経路とbulk/動的軸経路の式が乖離しない。風はEdgeに永続保存しない（動的データで
    ありRoad Attributeとして扱わない）。
    """
    if weather is None or edge.bearing_deg is None:
        return {material_id: None for material_id in REQUEST_DYNAMIC_MATERIAL_IDS}
    if travel_speed_ms is None:
        raise ValueError("compute_dynamic_edge_materials: travel_speed_ms is required when weather is given")
    context = DynamicAxisRequestContext(
        bearing_deg=np.array([edge.bearing_deg], dtype=float), weather=weather, travel_speed_ms=travel_speed_ms,
    )
    result: dict[str, float | None] = {}
    for material_id, array in evaluate_dynamic_material_arrays(context).items():
        value = float(array[0])
        result[material_id] = None if np.isnan(value) else value
    return result


@dataclass(frozen=True, slots=True)
class DynamicAxisRequestContext:
    """動的材料（`REQUEST_DYNAMIC_MATERIAL_IDS`）をリクエスト時にベクトル評価するための
    統一入力。Edgeの幾何配列とリクエスト単位の動的データ（風・走行速度）を束ねる。

    `DYNAMIC_MATERIAL_EVALUATORS`へ登録する各材料のevaluatorはこの1引数だけを受け取り
    材料配列を返す統一シグネチャにすることで、動的材料が増えても呼び出し側
    （`evaluate_dynamic_axis_arrays`、静的行列のNaN列を埋める処理）へ軸名・材料名の分岐を
    追加せず、この辞書へ1エントリ追加するだけで対応できる（フロントの
    `RAMP_AXES`/`buildAxisOverlayLayers`と同種の汎用ディスパッチ）。呼び出しはリクエスト
    あたり動的材料の数だけの設定フェーズであり、Edge単位のホットループには入らない。
    """

    bearing_deg: np.ndarray
    weather: WeatherConditions | None
    # 走行速度（m/s、リクエスト単位）。既定値を置かないのは、走行速度に依存する材料へ
    # 伝播漏れがあったとき既定値で黙って計算せず、構築時点で失敗させるため。
    travel_speed_ms: float
    # 時刻依存の材料向け: 起点の時別予報系列と、各Edgeの通過予定時刻（`start`からの経過
    # 時間[h]、`bearing_deg`と同じ行順）。3つとも揃っていればEdgeごとに通過予定時刻の値を
    # 引き、揃っていなければ`weather`（出発時点のスナップショット）を全Edgeへ一様に使う。
    wind_series: WindForecastSeries | None = None
    start: datetime | None = None
    passage_hours: np.ndarray | None = None

    def time_varying(self) -> bool:
        return self.wind_series is not None and self.start is not None and self.passage_hours is not None

    def wind_inputs(self) -> tuple[np.ndarray, np.ndarray] | None:
        """各Edgeに適用する（風速, 風向）。時別系列と通過予定時刻が揃っていればEdgeごとに
        その時刻の値、揃っていなければ出発時点のスナップショット（全Edge共通のスカラー）。
        風が無ければNone。"""
        if self.time_varying():
            return self.wind_series.sample(self.start, self.passage_hours)
        if self.weather is None:
            return None
        return np.asarray(self.weather.wind_speed_ms, dtype=float), np.asarray(self.weather.wind_direction_deg, dtype=float)


def _evaluate_wind_drag_ratio_array(context: DynamicAxisRequestContext) -> np.ndarray:
    inputs = context.wind_inputs()
    if inputs is None:
        return np.full(context.bearing_deg.shape, np.nan)
    speed, direction = inputs
    return wind_drag_ratio_array(speed, direction, context.bearing_deg, context.travel_speed_ms)


# `REQUEST_DYNAMIC_MATERIAL_IDS`（axis_definitions.py）の各材料idを、リクエスト時点の
# 幾何配列＋動的contextからベクトル評価する関数への唯一の登録点（式の実体は
# `domain/wind.py`にあり、ここは配線のみ）。`REQUEST_DYNAMIC_MATERIAL_IDS`自体が
# 「材料id」の集合として宣言されている（軸idの集合ではない）ため、ここも材料idで
# キーイングする——`dynamic_axis_topological_order`・`evaluate_axis_array`（いずれも軸名を
# ハードコードしない汎用実装）が「動的材料さえ埋まればどんな軸（軸スタジオが動的材料を
# 直接参照して作成したカスタム軸を含む）でも正しく合成する」ため、材料id単位の登録だけで
# 軸全体をカバーできる。`REQUEST_DYNAMIC_MATERIAL_IDS`と1対1に揃える（動的材料が増えたら
# 両方へ1エントリずつ追加する。片方だけだと`evaluate_dynamic_material_arrays`が失敗する）。
DYNAMIC_MATERIAL_EVALUATORS: dict[str, Callable[[DynamicAxisRequestContext], np.ndarray]] = {
    "wind_drag_ratio": _evaluate_wind_drag_ratio_array,
}


def evaluate_dynamic_material_arrays(context: DynamicAxisRequestContext) -> dict[str, np.ndarray]:
    """`REQUEST_DYNAMIC_MATERIAL_IDS`の全材料を`context`から評価する（材料id→配列、
    `context.bearing_deg`と同じ行順）。スカラー経路（`compute_dynamic_edge_materials`）・
    bulk経路（`_evaluate_axes_bulk`）・静的行列への動的軸合成（`evaluate_dynamic_axis_arrays`）
    の3経路がすべてここを通る。"""
    return {
        material_id: DYNAMIC_MATERIAL_EVALUATORS[material_id](context)
        for material_id in REQUEST_DYNAMIC_MATERIAL_IDS
    }


def evaluate_dynamic_axis_arrays(
    static_axis_scores: Mapping[str, np.ndarray], context: DynamicAxisRequestContext,
) -> dict[str, np.ndarray]:
    """タイル単位でキャッシュ済みの`StaticEdgeScoreMatrix.axis_scores`（NaN列を含む）から、
    動的軸（`dynamic_axis_topological_order`が返す軸）だけをリクエスト時点の値で上書き
    した軸別スコア辞書を返す。戻り値には動的材料の配列も含む（呼び出し元が区間表示用に
    材料値を読めるようにするため）。

    `evaluate_dynamic_material_arrays`で動的材料を求め、そこから
    `dynamic_axis_topological_order`の順で`evaluate_axis_array`を適用する（材料→軸の
    汎用トポロジカル合成のベクトル版で、動的軸の軸名自体は本関数もハードコードしない）。
    """
    materials_with_axes: dict[str, np.ndarray] = dict(static_axis_scores)
    materials_with_axes.update(evaluate_dynamic_material_arrays(context))
    for axis_id in dynamic_axis_topological_order(AXIS_DEFINITIONS):
        materials_with_axes[axis_id] = evaluate_axis_array(AXIS_DEFINITIONS[axis_id], materials_with_axes)
    return materials_with_axes
