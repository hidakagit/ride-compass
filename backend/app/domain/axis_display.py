"""地図表示ルール（kind=ramp）の自動導出（改善計画T278、T308で一般化）。

`AXIS_DEFINITIONS`の軸が参照する材料（`domain/material_catalog.py: MATERIAL_CATALOG`）が
全てMVTタイルへ焼き込み済み（`tile_property`保持）であれば、その軸の地図ramp表示
（`registry.py: TileInputSpec`のΣproperty×weight・真偽値のcase分岐）を自動導出できる。

**安全に自動導出できるケースに限定する**（改善計画T278調査・T308一般化で判明した制約）:
- `CategoricalShape`（真偽値材料1件、またはstr N値材料1件）: 真偽値は2値の中間点、
  str N値は達成しうるスコアの隣接中間点を閾値とする（改善計画T308でstr N値も対応）。
- `FlagSumShape`（真偽値フラグN件）: 達成しうる合計値（部分和の全組合せ、cap適用後）の
  隣接中間点を閾値とする。
- `BreakpointLinearShape`で`preprocess="identity"`の場合（改善計画T308で単一材料・
  weight=1.0限定を撤廃）: `total = Σ(material_value × term.weight)`という評価側の量は、
  termごとに`TileInputSpec(property, weight=term.weight)`を並べてフロントが計算する量と
  完全に同一（同じ材料・同じ重み・同じ演算）であるため、`shape.breakpoints`のx値
  （先頭除く）は元のterm数・重みに関わらずそのまま妥当な閾値として流用できる
  （近似ではなく数学的に厳密な流用）。

それ以外（`preprocess="abs"`[フロントの`buildAxisRampValueExpression`が未対応]・
タイル非依存材料・実行時スケール変換が必要な材料[`tile_property_needs_runtime_scale=True`]・
方向依存材料[`tile_property_direction_dependent=True`、改善計画T308]を含む軸、
他の軸を参照する`MaterialTerm`を含む軸）は`None`を返す（自動導出対象外——地図に出ない。
既存のkind="none"軸を壊さない安全側の判断。改善計画T298: kind="bespoke"は利用ゼロのため
Literal自体を削除済み、registry.py参照）。

この関数が対象外と判定した軸は、`AxisDefinition.display_override`（軸自身が持つ手書きの
`AxisDisplaySpec`、改善計画T310）が設定されていれば`axis_display_for()`がそちらを使う
（統計的に閾値を調整したい軸・他の軸を参照する材料構成でこの関数が解決できない軸向け。
以前は軸id→値のハードコード辞書だったが、他の既存軸限定の特別扱いと同じ理由で軸自身の
データへ移設した）。`display_override`も未設定なら`kind="none"`（地図に出ない）。

**T308での用途拡大**: 上記の一般化により、軸スタジオ（GUI）で作成された軸
（複数材料の重み付き結合や、highway/bicycle_infra等のstr N値カテゴリカル材料を使う軸を
含む）も、タイル焼き込み済み・実行時スケール変換不要・方向非依存の材料だけで構成されて
いれば、個別の手書き登録なしに自動導出の対象になる（本モジュールの`axis_display_for()`が
呼び出し元、docs/decisions/t308-axis-map-display-auto-derivation.md参照）。
"""

from itertools import combinations
from typing import cast

from pydantic import BaseModel

from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    FlagSumShape,
)
from app.domain.material_catalog import MATERIAL_CATALOG
from app.domain.registry import AxisDisplaySpec, TileInputSpec


class RampInputs(BaseModel):
    tile_inputs: list[TileInputSpec]
    thresholds: list[float]


def _adjacent_midpoint_thresholds(scores: list[float]) -> list[float]:
    """スコアの集合から、ソート済み隣接値の中間点を閾値として返す（改善計画T308、
    bool2値の`[(lower+upper)/2]`をN値へ一般化したもの）。"""
    ordered = sorted(set(scores))
    return [(a + b) / 2 for a, b in zip(ordered, ordered[1:])]


def _flag_sum_thresholds(points: list[float], cap: float | None) -> list[float]:
    """達成しうる合計値（空集合込みの全部分和、cap適用後）の隣接中間点を閾値として返す。

    コードレビュー指摘の修正: 末尾の「sorted→隣接中間点」ロジックが
    `_adjacent_midpoint_thresholds`と重複していたため、達成しうる合計値の集合を
    求めるところまでを担い、閾値化自体は共通関数へ委ねる（将来中間点の計算式
    [丸め・重み付け等]を変更する際、片方だけ直し忘れて挙動が乖離するのを防ぐ）。
    """
    sums: set[float] = {0.0}
    for r in range(1, len(points) + 1):
        for combo in combinations(points, r):
            total = sum(combo)
            if cap is not None:
                total = min(total, cap)
            sums.add(total)
    return _adjacent_midpoint_thresholds(list(sums))


def derive_ramp_inputs(definition: AxisDefinition) -> RampInputs | None:
    materials = definition.materials
    specs = {m: MATERIAL_CATALOG.get(m) for m in materials}
    if any(
        spec is None
        or spec.tile_property is None
        or spec.tile_property_needs_runtime_scale
        or spec.tile_property_direction_dependent
        for spec in specs.values()
    ):
        return None

    shape = definition.shape

    if isinstance(shape, CategoricalShape):
        spec = specs[shape.material]
        assert spec is not None and spec.tile_property is not None
        if set(shape.mapping.keys()) == {True, False}:
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
        # 改善計画T308: bool2値以外（str N値）のramp化。`registry.py: TileInputSpec.
        # categories`が既にN値文字列材料に対応済みのため（car_stress_highway_base等の
        # 手書き登録が実例）、bool2値と同じ理屈で一般化する。
        if any(isinstance(key, bool) for key in shape.mapping):
            # bool/strの混在は想定外の構成（現行AXIS_DEFINITIONSに実例なし）。安全側でNone。
            return None
        str_mapping = cast(dict[str, float], dict(shape.mapping))
        distinct_scores = sorted(set(str_mapping.values()))
        if len(distinct_scores) < 2:
            # 全値が同一スコアなら色分けする意味が無い（閾値を作れない）。
            return None
        return RampInputs(
            tile_inputs=[
                TileInputSpec(
                    property=spec.tile_property,
                    categories=str_mapping,
                    # 改善計画T297の教訓: `evaluate_categorical`は未登録値をNone（評価不能）
                    # として扱うため、地図側も「未登録値=寄与0」ではなく「不明」（灰色）へ
                    # 倒す。bool2値と同じくhas_unknown_fallback=True固定にする。
                    has_unknown_fallback=True,
                )
            ],
            thresholds=_adjacent_midpoint_thresholds(distinct_scores),
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
        if shape.preprocess != "identity":
            # abs前処理はフロントのbuildAxisRampValueExpressionが未対応（改善計画T308の
            # スコープ外、フォローアップ）。安全側でNone。
            return None
        # コードレビュー指摘（既知の制約、意図的に許容）: 評価側（evaluate_axis_scalar/
        # evaluate_axis_array）はrequired=Trueの材料が欠損していれば軸全体をNone/NaN
        # （評価不能）にするが、フロント側のΣ(property×weight)expression
        # （buildAxisRampValueExpression）はタイルプロパティ欠損を寄与0として扱う
        # （coalesce）。required=Falseの材料は「欠損時は寄与0」が評価側の意味論そのものの
        # ため両者は一致するが、required=Trueの材料ではこの2つの意味論が食い違い、本来
        # 「評価不能」な区間が地図上では「評価済みで良好（緑）」に誤表示されうる
        # （TileInputSpecには数値材料の「不明」表現手段が無い——has_unknown_fallbackは
        # 真偽値/N値カテゴリカル材料専用、buildAxisRampUnknownExpression参照）。
        # required=Trueの材料を一律に自動導出対象外とする案も検討したが、T308時点で
        # stop_density（`stop_count_per_km`がrequired=True）を含め意図的に許容する設計と
        # してテスト化済み（test_single_term_breakpoint_linear_reuses_breakpoints_as_
        # thresholds・test_multi_term_breakpoint_linear_derives_ramp_with_coarser_
        # thresholds・test_axis_display_for_derives_gui_created_axis_display参照）ため、
        # 既存の挙動を変えない。実務上は「必須材料がway単位の事前集計で欠損する」ケース
        # 自体が稀（way_attribute_countsは欠損時0埋めが基本）なため実害は限定的だが、
        # GUI作成軸でrequired=True材料が実際にタグ欠損しやすい場合は、この不整合を
        # 認識した上でdisplay_override（軸自身の手書き上書き）を検討すること。
        tile_inputs = []
        for term in shape.terms:
            spec = specs[term.material]
            assert spec is not None and spec.tile_property is not None
            if spec.tile_property_inverted:
                # tile_property_inverted（否定）はboolean材料の「no_lit⟵litの否定」を表す
                # ためだけに定義された概念で、数値材料に対する「反転」の意味は未定義
                # （フロントのbuildAxisRampValueExpressionも数値側の分岐ではinvertを一切
                # 読まない）。以前はここでinvertを無視したまま素通りしており、将来
                # tile_property_inverted=Trueの数値材料が追加された場合に色分けが反転した
                # まま気づかれない欠陥があった。数値材料の反転は未対応のため、安全側で
                # ramp化不可（None）とする。
                return None
            tile_inputs.append(TileInputSpec(property=spec.tile_property, weight=term.weight))
        # 改善計画T308: 単一term・weight=1.0限定を撤廃。total=Σ(material_value×term.weight)は
        # 評価側の量とフロント表示側の量が完全に同一の演算のため、term数・重みによらず
        # shape.breakpointsのx値（先頭除く）をそのまま閾値として流用できる（モジュール
        # docstring参照）。
        thresholds = [bp[0] for bp in shape.breakpoints[1:]]
        return RampInputs(tile_inputs=tile_inputs, thresholds=thresholds)

    return None


def primary_attribute_ids_for(definition: AxisDefinition) -> list[str]:
    """軸が参照する材料を一次属性idへ解決する。`AxisDefinition.materials`は材料idだけで
    なく他の軸id（改善計画T292の階層構造、例: car_stressの内部軸6つ）も返しうるため、
    材料id側で見つからないエントリはAXIS_DEFINITIONSの軸として再帰的に解決する
    （内部軸自体も内部軸を参照しうる想定はないが、循環参照は軸スタジオ側で拒否済み
    [test_create_rejects_direct_cycle_between_two_axes]のため`visited`で安全側に保護する）。

    改善計画T320: 元は`api/routers/axis_catalog.py`（GET /api/axis-catalog、実行時API）
    専用のprivateヘルパーだったが、`registry_defaults.py`（`export_openapi.py`向けの
    ビルド時静的axis-catalog.json生成）が同じ解決ロジックを`AxisSpec.inputs`として
    軸ごとに手書きで重複させていたため、この関数へ一本化した（片側import、設計原則2）。
    """
    seen: dict[str, None] = {}
    visited: set[str] = set()

    def resolve(current: AxisDefinition) -> None:
        if current.axis_id in visited:
            return
        visited.add(current.axis_id)
        for material_id in current.materials:
            spec = MATERIAL_CATALOG.get(material_id)
            if spec is not None:
                if spec.primary_attribute_id is not None:
                    seen.setdefault(spec.primary_attribute_id, None)
                continue
            referenced_axis = AXIS_DEFINITIONS.get(material_id)
            if referenced_axis is not None:
                resolve(referenced_axis)

    resolve(definition)
    return list(seen)


def axis_display_for(definition: AxisDefinition) -> AxisDisplaySpec:
    """軸の地図表示宣言（改善計画T308、T310で軸id別の特別扱いを解消）。
    `GET /api/axis-catalog`が公開軸すべてに対して呼ぶ想定の純粋関数（`AXIS_DEFINITIONS`・
    `MATERIAL_CATALOG`というプロセス内メモリだけを見る、DB/IO無し）。

    優先順位: ①`definition.display_override`（derive_ramp_inputsが解決できない軸、または
    統計的に閾値を調整したい軸が、軸自身のデータとして持つ手書き上書き。改善計画T310で
    軸id→値のハードコード辞書[旧`_HAND_WRITTEN_DISPLAY`]から軸自身のフィールドへ移設した）、
    ②無ければ`derive_ramp_inputs()`による自動導出、③どちらも得られなければ`kind="none"`。

    `unit`・`category`（凡例の単位・地図レイヤーパネルの並び順区分）は材料構成から
    機械的に導出できないため、自動導出ケースではAxisDisplaySpecの既定値
    （`unit=""`・`category="trafficSafety"`）にフォールバックする
    （docs/decisions/t308-axis-map-display-auto-derivation.md「凡例・色分けの
    描画方法」節参照）。
    """
    if definition.display_override is not None:
        return definition.display_override
    ramp = derive_ramp_inputs(definition)
    if ramp is None:
        return AxisDisplaySpec(kind="none", label=definition.label)
    return AxisDisplaySpec(
        kind="ramp",
        label=definition.label,
        tile_inputs=ramp.tile_inputs,
        thresholds=ramp.thresholds,
    )
