"""軸の値を人へ出すときに何を添えるか。

得点（0〜100）は目盛りの引き方に依存する相対評価のため、軸単体では経路を判断できない。
単位が定まる軸には生値を単位付きで添え、定まらない軸には材料の内訳を添える。
"""

from collections.abc import Mapping
from dataclasses import dataclass

from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    BreakpointLinearShape,
)
from app.domain.dynamic_way_values import map_value_kind
from app.domain.material_catalog import MATERIAL_CATALOG, is_known_material


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


def raw_value_total_unit(definition: AxisDefinition) -> str | None:
    """生値へ走行距離を掛けた総量に付けられる単位。出す意味が無ければNone。

    「0.8回/km」に距離を掛けた「約26回」は何回止まるかを答えるが、「151度/km」に掛けた
    「約3322度」は比べる尺度が無く読み手の判断を変えない。単位が「◯◯/km」であることを
    条件にすると両者が同じ扱いになるため、出す意味があるかは材料の`total_unit`が持つ。
    """
    if raw_value_unit(definition) is None:
        return None
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


def axis_material_shares(definition: AxisDefinition) -> list[AxisMaterialShare]:
    """単位が定まらない軸のために、軸を材料まで分解して占有率を出す。

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
            referenced_axis = AXIS_DEFINITIONS.get(ref)
            if referenced_axis is not None:
                walk(referenced_axis, share, depth + 1, next_visited)
            elif ref not in shares:
                shares[ref] = AxisMaterialShare(material_id=ref, share=share, depth=depth)

    walk(definition, 1.0, 0, frozenset())
    if len(shares) <= 1:
        return []
    # 挿入順（＝定義順の深さ優先）を保つ安定ソートのため、キーは share と depth だけにする。
    return sorted(shares.values(), key=lambda entry: (-entry.share, entry.depth))


def displayed_material_ids(weights: Mapping[str, float], lens_axis_id: str | None = None) -> set[str]:
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
