"""軸の値を人へ出すときに何を添えるか。

得点（0〜100）は目盛りの引き方に依存する相対評価のため、軸単体では経路を判断できない。
単位が定まる軸には生値を単位付きで添え、定まらない軸には材料の内訳を添える。
"""

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import model_validator

from app.domain.axis_definitions import (
    AxisDefinition,
    BreakpointLinearShape,
)
from app.domain.material_catalog import MATERIAL_CATALOG
from app.domain.strict_model import StrictModel


def raw_value_unit(definition: AxisDefinition) -> str | None:
    """折れ点を通す前の重み付き和に付けられる単位。付けられなければNone。

    重みが1でない項があると、和は材料の値をスケールし直した量になり材料の単位では
    読めない（「1kmあたり1.5回として数えた踏切」を含む和は実際の回/kmではない）。

    単位が揃っていても和の意味は保証されない。%・km/h・倍率のような割合・率は母数の
    違うものを足しても何も表さないため、2項以上では`additive`な材料だけを認める。
    項が1つならそもそも和ではないので、この条件は課さない。
    """
    shape = definition.shape
    if not isinstance(shape, BreakpointLinearShape):
        return None
    specs = []
    for term in shape.terms:
        if term.weight == 0:
            continue
        if term.weight != 1.0:
            return None
        spec = MATERIAL_CATALOG.get(term.material)
        if spec is None or not spec.unit:
            return None
        specs.append(spec)
    if len({spec.unit for spec in specs}) != 1:
        return None
    if len(specs) > 1 and not all(spec.additive for spec in specs):
        return None
    return specs[0].unit


class RawValueUnits(StrictModel):
    """軸の生値に添える単位。"""

    #: 折れ点を通す前の重み付き和の単位（`raw_value_unit`）。付けられなければNone。
    unit: str | None
    #: 生値へ走行距離を掛けた総量の単位。生値の単位が無い軸と、総量を出しても読み手の判断が
    #: 変わらない軸はNone。
    total_unit: str | None

    @model_validator(mode="after")
    def _check_total_has_a_rate(self) -> "RawValueUnits":
        """総量は生値に距離を掛けたものなので、生値の単位が無いのに総量の単位だけがあると、
        読む側は掛ける元の値の無い総量を出す。"""
        if self.total_unit is not None and self.unit is None:
            raise ValueError(f"total unit {self.total_unit!r} without a raw value unit")
        return self


def raw_value_units(definition: AxisDefinition) -> RawValueUnits:
    """軸の生値と、それへ走行距離を掛けた総量に添える単位。"""
    unit = raw_value_unit(definition)
    return RawValueUnits(unit=unit, total_unit=None if unit is None else _total_unit(definition))


def _total_unit(definition: AxisDefinition) -> str | None:
    """生値の単位がある軸で、総量に付けられる単位。出す意味が無ければNone。

    「0.8回/km」に距離を掛けた「約26回」は何回止まるかを答えるが、「151度/km」に掛けた
    「約3322度」は比べる尺度が無く読み手の判断を変えない。単位が「◯◯/km」であることを
    条件にすると両者が同じ扱いになるため、出す意味があるかは材料の`total_unit`が持つ。
    """
    shape = definition.shape
    assert isinstance(shape, BreakpointLinearShape)  # raw_value_unitが非Noneなら成り立つ
    total_units = {
        spec.total_unit
        for term in shape.terms
        if term.weight != 0 and (spec := MATERIAL_CATALOG.get(term.material)) is not None
    }
    if len(total_units) != 1:
        return None
    return total_units.pop()


@dataclass(frozen=True, slots=True)
class AxisMaterialShare:
    """軸が参照する材料1件と、それが軸の生値に占める正規化重み。"""

    material_id: str
    #: 各階層で `|w| / Σ|w|` を取り、根から葉まで掛け合わせた値（0〜1）。
    share: float
    #: 根の軸からの探索の深さ（直接のtermが0）。同率の並び替えに使う。
    depth: int


def _shape_terms(definition: AxisDefinition) -> list[tuple[str, float]]:
    """カテゴリの軸は重みの概念を持たないため、重み1の1項として扱う。"""
    shape = definition.shape
    if isinstance(shape, BreakpointLinearShape):
        return [(term.material, term.weight) for term in shape.terms]
    return [(shape.material, 1.0)]


def axis_material_shares(
    definition: AxisDefinition, definitions: Mapping[str, AxisDefinition]
) -> list[AxisMaterialShare]:
    """単位が定まらない軸のために、軸を材料まで分解して占有率を出す。参照先の軸は`definitions`から引く。

    辿る先は必ず材料で、途中の軸の得点は結果に含めない——較正に依存する数字を内訳へ
    混ぜると、この関数が避けようとしている問題が入れ子で再発する。

    **重みは階層ごとに正規化してから掛ける。** 内部軸の折れ点・対応表は非線形変換なので、
    外側の重み1.0と内側の重み1.0は別のスケールにあり、生の重みを階層をまたいで掛けても
    意味が無い。同じshapeの中の項どうしだけは、重み付き和が得点として意味を持つよう
    作者が決めた値なので比較できる。

    材料1件へ分解される軸は空を返す。分解しても情報が増えず、符号を畳む前処理は材料の
    単位では効かないため、登りと下りが相殺された平均を見せることになる。
    """
    shares: dict[str, AxisMaterialShare] = {}

    def walk(current: AxisDefinition, inherited: float, depth: int, visited: frozenset[str]) -> None:
        if current.axis_id in visited:
            return
        next_visited = visited | {current.axis_id}
        terms = [(ref, weight) for ref, weight in _shape_terms(current) if weight != 0.0]
        total = sum(abs(weight) for _, weight in terms)
        if total == 0:
            return
        for ref, weight in terms:
            share = inherited * abs(weight) / total
            referenced_axis = definitions.get(ref)
            if referenced_axis is not None:
                walk(referenced_axis, share, depth + 1, next_visited)
            elif ref not in shares:
                shares[ref] = AxisMaterialShare(material_id=ref, share=share, depth=depth)

    walk(definition, 1.0, 0, frozenset())
    if len(shares) <= 1:
        return []
    # 挿入順（＝定義順の深さ優先）を保つ安定ソートのため、キーは share と depth だけにする。
    return sorted(shares.values(), key=lambda entry: (-entry.share, entry.depth))
