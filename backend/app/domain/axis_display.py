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

現行7軸のうち、この関数が実際に使われるのは`surface_q`・`night`のみ（`registry_defaults.py`
参照）。`stop_density`（改善計画T308一般化後は技術的に自動導出可能になったが、既存の
手書きthresholds[1,2,4]は統計的経験則で単純な折れ点流用[本関数が返す[4.0]の1閾値のみ]
より段階が細かく、置き換えると表示が粗くなるため、意図的に手書きのまま維持する）・
`accident`（材料が年正規化済みでタイル生値とスケールが異なる、静的な変換係数を持てない）・
`car_stress`（改善計画T292: 内部軸6つを参照するBreakpointLinearShapeのため、他の軸を
参照するMaterialTermをこの関数は解決できない）は対象外のまま手書きのdisplayを維持する
（car_stressもT292以降kind="ramp"だが、tile_inputsはこの関数ではなく
registry_defaults.pyへ直接手書きしている——stop_density/accidentと同じ前例）。

**T308での用途拡大**: 上記の一般化により、軸スタジオ（GUI）で作成された軸
（複数材料の重み付き結合や、highway/bicycle_infra等のstr N値カテゴリカル材料を使う軸を
含む）も、タイル焼き込み済み・実行時スケール変換不要・方向非依存の材料だけで構成されて
いれば、`registry_defaults.py`への個別の手書き登録なしに自動導出の対象になる
（本モジュールの`axis_display_for()`が呼び出し元、
docs/decisions/t308-axis-map-display-auto-derivation.md参照）。
"""

from itertools import combinations
from typing import cast

from pydantic import BaseModel

from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    UNSIGNALED_INTERSECTION_WEIGHT,
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


def _adjacent_midpoint_thresholds(scores: list[float]) -> list[float]:
    """スコアの集合から、ソート済み隣接値の中間点を閾値として返す（改善計画T308、
    bool2値の`[(lower+upper)/2]`をN値へ一般化したもの）。"""
    ordered = sorted(set(scores))
    return [(a + b) / 2 for a, b in zip(ordered, ordered[1:])]


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


# --- 改善計画T308: 自動導出対象外の3軸（stop_density/accident/car_stress）の手書き表示 ---
#
# derive_ramp_inputsが対象外にする理由はモジュールdocstring参照。以前は
# registry_defaults.pyへ直接書かれていたが、`axis_display_for()`（実行時APIが読む単一
# 関数）と`registry_defaults.py`（ビルド時静的生成物axis-catalog.json・テストが読む
# レジストリ）の両方から同じ内容を参照する必要があるため、このモジュールを単一ソースに
# 移設した（設計原則2「片側import」、値を2箇所に手書きしない）。

# car_stressのtile_inputsが参照する内部軸のshape（derive_ramp_inputsが解決できない
# 「他の軸を参照するBreakpointLinearShape」を手書き登録する際、highway/bicycle_infra/
# maxspeed_kmh/lanes_count/motor_vehicle_noの値自体はAXIS_DEFINITIONSを単一ソースとして
# 参照する。designationのみ材料自体が異なる[categories="designation"(3値) vs
# 評価用"is_designated"(bool)]ため単一ソース化できず手書きのまま）。
_CAR_STRESS_HIGHWAY_BASE_SHAPE = AXIS_DEFINITIONS["car_stress_highway_base"].shape
_CAR_STRESS_BICYCLE_INFRA_SHAPE = AXIS_DEFINITIONS["car_stress_bicycle_infra_adjustment"].shape
_CAR_STRESS_MAXSPEED_SHAPE = AXIS_DEFINITIONS["car_stress_maxspeed_adjustment"].shape
_CAR_STRESS_LANES_SHAPE = AXIS_DEFINITIONS["car_stress_lanes_adjustment"].shape
_CAR_STRESS_MOTOR_VEHICLE_NO_SHAPE = AXIS_DEFINITIONS["car_stress_motor_vehicle_no_adjustment"].shape
assert isinstance(_CAR_STRESS_HIGHWAY_BASE_SHAPE, CategoricalShape)
assert isinstance(_CAR_STRESS_BICYCLE_INFRA_SHAPE, CategoricalShape)
assert isinstance(_CAR_STRESS_MAXSPEED_SHAPE, BreakpointLinearShape)
assert isinstance(_CAR_STRESS_LANES_SHAPE, BreakpointLinearShape)
assert isinstance(_CAR_STRESS_MOTOR_VEHICLE_NO_SHAPE, CategoricalShape)

STOP_DENSITY_DISPLAY = AxisDisplaySpec(
    kind="ramp",
    label=AXIS_DEFINITIONS["stop_density"].label,
    category="trafficSafety",
    tile_inputs=[
        TileInputSpec(property="stop_per_km", weight=1.0),
        TileInputSpec(property="intersection_per_km", weight=UNSIGNALED_INTERSECTION_WEIGHT),
    ],
    # domain/difficulty.py: stop_difficultyの正準スケール（0→4.0回/kmで0→100）に
    # 対応する4段階（〜1/〜2/〜4/4超）。derive_ramp_inputsが導出する[4.0]の1閾値
    # （2段階、モジュールdocstring参照）より段階が細かい統計的経験則のため手書き維持。
    thresholds=[1.0, 2.0, 4.0],
    unit="回/km",
    note="信号・横断歩道・一時停止・踏切に無タグ交差点（重み0.3）を加えた"
    "停止要因の密度。way単位の事前集計（way_attribute_counts）由来",
)

ACCIDENT_DISPLAY = AxisDisplaySpec(
    kind="ramp",
    label=AXIS_DEFINITIONS["accident"].label,
    category="trafficSafety",
    tile_inputs=[TileInputSpec(property="accident_per_km", weight=1.0)],
    # domain/difficulty.py: accident_difficultyの正準スケール（0→0.5件/(km・年)で
    # 0→100）を、タイルへ焼き込む生値（収録3年分の重み付き件数/km、年正規化前）へ
    # 換算した4段階（〜0.4/〜0.8/〜1.5/1.5超）。
    thresholds=[0.4, 0.8, 1.5],
    unit="件/km",
    note="警察庁統計（収録全年分、死亡事故は重み付き）の自転車関連事故の"
    "距離正規化密度。way単位の事前集計（way_attribute_counts）由来。"
    "正確な事故地点は既存の事故レイヤー（accidents、生の点表示）で確認できる",
)

CAR_STRESS_DISPLAY = AxisDisplaySpec(
    kind="ramp",
    label=AXIS_DEFINITIONS["car_stress"].label,
    category="trafficSafety",
    # 改善計画T292: 内部軸6つがそれぞれ参照する材料は全てMVTタイルへ焼き込み済み
    # （highway/bicycle_infra/maxspeed_kmh/lanes_count/motor_vehicle_no、
    # material_catalog.py参照。designationのみtile_property保持の"designation"
    # [3値文字列]と評価用の"is_designated"[bool]が別材料——タイルには前者しか
    # 無いため、is_designatedと同じ意味を「designationがどの値であれ+1」という
    # categories（3値とも同じ点数）で表現する）。derive_ramp_inputsの自動導出は
    # 「他の軸を参照するBreakpointLinearShape（AXIS_DEFINITIONS['car_stress']の
    # terms）」を解決できないため対象外のまま（モジュールdocstring参照）、
    # stop_density/accidentと同じ前例で手書き登録する。
    #
    # 値はAXIS_DEFINITIONS内部軸の生の合計（0-100への最終rescale
    # [breakpoints=(1,0)-(5,100)]は適用しない）。stop_density/accidentも
    # 生の集計値（回/km・件/km）へ直接thresholdsを置いており、rampの目的は
    # 色分けの相対比較であって難易度の絶対値表示ではない
    # （正確な合成コストは区間インスペクタ/api/region/axis-inspectorが
    # サーバー側で正確に計算する）。
    tile_inputs=[
        TileInputSpec(
            property="highway",
            categories=_CAR_STRESS_HIGHWAY_BASE_SHAPE.mapping,
            has_unknown_fallback=True,
        ),
        TileInputSpec(
            property="bicycle_infra",
            categories=_CAR_STRESS_BICYCLE_INFRA_SHAPE.mapping,
        ),
        TileInputSpec(
            property="maxspeed_kmh",
            breakpoints=_CAR_STRESS_MAXSPEED_SHAPE.breakpoints,
        ),
        TileInputSpec(
            property="lanes_count",
            breakpoints=_CAR_STRESS_LANES_SHAPE.breakpoints,
        ),
        TileInputSpec(
            # designationはcar_stress内部軸の材料(is_designated、bool)とは別の
            # 材料（3値文字列、種別によらず一律+1）のため単一ソース化できない。
            property="designation",
            categories={"emergency_transport": 1.0, "critical_logistics": 1.0, "both": 1.0},
        ),
        TileInputSpec(
            property="motor_vehicle_no",
            boolean=True,
            true_value=_CAR_STRESS_MOTOR_VEHICLE_NO_SHAPE.mapping[True],
            false_value=_CAR_STRESS_MOTOR_VEHICLE_NO_SHAPE.mapping[False],
        ),
    ],
    # highway基準値（1-4）の区分境界そのもの（4段階の主要因）。他5補正の
    # 寄与幅（各-2〜+1）に対し、highway基準値が主要な分散要因のため、その
    # 境界をそのまま閾値に流用する（stop_density/accidentと同じく統計分析
    # ではなくドメイン知識による選定、実データでの分布確認は必要になれば
    # 別タスクで実施）。
    thresholds=[2.0, 3.0, 4.0],
    note="改善計画T292: highway/bicycle_infra/maxspeed_kmh/lanes_count/"
    "designation/motor_vehicle_noの6材料から自動計算する。以前は専用の"
    "手書きexpression（旧carStressExpression.ts）が必要だったが、内部軸への"
    "階層再構成でtile_inputsの重み付き結合として表現できるようになった",
)

_HAND_WRITTEN_DISPLAY: dict[str, AxisDisplaySpec] = {
    "stop_density": STOP_DENSITY_DISPLAY,
    "accident": ACCIDENT_DISPLAY,
    "car_stress": CAR_STRESS_DISPLAY,
}


def axis_display_for(definition: AxisDefinition) -> AxisDisplaySpec:
    """軸の地図表示宣言（改善計画T308）。`GET /api/axis-catalog`が公開軸すべてに対して
    呼ぶ想定の純粋関数（`AXIS_DEFINITIONS`・`MATERIAL_CATALOG`というプロセス内メモリだけを
    見る、DB/IO無し）。

    優先順位: ①上記の手書きoverride（derive_ramp_inputsが解決できない3軸）、②無ければ
    `derive_ramp_inputs()`による自動導出、③どちらも得られなければ`kind="none"`。

    `unit`・`category`（凡例の単位・地図レイヤーパネルの並び順区分）は材料構成から
    機械的に導出できないため、自動導出ケースではAxisDisplaySpecの既定値
    （`unit=""`・`category="trafficSafety"`）にフォールバックする
    （docs/decisions/t308-axis-map-display-auto-derivation.md「凡例・色分けの
    描画方法」節参照。軸スタジオへの入力欄追加は本タスクのスコープ外）。
    """
    override = _HAND_WRITTEN_DISPLAY.get(definition.axis_id)
    if override is not None:
        return override
    ramp = derive_ramp_inputs(definition)
    if ramp is None:
        return AxisDisplaySpec(kind="none", label=definition.label)
    return AxisDisplaySpec(
        kind="ramp",
        label=definition.label,
        tile_inputs=ramp.tile_inputs,
        thresholds=ramp.thresholds,
    )
