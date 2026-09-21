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
from app.domain.weather import WeatherConditions
from app.domain.wind import WindForecastSeries, wind_drag_ratio_array


@dataclass(frozen=True, slots=True)
class DynamicAxisRequestContext:
    """動的材料をリクエスト時にベクトル評価するための統一入力。Edgeの幾何配列と
    リクエスト単位の動的データ（風・走行速度）を束ねる。

    `DYNAMIC_MATERIAL_EVALUATORS`のevaluatorがこの1引数だけを取る形にしてあるため、
    動的材料が増えても呼び出し側へ軸名・材料名の分岐が要らない。
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


# 材料idから、リクエスト時点の幾何配列＋動的contextをベクトル評価する関数への唯一の
# 登録点（式の実体は`domain/wind.py`にあり、ここは配線のみ）。軸idではなく材料idで
# キーイングするのは、合成側（`dynamic_axis_topological_order`・`evaluate_axis_array`）が
# 軸名をハードコードせず、動的材料さえ埋まればどんな軸でも合成できるため——軸スタジオで
# 作られたカスタム軸もこの登録だけでカバーされる。
# `REQUEST_DYNAMIC_MATERIAL_IDS`と1対1に揃える。片方だけだと
# `evaluate_dynamic_material_arrays`がKeyErrorで失敗する。
DYNAMIC_MATERIAL_EVALUATORS: dict[str, Callable[[DynamicAxisRequestContext], np.ndarray]] = {
    "wind_drag_ratio": _evaluate_wind_drag_ratio_array,
}


def evaluate_dynamic_material_arrays(context: DynamicAxisRequestContext) -> dict[str, np.ndarray]:
    """`REQUEST_DYNAMIC_MATERIAL_IDS`の全材料を`context`から評価する（材料id→配列、
    `context.bearing_deg`と同じ行順）。動的材料を評価する唯一の経路で、
    静的行列への動的軸合成（`evaluate_dynamic_axis_arrays`）もここを通る。"""
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
    `dynamic_axis_topological_order`の順で`evaluate_axis_array`を適用する。動的軸の軸名は
    ここにも現れない。
    """
    materials_with_axes: dict[str, np.ndarray] = dict(static_axis_scores)
    materials_with_axes.update(evaluate_dynamic_material_arrays(context))
    for axis_id in dynamic_axis_topological_order(AXIS_DEFINITIONS):
        materials_with_axes[axis_id] = evaluate_axis_array(AXIS_DEFINITIONS[axis_id], materials_with_axes)
    return materials_with_axes
