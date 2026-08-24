"""地図表示ルール（kind=ramp）の自動導出（改善計画T278）。

`AXIS_DEFINITIONS`の軸が参照する材料（`domain/material_catalog.py: MATERIAL_CATALOG`）が
全てMVTタイルへ焼き込み済み（`tile_property`保持）であれば、その軸の地図ramp表示
（`registry.py: TileInputSpec`のΣproperty×weight・真偽値のcase分岐）を自動導出できる。

**安全に自動導出できるケースに限定する**（改善計画T278調査で判明した制約）:
- `CategoricalShape`（真偽値材料1件）: 2値の中間点を閾値とする2段階ramp。
- `FlagSumShape`（真偽値フラグN件）: 達成しうる合計値（部分和の全組合せ、cap適用後）の
  隣接中間点を閾値とする。
- `BreakpointLinearShape`で単一材料・weight=1.0・preprocess="identity"の場合のみ:
  既存breakpointsのx値（先頭除く）をそのまま閾値に流用。

それ以外（複数材料の重み付き結合・abs前処理・タイル非依存材料・実行時スケール変換が
必要な材料[`tile_property_needs_runtime_scale=True`]を含む軸、他の軸を参照する
`MaterialTerm`を含む軸）は`None`を返す（自動導出対象外——地図に出ない。既存の
kind="none"軸を壊さない安全側の判断。改善計画T298: kind="bespoke"は利用ゼロのため
Literal自体を削除済み、registry.py参照）。

現行7軸のうち、この関数が実際に使われるのは`surface_q`・`night`のみ（`registry_defaults.py`
参照）。`stop_density`（複数材料の重み付き結合）・`accident`（材料が年正規化済みで
タイル生値とスケールが異なる、静的な変換係数を持てない）・`car_stress`（改善計画T292:
内部軸6つを参照するBreakpointLinearShapeのため、他の軸を参照するMaterialTermをこの関数は
解決できない）は対象外のまま手書きのdisplayを維持する（car_stressもT292以降kind="ramp"
だが、tile_inputsはこの関数ではなくregistry_defaults.pyへ直接手書きしている
——stop_density/accidentと同じ前例）。
"""

from itertools import combinations

from pydantic import BaseModel

from app.domain.axis_definitions import AxisDefinition, BreakpointLinearShape, CategoricalShape, FlagSumShape
from app.domain.material_catalog import MATERIAL_CATALOG
from app.domain.registry import TileInputSpec


class RampInputs(BaseModel):
    tile_inputs: list[TileInputSpec]
    thresholds: list[float]


def _flag_sum_thresholds(points: list[float], cap: float | None) -> list[float]:
    """達成しうる合計値（空集合込みの全部分和、cap適用後）の隣接中間点を閾値として返す。"""
    sums: set[float] = {0.0}
    for r in range(1, len(points) + 1):
        for combo in combinations(points, r):
            total = sum(combo)
            if cap is not None:
                total = min(total, cap)
            sums.add(total)
    ordered = sorted(sums)
    return [(a + b) / 2 for a, b in zip(ordered, ordered[1:])]


def derive_ramp_inputs(definition: AxisDefinition) -> RampInputs | None:
    materials = definition.materials
    specs = {m: MATERIAL_CATALOG.get(m) for m in materials}
    if any(
        spec is None or spec.tile_property is None or spec.tile_property_needs_runtime_scale
        for spec in specs.values()
    ):
        return None

    shape = definition.shape

    if isinstance(shape, CategoricalShape):
        spec = specs[shape.material]
        assert spec is not None and spec.tile_property is not None
        # 改善計画T292: CategoricalShape.mappingはstr多値材料（highway/bicycle_infra等、
        # 3値以上）にも対応したが、2色ramp（true_score/false_score）はbool2値材料
        # 専用の表現のため、str多値のmappingはramp化不可（None、qualitative色分けは
        # 別の自動導出の対象——フロント表示層の汎用化タスクで扱う）とする。
        if set(shape.mapping.keys()) != {True, False}:
            return None
        true_score = shape.mapping[True]
        false_score = shape.mapping[False]
        lower, upper = sorted([true_score, false_score])
        return RampInputs(
            tile_inputs=[
                TileInputSpec(
                    property=spec.tile_property,
                    boolean=True,
                    invert=spec.tile_property_inverted,
                    true_value=true_score,
                    false_value=false_score,
                    # レビュー指摘の修正: CategoricalShapeは2値マッピング（true_score/
                    # false_score）だが、タイル欠損は「trueでもfalseでもない不明」を表す
                    # （registry.py: TileInputSpec.has_unknown_fallbackのdocstring参照）。
                    # 欠損時は自動的にfalse_value（多くの軸で「悪い」側のスコア）へ
                    # 落ちてしまい、backend評価側（evaluate_categoricalは欠損をNone扱い）
                    # と矛盾するため、フロントで灰色「不明」表示へ振り分けさせる。
                    has_unknown_fallback=True,
                )
            ],
            thresholds=[(lower + upper) / 2],
        )

    if isinstance(shape, FlagSumShape):
        tile_inputs = []
        for material, points in shape.flags:
            spec = specs[material]
            assert spec is not None and spec.tile_property is not None
            tile_inputs.append(
                TileInputSpec(
                    property=spec.tile_property,
                    boolean=True,
                    invert=spec.tile_property_inverted,
                    true_value=points,
                    false_value=0.0,
                )
            )
        thresholds = _flag_sum_thresholds([points for _, points in shape.flags], shape.cap)
        return RampInputs(tile_inputs=tile_inputs, thresholds=thresholds)

    if isinstance(shape, BreakpointLinearShape):
        if len(shape.terms) != 1 or shape.terms[0].weight != 1.0 or shape.preprocess != "identity":
            return None
        spec = specs[shape.terms[0].material]
        assert spec is not None and spec.tile_property is not None
        if spec.tile_property_inverted:
            # tile_property_inverted（否定）はboolean材料の「no_lit⟵litの否定」を表す
            # ためだけに定義された概念で、数値材料に対する「反転」の意味は未定義
            # （フロントのbuildAxisRampValueExpressionも数値側の分岐ではinvertを一切
            # 読まない）。レビュー指摘で発見: 以前はここでinvertを無視したまま
            # weight=1.0で素通りしており、将来tile_property_inverted=Trueの数値材料が
            # 追加された場合に色分けが反転したまま気づかれない欠陥があった。
            # 数値材料の反転は未対応のため、安全側でramp化不可（None）とする。
            return None
        thresholds = [bp[0] for bp in shape.breakpoints[1:]]
        return RampInputs(
            tile_inputs=[TileInputSpec(property=spec.tile_property, weight=1.0)],
            thresholds=thresholds,
        )

    return None
