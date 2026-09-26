"""専用way値レイヤー（`dedicated_way_value_layer=True`の軸）が対象とする軸の宣言。状態機械
（ルート未確定=ユーザー指定パラメータを全道路へ一律適用／ルート確定後=ルート自身の実値を
ルート線のみへ適用）は軸非依存で、実際に何のパラメータ（時刻・向き・速度）を必要と
するかだけをここで宣言する。

**この層で扱うidは軸id（`axis_definitions.axis_id`）であり、材料id
（`material_catalog.py`のキー、例: `wind_drag_ratio`）ではない。**両者は名前空間が
異なる別概念で、配信サービスが返す生値の材料idは`WindWayService.material_id`等が
別に持つ（`transform_dedicated_way_values`が軸定義の評価へ渡す先）。

軸→サービス実装本体の対応は、軸が参照する材料とサービスの`material_id`の突き合わせで
決まる（`api/dependencies.py: _DEDICATED_WAY_VALUE_SERVICES`）。材料ごとの計算ロジック
自体は宣言的に導出できないPythonコードのまま残る。
"""

from dataclasses import dataclass
from typing import Literal, cast

from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    BreakpointLinearShape,
    evaluate_axis_scalar,
)
from app.domain.axis_display import axis_display_for
from app.domain.axis_templates import evaluate_breakpoint_linear
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

    定数ではなく呼び出しの都度導出する関数なのは、`AXIS_DEFINITIONS`がプロセス起動時・
    管理API書き込み直後にin-place更新されるため。軸スタジオでの設定はここへ自動的に
    反映される。

    配信できる値があるかは別で、軸が参照する材料の値を組み立てるサービス本体が
    `api/dependencies.py`の`_DEDICATED_WAY_VALUE_SERVICES`に登録されている必要がある
    （材料ごとに1回のコード変更。軸を増やすたびには要らない）。登録の無い材料だけを
    参照する軸へこのフラグを立てることは書き込み時に拒否される
    （`axis_admin.py: _check_dedicated_layer_is_implemented`）。
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
    """**`terms[0].material`は材料idと軸idの2つの名前空間を跨ぐ**（`axis_definitions.py`）。
    材料を指しているときだけ生値を塗れる——軸を指す項の値は参照先の得点で、符号にも単位にも
    材料の意味が無い。0次条件を持つ軸も生値を塗らない——条件の当たる道でも生値は生値のままで、
    評価（条件の値）と食い違う。"""
    shape = definition.shape
    if (
        not definition.priority_overrides
        and isinstance(shape, BreakpointLinearShape)
        and shape.preprocess == "abs"
        and len(shape.terms) == 1
        and shape.terms[0].material in MATERIAL_CATALOG
    ):
        return "signed_material"
    return "difficulty"


def _signed_thresholds_from_breakpoints(shape: BreakpointLinearShape) -> list[float]:
    """符号付き材料の段の境界を、軸自身の折れ線の節から作る。

    **段の並びをどこかに固定で持たない。** 折れ線の節は「この材料のどの値から効きが
    変わるか」を軸が宣言したもので、段の境界として意味がある。固定の一覧を別に持つと、
    軸を直しても段が追従せず、しかもその一覧を誰が決めたのかが辿れなくなる。

    軸は`|値|`を評価している（`preprocess="abs"`）ので、段も0対称に開く——正負で
    別の切り方をする根拠を軸は持たない。
    """
    knots = sorted({x for x, _ in shape.breakpoints if x > 0})
    return [-x for x in reversed(knots)] + knots


def map_value_thresholds(definition: AxisDefinition) -> list[float] | None:
    """`map_value_kind`が示すスケールでの段階境界。

    **ルート確定前の全道路の塗りと、確定後のルート線は同じ段で塗る。** 前者は材料の
    重み付き和を、後者は0〜100の難易度を塗るため、同じ段を両方の目盛りで言い直す必要が
    ある。ここが返すのは後者の目盛りでの境界で、前者の境界（`axis_display_for`が持つ
    しきい値）を軸の折れ線で写したものである——写さずに渡すと、材料の単位で書かれた境界が
    難易度と比べられ、ルート線が全区間ひとつのバンドへ落ちる。

    `CategoricalShape`の値は初めからスコアと同じスケールのため写さない。ramp表示を持たない
    軸（専用way値配信）の上書きも、地図が塗る値そのものに対する境界なのでそのまま返す。
    """
    display = axis_display_for(definition)
    if display.kind != "ramp":
        override = definition.display_thresholds_override
        if override is not None:
            return list(override)
        if map_value_kind(definition) == "signed_material":
            # `signed_material`は折れ線の軸にしか付かない。
            return _signed_thresholds_from_breakpoints(cast(BreakpointLinearShape, definition.shape))
        return None
    shape = definition.shape
    if not isinstance(shape, BreakpointLinearShape):
        return list(display.thresholds)
    if shape.preprocess != "identity":
        # 符号を畳む軸の折れ線は材料の目盛りを写せない（負の境界が正の側へ折り返る）。
        # 地図に塗れる軸を符号を畳まない形に限るのは`axis_display_for`で、そちらが変わったときに
        # ルート線が全区間同じ帯へ黙って落ちないよう、ここで止める。
        raise ValueError(
            f"axis '{definition.axis_id}': ramp display on a shape that folds the sign "
            f"(preprocess={shape.preprocess!r}); its thresholds cannot be mapped"
        )
    return [
        round(evaluate_breakpoint_linear(threshold, shape.breakpoints), 1)
        for threshold in display.thresholds
    ]


def map_value_unit(definition: AxisDefinition) -> str:
    """地図の凡例に添える単位。難易度は無次元（空文字）、符号付き材料は材料カタログの単位。"""
    if map_value_kind(definition) != "signed_material":
        return ""
    shape = definition.shape
    assert isinstance(shape, BreakpointLinearShape)
    return MATERIAL_CATALOG[shape.terms[0].material].unit


def transform_dedicated_way_values(
    definition: AxisDefinition, material_id: str, values: dict[str, float]
) -> dict[str, float]:
    """専用way値配信サービスが返した材料生値（`material_id`の値）を、地図が塗るべき値へ
    変換する。`map_value_kind`が`difficulty`なら軸スタジオの定義（breakpoints・
    priority_overrides）で評価した難易度、`signed_material`なら生値のまま。評価できない
    値（軸が他の材料も必須にしている等）はその道路を結果から除く（地図上は「データなし」）。
    同じ材料値は1回だけ評価する（風のようにタイル内が全て同値の場合、評価は1回で済む）。
    """
    if map_value_kind(definition) == "signed_material":
        return values
    if any(override.material != material_id for override in definition.priority_overrides):
        # 配信が値を持つのは`material_id`だけで、ほかの材料に置いた0次条件は当たるかどうかを決められない。
        return {}
    evaluated: dict[float, float | None] = {}
    result: dict[str, float] = {}
    for feature_key, value in values.items():
        if value not in evaluated:
            evaluated[value] = evaluate_axis_scalar(definition, {material_id: value})
        difficulty = evaluated[value]
        if difficulty is not None:
            result[feature_key] = difficulty
    return result

