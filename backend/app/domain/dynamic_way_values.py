"""専用way値レイヤー（`dedicated_way_value_layer=True`の軸）の、要求の条件の組み立てと地図が塗る値。
状態機械（ルート未確定=ユーザー指定パラメータを全道路へ一律適用／ルート確定後=ルート自身の実値を
ルート線のみへ適用）は軸非依存で、要求の条件（時刻・向き・速度）のうち何が要るかは値を返す
サービスが受け取る条件の型で決まる（`assemble_conditions`）。

**この層で扱うidは軸id（`axis_definitions.axis_id`）であり、材料id
（`material_catalog.py`のキー、例: `wind_drag_ratio`）ではない。**両者は名前空間が
異なる別概念で、配信サービスが返す生値の材料idは`WindWayService.material_id`等が
別に持つ（`transform_dedicated_way_values`が軸定義の評価へ渡す先）。

軸→サービス実装本体の対応は、軸が参照する材料とサービスの`material_id`の突き合わせで
決まる（`services/dedicated_way_values.py: DEDICATED_WAY_VALUE_SERVICES`）。材料ごとの計算ロジック
自体は宣言的に導出できないPythonコードのまま残る。
"""

from collections.abc import Mapping
from dataclasses import MISSING, dataclass, fields
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Literal, TypeVar, cast

from pydantic import Field

from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    BreakpointLinearShape,
    evaluate_axis_values,
)
from app.domain.axis_display import axis_display_for
from app.domain.axis_raw_value import axis_material_shares, raw_value_unit
from app.domain.material_catalog import MATERIAL_CATALOG, is_known_material
from app.domain.strict_model import StrictModel

#: 難易度（0〜100）の段の境界。軸が宣言していないときに使う。**値ではなく等分の規則**
#: ——無次元の得点には目盛りの手掛かりが無いので、3等分する。符号付き材料の段は
#: 軸の折れ線から導く（`_signed_thresholds_from_breakpoints`）ので、ここには持たない。
DEFAULT_DIFFICULTY_BOUNDARIES: tuple[float, ...] = (33, 66)

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

# 地図がその軸について塗る値の種類。`signed_material`は「単一材料の絶対値を評価する軸」
# （勾配のように向きの符号が意味を持つ）で、地図は難易度ではなく符号付きの材料生値を塗る。
# それ以外は軸スタジオのbreakpointsで評価済みの難易度（0〜100）を塗る。ルート確定前の
# 専用way値配信（`transform_dedicated_way_values`）・ルート確定後のルート線色分けの
# 両方がこの1つの判定に従うため、同じ軸の色分けはルートの有無で
# スケールが変わらない。ramp軸（ルート確定前はタイルの重み付き和を塗る軸）は、`axis_display_for`が
# 符号を畳む形を外すため常に`difficulty`で、その配色で塗る。
MapValueKind = Literal["difficulty", "signed_material"]


class DifficultyMapValue(StrictModel):
    """地図が軸の難易度（0〜100）を塗る。"""

    kind: Literal["difficulty"] = "difficulty"


class SignedMaterialMapValue(StrictModel):
    """地図が材料1つの符号付きの生値を塗る。"""

    kind: Literal["signed_material"] = "signed_material"
    #: 生値を塗る材料のid。画面は軸の形から読み直さない。
    material: str


# 塗る値の種類と、種類によって決まる項目を1つにまとめたもの。材料は`signed_material`のときだけ在る。
MapValue = Annotated[DifficultyMapValue | SignedMaterialMapValue, Field(discriminator="kind")]


#: 専用配信の要求が運ぶ条件の名前。`WayValueQuery`の欄の名前で、配信のクエリパラメータの名前でもある。
WayValueConditionName = Literal["at", "bearing_deg", "speed_kmh"]


@dataclass(frozen=True)
class WayValueQuery:
    """専用配信の要求が運ぶ条件。どれも省略されうる——どれが要るかは、値を返すサービスが
    受け取る条件の型（`assemble_conditions`の`kind`）が決める。欄の名前は`WayValueConditionName`。"""

    at: datetime | None
    bearing_deg: float | None
    speed_kmh: float | None


@dataclass(frozen=True)
class MissingConditions:
    """サービスが要る条件のうち、要求に無かったものの名前（`WayValueQuery`の欄の名前）。"""

    names: tuple[str, ...]


_C = TypeVar("_C", bound="DataclassInstance")


def assemble_conditions(kind: type[_C], query: WayValueQuery) -> _C | MissingConditions:
    """サービスが受け取る条件（frozen dataclassの`kind`）を要求から組み立てる。

    `kind`の欄は`WayValueQuery`の同じ名前の欄から取り、既定値の無い欄が要るものになる。
    **方位・速度の欠けを判定するのはここだけ**——サービスは組み立て済みの値だけを受け取るので、
    要る欄は`None`を許さない型のまま届く。地図の配信は欠けを422に、区間インスペクタは
    「データなし」にする。
    """
    kind_fields = fields(kind)
    values = {field.name: getattr(query, field.name) for field in kind_fields}
    missing = tuple(
        field.name for field in kind_fields
        if values[field.name] is None and field.default is MISSING and field.default_factory is MISSING
    )
    if missing:
        return MissingConditions(missing)
    return kind(**values)


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


def _quantity_boundaries(definition: AxisDefinition) -> tuple[list[float], str] | None:
    """難易度の段の境界を、得点を作る前の量（単位つき）で書けるなら、その量と単位。

    書けるのは、得点が単位のある量（`raw_value_unit`）から作られ、その量について狭く増えるときだけ。
    そのときに限り「得点 f(a)以上 f(b)未満」の道と「量 a以上 b未満」の道が一致する——平らな区間や
    下りのある折れ線では、量で書いた段が実際と違う道を指す。境界は折れ線の下端より上・上端以下に
    限る。その外では得点が端に張り付き、量の段と得点の段が一致しない。

    量の境界は、ramp表示の軸ならその境界（初めから量の目盛り）、上書きの無い専用配信の軸なら
    折れ線の節（軸が「どの量から効きが変わるか」を宣言したもの）。専用配信の軸の上書きは得点で
    刻まれているので、量へ戻さない。
    """
    unit = raw_value_unit(definition)
    shape = definition.shape
    if (
        unit is None
        or definition.priority_overrides
        or not isinstance(shape, BreakpointLinearShape)
        or shape.preprocess != "identity"
    ):
        return None
    knots = sorted(shape.breakpoints)
    if any(lower[1] >= upper[1] for lower, upper in zip(knots, knots[1:])):
        return None
    display = axis_display_for(definition)
    if display.kind == "ramp":
        boundaries = list(display.thresholds)
    elif definition.display_thresholds_override is None:
        boundaries = [x for x, _ in knots[1:]]
    else:
        return None
    if not all(knots[0][0] < boundary <= knots[-1][0] for boundary in boundaries):
        return None
    return boundaries, unit


def map_value_thresholds(definition: AxisDefinition) -> list[float]:
    """`map_value_kind`が示すスケールでの段階境界。境界を宣言していない難易度の軸は既定の境界
    （`DEFAULT_DIFFICULTY_BOUNDARIES`）——既定をここで解くので、読む側は既定を持たない。

    **ルート確定前の全道路の塗りと、確定後のルート線は同じ段で塗る。** 前者は材料の
    重み付き和を、後者は0〜100の難易度を塗るため、同じ段を両方の目盛りで言い直す必要が
    ある。ここが返すのは後者の目盛りでの境界で、前者の境界（`axis_display_for`が持つ
    しきい値）を軸の折れ線で写したものである——写さずに渡すと、材料の単位で書かれた境界が
    難易度と比べられ、ルート線が全区間ひとつのバンドへ落ちる。

    `CategoricalShape`の値は初めからスコアと同じスケールのため写さない。ramp表示を持たない
    軸（専用way値配信）の上書きも、地図が塗る値そのものに対する境界なのでそのまま返す。
    上書きの無い専用配信の軸のうち、得点を単位のある量から作る軸は、折れ線の節で切る
    （`_quantity_boundaries`。凡例が段を量で書けるように）。
    """
    display = axis_display_for(definition)
    if display.kind != "ramp":
        override = definition.display_thresholds_override
        if override is not None:
            return list(override)
        if map_value_kind(definition) == "signed_material":
            # `signed_material`は折れ線の軸にしか付かない。
            return _signed_thresholds_from_breakpoints(cast(BreakpointLinearShape, definition.shape))
        quantity = _quantity_boundaries(definition)
        if quantity is not None:
            # 量で書ける軸は折れ線の軸に限る（`_quantity_boundaries`）。
            line = cast(BreakpointLinearShape, definition.shape)
            return [line.score_at(boundary) for boundary in quantity[0]]
        return list(DEFAULT_DIFFICULTY_BOUNDARIES)
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
    return [shape.score_at(threshold) for threshold in display.thresholds]


def map_value(definition: AxisDefinition) -> MapValue:
    """地図がこの軸について塗る値（種類と、`signed_material`なら生値を塗る材料）。"""
    if map_value_kind(definition) != "signed_material":
        return DifficultyMapValue()
    # `signed_material`は折れ線の軸にしか付かない。
    return SignedMaterialMapValue(material=cast(BreakpointLinearShape, definition.shape).terms[0].material)


def map_value_unit(definition: AxisDefinition) -> str:
    """地図の凡例に添える単位。難易度は無次元（空文字）、符号付き材料は材料カタログの単位。"""
    value = map_value(definition)
    return MATERIAL_CATALOG[value.material].unit if isinstance(value, SignedMaterialMapValue) else ""


class MapLegendScale(StrictModel):
    """地図の凡例が段の境界を書く目盛り。塗る値の目盛りと同じとは限らない——量から得点を作る軸は、
    塗るのは得点でも段は量で書く（「66」だけでは雨の量か得点か読めない）。"""

    #: `map_value_thresholds`と同じ件数・同じ順で、各境界をこの目盛りで書いた値。
    boundaries: list[float]
    #: 境界の単位。Noneは、境界が軸の得点（0〜100）であること（単位の無い量の空文字とは別）。
    unit: str | None


def map_legend(definition: AxisDefinition) -> MapLegendScale:
    """地図の凡例が段の境界を書く目盛り。ルート確定の前と後で同じ段を同じ文字で書く。"""
    thresholds = map_value_thresholds(definition)
    if map_value_kind(definition) == "signed_material":
        return MapLegendScale(boundaries=thresholds, unit=map_value_unit(definition))
    quantity = _quantity_boundaries(definition)
    if quantity is None:
        return MapLegendScale(boundaries=thresholds, unit=None)
    boundaries, unit = quantity
    return MapLegendScale(boundaries=boundaries, unit=unit)


def transform_dedicated_way_values(
    definition: AxisDefinition, material_id: str, values: Mapping[str, float | None]
) -> dict[str, float | None]:
    """専用way値配信サービスが返した材料生値（`material_id`の値）を、地図が塗るべき値へ
    変換する。`map_value_kind`が`difficulty`なら軸スタジオの定義（breakpoints・
    priority_overrides）で評価した難易度、`signed_material`なら生値のまま。評価できない
    値（軸が他の材料も必須にしている等）はその道路を結果から除く（地図上は「データなし」）。
    走行方位で決まらない値（None）は、Noneのまま返す（地図上は「向きで決まらない」）。
    タイル内の全道路を1回の配列評価で求める。
    """
    if map_value_kind(definition) == "signed_material":
        return dict(values)
    if any(override.material != material_id for override in definition.priority_overrides):
        # 配信が値を持つのは`material_id`だけで、ほかの材料に置いた0次条件は当たるかどうかを決められない。
        return {}
    known = {key: value for key, value in values.items() if value is not None}
    feature_keys = list(known)
    difficulties = evaluate_axis_values(
        definition, {material_id: [known[key] for key in feature_keys]}, len(feature_keys)
    )
    transformed: dict[str, float | None] = {key: None for key, value in values.items() if value is None}
    transformed.update(
        (key, difficulty) for key, difficulty in zip(feature_keys, difficulties) if difficulty is not None
    )
    return transformed


def displayed_material_ids(weights: Mapping[str, float], lens_axis_id: str | None) -> set[str]:
    """区間表示へ載せるべき材料id。軸名のハードコードは持たない。

    重み>0の公開軸が参照する材料に加え、`lens_axis_id`が符号付き材料の軸を指す場合はその
    材料も**重みに関わらず**含める。符号付き材料は難易度0-100へ変換すると符号（登り/下り）が
    失われるため、地図のレンズは難易度ではなく生値の側を塗る。含めないと、重み0の軸を
    レンズに選んだときだけ表示が欠ける。

    `evaluation.py: route_facing_material_ids`（スコア行列が運ぶ列の既定）とは別物で、
    こちらはそのうちリクエストの好みとレンズに応じて実際に見せる部分集合を決める。
    """
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
