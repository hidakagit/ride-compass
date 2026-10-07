"""地図が軸について塗るもの——塗る値・単位・段の境界・凡例の目盛り——を軸定義から決める。

ルート確定前の全道路の塗り（タイルのramp・専用way値配信）とルート確定後のルート線の色分けは、
どれもここが返す1つの値に従う。同じ軸の色分けは、ルートの有無でスケールも段も変わらない。
"""

from typing import Annotated, Literal, cast

from pydantic import Field, model_validator

from app.domain.axis_definitions import AxisDefinition, BreakpointLinearShape
from app.domain.axis_display import axis_display_for, map_band_labels
from app.domain.axis_raw_value import raw_value_unit
from app.domain.material_catalog import MATERIAL_CATALOG
from app.domain.registry import AxisDisplaySpec
from app.domain.strict_model import StrictModel

#: 難易度（0〜100）の段の境界。軸が宣言していないときに使う。**値ではなく等分の規則**
#: ——無次元の得点には目盛りの手掛かりが無いので、3等分する。符号付き材料の段は
#: 軸の折れ線から導く（`_signed_thresholds_from_breakpoints`）ので、ここには持たない。
DEFAULT_DIFFICULTY_BOUNDARIES: tuple[float, ...] = (33, 66)


class DifficultyMapValue(StrictModel):
    """地図が軸の難易度（0〜100）を塗る。軸スタジオのbreakpointsで評価済みの値で、ramp軸
    （ルート確定前はタイルの重み付き和を塗る軸）は`axis_display_for`が符号を畳む形を外すため
    常にこちら。"""

    kind: Literal["difficulty"] = "difficulty"


class SignedMaterialMapValue(StrictModel):
    """地図が材料1つの符号付きの生値を塗る。単一材料の絶対値を評価する軸（勾配のように
    向きの符号が意味を持つ）で、難易度へ写すと符号が失われる。"""

    kind: Literal["signed_material"] = "signed_material"
    #: 生値を塗る材料のid。画面は軸の形から読み直さない。
    material: str


# 塗る値の種類と、種類によって決まる項目を1つにまとめたもの。材料は`signed_material`のときだけ在る。
MapValue = Annotated[DifficultyMapValue | SignedMaterialMapValue, Field(discriminator="kind")]


class MapLegendScale(StrictModel):
    """地図の凡例が段の境界を書く目盛り。塗る値の目盛りと同じとは限らない——量から得点を作る軸は、
    塗るのは得点でも段は量で書く（「66」だけでは雨の量か得点か読めない）。"""

    #: `MapPaint.thresholds`と同じ件数・同じ順で、各境界をこの目盛りで書いた値。
    boundaries: list[float]
    #: 境界の単位。Noneは、境界が軸の得点（0〜100）であること（単位の無い量の空文字とは別）。
    unit: str | None


class MapPaint(StrictModel):
    """地図がこの軸について塗るもの。段の並び（境界・凡例・タイルの境界・ラベル）はどれも同じ段を
    下から数えて並べ、読む側は段の番号で引き合わせる。"""

    value: MapValue
    #: 地図の凡例に添える単位。難易度は無次元（空文字）、符号付き材料は材料カタログの単位。
    unit: str
    #: `value`の種類が示すスケールでの段の境界。境界を宣言していない難易度の軸は既定の境界
    #: （`DEFAULT_DIFFICULTY_BOUNDARIES`）——既定をここで解くので、読む側は既定を持たない。
    thresholds: list[float]
    #: 凡例が上の境界を書く目盛り。ルート確定の前と後で同じ段を同じ文字で書く。
    legend: MapLegendScale
    #: ルート確定前に全道路をタイルの値で塗る式と、その値（材料の目盛り）での段の境界
    #: （`axis_display_for`）。タイルで塗れない軸（専用way値配信・地図に出ない軸）は`kind="none"`。
    tiles: AxisDisplaySpec
    #: 段ごとの体感ラベル（`map_band_labels`）。上書きの無い軸はNoneで、凡例は段の範囲だけを書く。
    band_labels: list[str] | None

    @model_validator(mode="after")
    def _check_bands_line_up(self) -> "MapPaint":
        """段の並びの件数を揃える。1つでも食い違うと、読む側が同じ番号で引いた境界・ラベルが
        別の段のものになり、ルート確定の前に隠した段が生成後に別の段へ化ける。"""
        bands = len(self.thresholds) + 1
        counts = {"legend boundaries": len(self.legend.boundaries) + 1}
        if self.tiles.kind == "ramp":
            counts["tile thresholds"] = len(self.tiles.thresholds) + 1
        if self.band_labels is not None:
            counts["band labels"] = len(self.band_labels)
        mismatched = {name: count for name, count in counts.items() if count != bands}
        if mismatched:
            raise ValueError(f"map bands do not line up: {bands} bands from thresholds, but {mismatched}")
        return self


def map_paint(definition: AxisDefinition) -> MapPaint:
    """地図がこの軸について塗るもの。"""
    tiles = axis_display_for(definition)
    value = _map_value(definition)
    quantity = _quantity_boundaries(definition, tiles)
    thresholds = _thresholds(definition, tiles, value, quantity)
    band_labels = map_band_labels(definition)
    if isinstance(value, SignedMaterialMapValue):
        unit = MATERIAL_CATALOG[value.material].unit
        legend = MapLegendScale(boundaries=thresholds, unit=unit)
    else:
        unit = ""
        if quantity is None:
            legend = MapLegendScale(boundaries=thresholds, unit=None)
        else:
            legend = MapLegendScale(boundaries=quantity[0], unit=quantity[1])
    return MapPaint(
        value=value, unit=unit, thresholds=thresholds, legend=legend, tiles=tiles, band_labels=band_labels
    )


def _map_value(definition: AxisDefinition) -> MapValue:
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
        return SignedMaterialMapValue(material=shape.terms[0].material)
    return DifficultyMapValue()


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


def _quantity_boundaries(definition: AxisDefinition, tiles: AxisDisplaySpec) -> tuple[list[float], str] | None:
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
    if tiles.kind == "ramp":
        boundaries = list(tiles.thresholds)
    elif definition.display_thresholds_override is None:
        boundaries = [x for x, _ in knots[1:]]
    else:
        return None
    if not all(knots[0][0] < boundary <= knots[-1][0] for boundary in boundaries):
        return None
    return boundaries, unit


def _thresholds(
    definition: AxisDefinition,
    tiles: AxisDisplaySpec,
    value: MapValue,
    quantity: tuple[list[float], str] | None,
) -> list[float]:
    """`value`の種類が示すスケールでの段の境界。

    **ルート確定前の全道路の塗りと、確定後のルート線は同じ段で塗る。** 前者は材料の
    重み付き和を、後者は0〜100の難易度を塗るため、同じ段を両方の目盛りで言い直す必要が
    ある。ここが返すのは後者の目盛りでの境界で、前者の境界（`tiles`のしきい値）を
    軸の折れ線で写したものである——写さずに渡すと、材料の単位で書かれた境界が
    難易度と比べられ、ルート線が全区間ひとつのバンドへ落ちる。

    `CategoricalShape`の値は初めからスコアと同じスケールのため写さない。ramp表示を持たない
    軸（専用way値配信）の上書きも、地図が塗る値そのものに対する境界なのでそのまま返す。
    上書きの無い専用配信の軸のうち、得点を単位のある量から作る軸は、折れ線の節で切る
    （`quantity`。凡例が段を量で書けるように）。
    """
    if tiles.kind != "ramp":
        override = definition.display_thresholds_override
        if override is not None:
            return list(override)
        if isinstance(value, SignedMaterialMapValue):
            # `signed_material`は折れ線の軸にしか付かない。
            return _signed_thresholds_from_breakpoints(cast(BreakpointLinearShape, definition.shape))
        if quantity is not None:
            # 量で書ける軸は折れ線の軸に限る（`_quantity_boundaries`）。
            line = cast(BreakpointLinearShape, definition.shape)
            return [line.score_at(boundary) for boundary in quantity[0]]
        return list(DEFAULT_DIFFICULTY_BOUNDARIES)
    shape = definition.shape
    if not isinstance(shape, BreakpointLinearShape):
        return list(tiles.thresholds)
    if shape.preprocess != "identity":
        # 符号を畳む軸の折れ線は材料の目盛りを写せない（負の境界が正の側へ折り返る）。
        # 地図に塗れる軸を符号を畳まない形に限るのは`axis_display_for`で、そちらが変わったときに
        # ルート線が全区間同じ帯へ黙って落ちないよう、ここで止める。
        raise ValueError(
            f"axis '{definition.axis_id}': ramp display on a shape that folds the sign "
            f"(preprocess={shape.preprocess!r}); its thresholds cannot be mapped"
        )
    return [shape.score_at(threshold) for threshold in tiles.thresholds]
