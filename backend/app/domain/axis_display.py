"""軸を地図にどう出すかを、軸の形と材料の性質から決める。

軸が参照する材料がすべてMVTタイルへ焼き込み済みなら、地図が塗る値の式
（`registry.py: TileInputSpec`）と段の境界を導ける。導けない軸は`kind="none"`で地図に
出ない。導ける形の一覧は`docs/modules/backend/axis-studio.md`「地図表示ルールの自動導出」
節にある。

`MaterialTerm.material`が材料idではなく他の軸idを指す場合は、参照先を再帰的に解決して
フラットな`tile_inputs`へ展開する。

タイルの生値と材料のスケールが実行時にしか決まらない材料は、変換係数を`weight`へ静的に
焼き込めないため`TileInputSpec.needs_runtime_scale`で印だけ付ける。係数そのものは
`GET /api/axis-catalog`が返す`material_runtime_scales`をフロントの式が掛け合わせる。

段の境界は軸の折れ点のx値をそのまま使うため粗くなることがあり、
`AxisDefinition.display_thresholds_override`で上書きできる。
"""

from itertools import combinations
from typing import cast


from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
)
from app.domain.axis_templates import evaluate_breakpoint_linear
from app.domain.material_catalog import MATERIAL_CATALOG, MaterialSpec
from app.domain.registry import AxisDisplaySpec, TileInputSpec
from app.domain.strict_model import StrictModel


class RampInputs(StrictModel):
    tile_inputs: list[TileInputSpec]
    thresholds: list[float]


def _adjacent_midpoint_thresholds(scores: list[float]) -> list[float]:
    ordered = sorted(set(scores))
    return [(a + b) / 2 for a, b in zip(ordered, ordered[1:])]


def _drop_thresholds_that_share_a_score(
    thresholds: list[float], shape: "BreakpointLinearShape"
) -> list[float]:
    """地図に出す段は、評価が区別できる差より細かくしない。

    区別できない差に境界を引くと、色は変わるのに評価は同じという見分けを地図が見せる。
    さらにルート線は難易度で塗るためその段を作れず、ルート前後で段の数が食い違う
    （`domain/dynamic_way_values.py: map_value_thresholds`と対で読むこと）。
    """
    kept: list[float] = []
    seen: list[float] = []
    for threshold in thresholds:
        total = abs(threshold) if shape.preprocess == "abs" else threshold
        score = round(evaluate_breakpoint_linear(total, shape.breakpoints), 1)
        if seen and score <= seen[-1]:
            continue
        seen.append(score)
        kept.append(threshold)
    return kept


def _boolean_terms_thresholds(weights: list[float], cap: float | None) -> list[float]:
    """真偽値の項は該当時weight・非該当時0の2値しか取らないため、軸が取りうる合計値は
    部分和に限られる。連続値と違って中間の値が現れないので、境界はその実現値の間に引く。
    """
    sums: set[float] = {0.0}
    for r in range(1, len(weights) + 1):
        for combo in combinations(weights, r):
            total = sum(combo)
            if cap is not None:
                total = min(total, cap)
            sums.add(total)
    return _adjacent_midpoint_thresholds(list(sums))


def _boolean_score_tile_input(spec: MaterialSpec, true_score: float, false_score: float) -> TileInputSpec:
    """真偽値の材料をタイル入力へ写す。**真偽値の入力を作るのはここだけ**——タイルに値が
    無いことが「不明」を意味するか「false」を意味するかは材料の`bool_default`だけが知って
    おり、組み立てが2か所に分かれると片方が灰色の不明帯を落とす。
    """
    has_unknown_fallback = spec.bool_default == "nan"
    assert spec.tile_property is not None  # 呼び出し元で保証済み
    return TileInputSpec(
        property=spec.tile_property,
        boolean=True,
        true_value=true_score,
        false_value=false_score,
        has_unknown_fallback=has_unknown_fallback,
    )


def _rescale_tile_input(tile_input: TileInputSpec, weight: float) -> TileInputSpec:
    """`TileInputSpec`は寄与値の置き場が形によって違う——カテゴリと真偽値は寄与値そのものを
    持ち、数値はタイル生値に掛ける倍率を`weight`に持つ。外側の重みは置き場の側へ乗せる。
    """
    if tile_input.categories is not None:
        return tile_input.model_copy(
            update={"categories": {value: score * weight for value, score in tile_input.categories.items()}}
        )
    if tile_input.boolean:
        return tile_input.model_copy(
            update={"true_value": tile_input.true_value * weight, "false_value": tile_input.false_value * weight}
        )
    return tile_input.model_copy(update={"weight": tile_input.weight * weight})


def _resolve_referenced_axis_tile_input(axis_id: str, weight: float, visited: frozenset[str]) -> TileInputSpec | None:
    """参照先の軸を1件のタイル入力へ畳めるのは、地図側が同じ値を再現できるときだけ。

    カテゴリの軸は評価時の値が`mapping`そのもので追加の変換が無いため、そのまま畳める。
    折れ点の軸は`TileInputSpec.breakpoints`が「タイル生値へ折れ点変換を当てる」形しか
    表現できないため、単項かつ内側の重みが1のときに限る——複数項や重み付きは「重ねてから
    折れ点」という順序になり、この形では書けない。真偽値の材料も折れ点変換の対象外。
    """
    if axis_id in visited:
        return None
    referenced = AXIS_DEFINITIONS.get(axis_id)
    if referenced is None:
        return None
    shape = referenced.shape
    if isinstance(shape, CategoricalShape):
        ramp = _derive_ramp_inputs(referenced, visited)
        if ramp is None or len(ramp.tile_inputs) != 1:
            return None
        return _rescale_tile_input(ramp.tile_inputs[0], weight)
    if isinstance(shape, BreakpointLinearShape):
        if shape.preprocess != "identity" or len(shape.terms) != 1:
            return None
        inner_term = shape.terms[0]
        if inner_term.weight != 1.0:
            return None
        inner_spec = MATERIAL_CATALOG.get(inner_term.material)
        if inner_spec is None:
            # 内側がさらに軸を指す2段以上のネストは畳めない。
            return None
        if (
            inner_spec.tile_property is None
            or inner_spec.tile_property_direction_dependent
            or inner_spec.tile_property_needs_runtime_scale
            or inner_spec.dtype == "boolean"
        ):
            return None
        return TileInputSpec(property=inner_spec.tile_property, breakpoints=shape.breakpoints, weight=weight)
    return None


def _derive_ramp_inputs(definition: AxisDefinition, visited_axes: frozenset[str] = frozenset()) -> RampInputs | None:
    visited = visited_axes | {definition.axis_id}

    materials = definition.materials
    specs: dict[str, MaterialSpec | None] = {m: MATERIAL_CATALOG.get(m) for m in materials}
    for material_id, spec in specs.items():
        if spec is None:
            if material_id not in AXIS_DEFINITIONS:
                return None
            # 軸参照。参照先の材料は`_resolve_referenced_axis_tile_input`が辿って調べる。
            continue
        if spec.tile_property is None or spec.tile_property_direction_dependent:
            return None
        # 実行時スケールが要る材料はここでは弾かない——タイルの生値自体は使えるため。

    shape = definition.shape

    if isinstance(shape, CategoricalShape):
        # 分類の軸が指せる先は材料だけ。折れ点の軸と違って参照先の軸を解決しないのは、
        # 引いてくる値が連続値の得点になり、対応表のキーと噛み合わないため。
        spec = specs.get(shape.material)
        if spec is None or spec.tile_property is None:
            return None
        if set(shape.mapping.keys()) == {True, False}:
            true_score = shape.mapping[True]
            false_score = shape.mapping[False]
            lower, upper = sorted([true_score, false_score])
            tile_input = _boolean_score_tile_input(spec, true_score, false_score)
            return RampInputs(tile_inputs=[tile_input], thresholds=[(lower + upper) / 2])
        if any(isinstance(key, bool) for key in shape.mapping):
            return None
        str_mapping = cast(dict[str, float], dict(shape.mapping))
        distinct_scores = sorted(set(str_mapping.values()))
        if len(distinct_scores) < 2:
            # 全値が同じ点数なら境界が作れない。
            return None
        return RampInputs(
            tile_inputs=[
                TileInputSpec(
                    property=spec.tile_property,
                    categories=str_mapping,
                    # 評価側は未登録の値を「評価不能」とするため、地図も寄与0ではなく不明へ倒す。
                    has_unknown_fallback=True,
                )
            ],
            thresholds=_adjacent_midpoint_thresholds(distinct_scores),
        )

    if isinstance(shape, BreakpointLinearShape):
        if shape.preprocess != "identity":
            # 符号を畳む前処理を地図側の式が表現できない。
            return None
        # 材料の欠損の扱いが評価側と地図側で食い違う（docs/modules/backend/axis-studio.md
        # 「暗黙の前提」節）。地図は欠損を寄与0として塗るため、評価不能な区間が良好に見える。
        tile_inputs = []
        for term in shape.terms:
            spec = specs.get(term.material)
            if spec is None:
                resolved = _resolve_referenced_axis_tile_input(term.material, term.weight, visited)
                if resolved is None:
                    return None
                tile_inputs.append(resolved)
                continue
            assert spec.tile_property is not None  # 上のspecsループで確認済み
            if spec.dtype == "boolean":
                # 該当時term.weight・非該当時0の2値。
                tile_inputs.append(_boolean_score_tile_input(spec, term.weight, 0.0))
            else:
                # 実行時スケールが要る材料もここで受け入れる。weightは元のterm.weightの
                # まま静的に確定し、実行時スケール定数はフロント側が
                # TileInputSpec.needs_runtime_scaleを見て追加で掛け合わせる。
                tile_inputs.append(
                    TileInputSpec(
                        property=spec.tile_property,
                        weight=term.weight,
                        needs_runtime_scale=spec.tile_property_needs_runtime_scale,
                    )
                )

        if all((s := specs.get(term.material)) is not None and s.dtype == "boolean" for term in shape.terms):
            # 部分和は2^N通りある。GUIは材料の天井で12を超えないが、APIは直接叩ける。
            if len(shape.terms) > 12:
                return None
            cap = shape.breakpoints[-1][0]
            thresholds = _boolean_terms_thresholds([term.weight for term in shape.terms], cap)
        else:
            # 評価側の重み付き和と地図側が塗る値は同じ演算なので、折れ点のx値がそのまま
            # 境界になる。
            thresholds = [bp[0] for bp in shape.breakpoints[1:]]
        return RampInputs(tile_inputs=tile_inputs, thresholds=thresholds)

    return None


def axis_display_for(definition: AxisDefinition) -> AxisDisplaySpec:
    """軸を地図にどう出すか。塗れない軸は`kind="none"`（地図に出ない）。

    段の境界は上書き（`display_thresholds_override`）があればそれを、無ければ自動導出の
    値を使い、どちらも折れ線が同じスコアへ写す境界を落とす。**段を決めるのはここだけ**で、
    ルート確定後のルート線の境界（`dynamic_way_values.py: map_value_thresholds`）も
    ここの値を折れ線で写して作る——段の識別子は前後で同じ保存先へ書かれるため、数が違うと
    ルート前に隠した段が生成後に別の段へ化ける。
    """
    ramp = _derive_ramp_inputs(definition)
    if ramp is None:
        return AxisDisplaySpec(kind="none", label=definition.label)
    thresholds = (
        list(definition.display_thresholds_override)
        if definition.display_thresholds_override is not None
        else list(ramp.thresholds)
    )
    shape = definition.shape
    if isinstance(shape, BreakpointLinearShape):
        thresholds = _drop_thresholds_that_share_a_score(thresholds, shape)
    return AxisDisplaySpec(
        kind="ramp", label=definition.label, tile_inputs=ramp.tile_inputs, thresholds=thresholds
    )
