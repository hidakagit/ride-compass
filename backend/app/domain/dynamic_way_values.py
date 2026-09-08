"""専用way値レイヤー（`dedicated_way_value_layer=True`の軸）が対象とする軸の宣言。状態機械
（ルート未確定=ユーザー指定パラメータを全道路へ一律適用／ルート確定後=ルート自身の実値を
ルート線のみへ適用）は軸非依存で、実際に何のパラメータ（時刻・向き・速度）を必要と
するかだけをここで宣言する。

**この層で扱うidは軸id（`axis_definitions.axis_id`）であり、材料id
（`material_catalog.py`のキー、例: `wind_drag_ratio`）ではない。**両者は名前空間が
異なる別概念で、配信サービスが返す生値の材料idは`WindWayService.material_id`等が
別に持つ（`transform_dedicated_way_values`が軸定義の評価へ渡す先）。

`infrastructure/dynamic_way_value_cache.py`（キャッシュキーのbucket化要否）・
`api/routers/region.py`（`GET /api/region/dynamic-way-values/{axis_id}/{z}/{x}/{y}`の
クエリパラメータ必須/省略判定）の両方が`dedicated_way_value_axes()`を読む。

axis_id→サービス実装本体（`WindWayService`/`GradientWayService`）の組み立ては別軸
（`api/dependencies.py: _DEDICATED_WAY_VALUE_SERVICE_FACTORIES`）で、各軸の計算ロジック
自体は宣言的に導出できないPythonコードのまま残る。

詳細はdocs/modules/backend/dynamic-way-values.md「軸登録と地図表示値」節参照。
"""

from dataclasses import dataclass
from typing import Literal

from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    BreakpointLinearShape,
    evaluate_axis_scalar,
)
from app.domain.material_catalog import MATERIAL_CATALOG

# 地図がその軸について塗る値の種類。`signed_material`は「単一材料の絶対値を評価する軸」
# （勾配のように向きの符号が意味を持つ）で、地図は難易度ではなく符号付きの材料生値を塗る。
# それ以外は軸スタジオのbreakpointsで評価済みの難易度（0〜100）を塗る。ルート確定前の
# 専用way値配信（`transform_dedicated_way_values`）・ルート確定後のルート線色分け（frontend
# `routeStyleModes.ts`）の両方がこの1つの判定に従うため、同じ軸の色分けはルートの有無で
# スケールが変わらない。
MapValueKind = Literal["difficulty", "signed_material"]


@dataclass(frozen=True)
class DedicatedWayValueAxis:
    axis_id: str
    label: str
    # 時刻（`at`クエリパラメータ）に依存するか。風=Yes（気象予報が時々刻々変わる）、
    # 勾配=No（標高・道路の向きは時刻で変わらない）。
    needs_time: bool
    # 向き（`bearing_deg`クエリパラメータ）に依存するか。風・勾配どちらもYes——向きの
    # *出所*（外部データ/道路自身に内在）が異なるだけで、パラメータとしては両方とも
    # ユーザー指定の走行方位を必要とする。
    needs_bearing: bool
    # 想定速度（`speed_kmh`クエリパラメータ）に依存するか。走行速度依存の材料
    # （`wind_drag_ratio`）を参照する軸で立てる。
    needs_speed: bool


def dedicated_way_value_axes() -> dict[str, DedicatedWayValueAxis]:
    """`AXIS_DEFINITIONS`から`dedicated_way_value_layer=True`の軸を抽出して導出する。
    `AXIS_DEFINITIONS`はプロセス起動時・管理API書き込み直後にin-place
    更新される（`services/axis_registry_service.py`参照）ため、モジュール読み込み時の
    定数ではなく呼び出しの都度導出する関数にする（`axis_catalog.py: get_axis_catalog`と
    同じ「プロセス内メモリへの都度アクセス」方式）。軸スタジオでの
    `dedicated_way_value_layer=true`・`dynamic_way_value_needs_time`/
    `dynamic_way_value_needs_bearing`の設定はここへ自動的に反映される。

    配信できる値があるかは別で、way_id→値を組み立てるサービス本体を
    `api/dependencies.py`の`_DEDICATED_WAY_VALUE_SERVICE_FACTORIES`へ登録する必要がある
    （コード変更を伴う）。登録の無いaxis_idへこのフラグを立てることは書き込み時に
    拒否される（`axis_admin.py: _check_dedicated_layer_is_implemented`）。
    """
    return {
        axis_id: DedicatedWayValueAxis(
            axis_id=axis_id,
            label=definition.label,
            needs_time=definition.dynamic_way_value_needs_time,
            needs_bearing=definition.dynamic_way_value_needs_bearing,
            needs_speed=definition.dynamic_way_value_needs_speed,
        )
        for axis_id, definition in AXIS_DEFINITIONS.items()
        if definition.dedicated_way_value_layer
    }


def map_value_kind(definition: AxisDefinition) -> MapValueKind:
    shape = definition.shape
    if isinstance(shape, BreakpointLinearShape) and shape.preprocess == "abs" and len(shape.terms) == 1:
        return "signed_material"
    return "difficulty"


def map_value_unit(definition: AxisDefinition) -> str:
    """地図の凡例に添える単位。難易度は無次元（空文字）、符号付き材料は材料カタログの単位。"""
    if map_value_kind(definition) != "signed_material":
        return ""
    shape = definition.shape
    assert isinstance(shape, BreakpointLinearShape)
    spec = MATERIAL_CATALOG.get(shape.terms[0].material)
    return spec.unit if spec is not None else ""


def transform_dedicated_way_values(
    definition: AxisDefinition, material_id: str, values: dict[int, float]
) -> dict[int, float]:
    """専用way値配信サービスが返した材料生値（`material_id`の値）を、地図が塗るべき値へ
    変換する。`map_value_kind`が`difficulty`なら軸スタジオの定義（breakpoints・
    priority_overrides）で評価した難易度、`signed_material`なら生値のまま。評価できない
    値（軸が他の材料も必須にしている等）はその道路を結果から除く（地図上は「データなし」）。
    同じ材料値は1回だけ評価する（風のようにタイル内全wayが同値の場合、評価は1回で済む）。
    """
    if map_value_kind(definition) == "signed_material":
        return values
    evaluated: dict[float, float | None] = {}
    result: dict[int, float] = {}
    for way_id, value in values.items():
        if value not in evaluated:
            evaluated[value] = evaluate_axis_scalar(definition, {material_id: value})
        difficulty = evaluated[value]
        if difficulty is not None:
            result[way_id] = difficulty
    return result

