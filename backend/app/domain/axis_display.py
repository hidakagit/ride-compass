"""地図表示ルール（kind=ramp）の自動導出（改善計画T278、T308で一般化）。

`AXIS_DEFINITIONS`の軸が参照する材料（`domain/material_catalog.py: MATERIAL_CATALOG`）が
全てMVTタイルへ焼き込み済み（`tile_property`保持）であれば、その軸の地図ramp表示
（`registry.py: TileInputSpec`のΣproperty×weight・真偽値のcase分岐）を自動導出できる。

**安全に自動導出できるケースに限定する**（改善計画T278調査・T308一般化・T396でFlagSumShapeを
BreakpointLinearShapeへ統合した際に判明した制約）:
- `CategoricalShape`（真偽値材料1件、またはstr N値材料1件）: 真偽値は2値の中間点、
  str N値は達成しうるスコアの隣接中間点を閾値とする（改善計画T308でstr N値も対応）。
- `BreakpointLinearShape`で全termがboolean材料の場合（改善計画T396、旧`FlagSumShape`の
  代替）: 各termは該当時1・非該当時0として振る舞うため、達成しうる合計値は「重み（旧flag_sum
  でいう加点）の空集合込み全部分和」に限られる（連続値と違い中間の値を取らない）。この
  部分和集合（`shape.breakpoints`の最終x値でクランプ）の隣接中間点を閾値とする。
- `BreakpointLinearShape`で`preprocess="identity"`かつ全termがboolean材料**ではない**場合
  （改善計画T308で単一材料・weight=1.0限定を撤廃）: `total = Σ(material_value × term.weight)`
  という評価側の量は、termごとに`TileInputSpec(property, weight=term.weight)`を並べて
  フロントが計算する量と完全に同一（同じ材料・同じ重み・同じ演算）であるため、
  `shape.breakpoints`のx値（先頭除く）は元のterm数・重みに関わらずそのまま妥当な閾値として
  流用できる（近似ではなく数学的に厳密な流用。連続値は中間の値も取りうるため、boolean限定
  ケースと違い部分和集合ではなくbreakpoints自体のx値をそのまま使ってよい）。

それ以外（`preprocess="abs"`・タイル非依存材料・実行時スケール変換が必要な材料
[`tile_property_needs_runtime_scale=True`]・方向依存材料
[`tile_property_direction_dependent=True`、改善計画T308]を含む軸、他の軸を参照する
`MaterialTerm`を含む軸）は`None`を返す（自動導出対象外——地図に出ない。既存のkind="none"軸を
壊さない安全側の判断。改善計画T298: kind="bespoke"は利用ゼロのためLiteral自体を削除済み、
registry.py参照）。

**`preprocess="abs"`対応は実装しないと最終決定した**（改善計画T404で先送り→T423で調査・
決定）。absを使う軸は現行`AXIS_DEFINITIONS`では`gradient`のみで、`gradient`が参照する
材料`gradient_percent`は`tile_property_direction_dependent=True`（方向依存材料、
`material_catalog.py`参照）でもある——上記のとおり方向依存材料を含む軸はこの時点で
`None`が確定するため、`preprocess="abs"`対応を実装しても`gradient`のkind="ramp"化には
**一切寄与しない**（2つの独立した制約が両方ともこの軸を弾く）。かつ`gradient`の地図表示は
T423でRedis経由のway_id→値配信（`gradient_way_service.py`）という別経路に決着しており、
そもそもramp（MVTタイル焼き込み）を必要としない。absを使う他の軸が今後追加される見込みも
無いため、「動機のない機能を先回りして作らない」という複雑度平衡の原則
（docs/complexity-review-2026-08-16.md）に沿い、フロント（`buildAxisRampValueExpression`）
側の対応も含めて実装しないことを確定する。新たにabs前処理を使う軸（方向非依存の材料に
absを適用したい場合等）が具体的に必要になった時点で、改めて着手を検討すること。

この関数が対象外と判定した軸は`axis_display_for()`が`kind="none"`を返す（地図に出ない）。
以前は`AxisDefinition.display_override`（軸自身が持つ手書きの`AxisDisplaySpec`、改善計画
T310）が設定されていればそちらを後方互換フォールバックとして使う仕組みだったが、
car_stress/stop_density/accidentの3軸をT404で本関数の自動導出＋`display_thresholds_
override`へ移行しdisplay_overrideが不要になったことを受け、改善計画T409でフィールド・
DBカラムごと削除した（docs/tasks/T409.md参照）。

**T308での用途拡大**: 上記の一般化により、軸スタジオ（GUI）で作成された軸
（複数材料の重み付き結合や、highway/surface等のstr N値カテゴリカル材料を使う軸を
含む）も、タイル焼き込み済み・実行時スケール変換不要・方向非依存の材料だけで構成されて
いれば、個別の手書き登録なしに自動導出の対象になる（本モジュールの`axis_display_for()`が
呼び出し元、docs/decisions/t308-axis-map-display-auto-derivation.md参照）。

**T404での拡張（display_override廃止方針、docs/tasks/T404.md）**: 上記の「対象外」
条件のうち2つを緩和した。
- **軸参照の再帰解決**: `MaterialTerm.material`が材料idではなく他の軸id（改善計画T292の
  軸階層）を指す場合、`_resolve_referenced_axis_tile_input()`がその参照先の軸を
  再帰的に解決し、末端の材料（タイル焼き込み済み・方向非依存）まで辿れれば
  フラットな`tile_inputs`へ展開する（car_stressが5つの内部軸を参照する構成の
  自動導出を可能にする、詳細は同関数のdocstring参照）。
- **実行時スケール変換の定数化**: `tile_property_needs_runtime_scale=True`な材料
  （例: `accident_count_per_km_year`）も、`TileInputSpec.needs_runtime_scale`で
  印を付けたうえで自動導出の対象に含める。タイル生値→材料スケールの変換係数は
  実行時（DBの収録年数等）にしか決まらないため、`weight`フィールドへ静的に
  焼き込めない代わりに、`GET /api/axis-catalog`が返す`material_runtime_scales`
  （実行時に1回だけ解決するグローバル定数）をフロントのJS式が追加で掛け合わせる
  （`frontend/src/components/Map/axisLayers.ts: buildAxisRampValueExpression`参照）。

方向依存材料（`tile_property_direction_dependent=True`、風・勾配）は引き続き対象外
（T404の対象外、T405で別途扱う）。auto-derive自体は成功しても、`derive_ramp_inputs`が
返す`thresholds`は元の`AxisDefinition.shape.breakpoints`のX軸スケールをそのまま流用する
ため、複数材料の組み合わせ（car_stress）や単純な線形正規化（stop_density/accident）では
1〜2段階の粗い色分けしか作れないことがある。この「色分け粒度の好み」は自動導出の能力とは
別問題のため、`AxisDefinition.display_thresholds_override`（軸スタジオのGUIが編集する
軽量な数値配列）で上書きする（`axis_display_for()`参照）。
"""

from itertools import combinations
from typing import cast

from pydantic import BaseModel

from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
)
from app.domain.material_catalog import MATERIAL_CATALOG, MaterialSpec
from app.domain.registry import AxisDisplaySpec, TileInputSpec


class RampInputs(BaseModel):
    tile_inputs: list[TileInputSpec]
    thresholds: list[float]


def _adjacent_midpoint_thresholds(scores: list[float]) -> list[float]:
    """スコアの集合から、ソート済み隣接値の中間点を閾値として返す（改善計画T308、
    bool2値の`[(lower+upper)/2]`をN値へ一般化したもの）。"""
    ordered = sorted(set(scores))
    return [(a + b) / 2 for a, b in zip(ordered, ordered[1:])]


def _boolean_terms_thresholds(weights: list[float], cap: float | None) -> list[float]:
    """全termがboolean材料のBreakpointLinearShape向け（改善計画T396、旧`FlagSumShape`の
    `_flag_sum_thresholds`を一般化）。各termは該当時weight・非該当時0の2値しか取らないため、
    達成しうる合計値は「重みの空集合込み全部分和」に限られる（連続値と異なり中間の値を
    取らない）。この部分和集合（capでクランプ後）の隣接中間点を閾値として返す。

    コードレビュー指摘の修正: 末尾の「sorted→隣接中間点」ロジックが
    `_adjacent_midpoint_thresholds`と重複していたため、達成しうる合計値の集合を
    求めるところまでを担い、閾値化自体は共通関数へ委ねる（将来中間点の計算式
    [丸め・重み付け等]を変更する際、片方だけ直し忘れて挙動が乖離するのを防ぐ）。
    """
    sums: set[float] = {0.0}
    for r in range(1, len(weights) + 1):
        for combo in combinations(weights, r):
            total = sum(combo)
            if cap is not None:
                total = min(total, cap)
            sums.add(total)
    return _adjacent_midpoint_thresholds(list(sums))


def _boolean_score_tile_input(spec: MaterialSpec, true_score: float, false_score: float) -> TileInputSpec | None:
    """真偽値2値のCategoricalShape（`mapping.keys() == {True, False}`）1件をTileInputSpecへ
    変換する共通ヘルパー（改善計画T404でヘルパー化）。

    `has_unknown_fallback`は`spec.bool_default`から決める（レビュー指摘の修正:
    以前は常にTrue固定だったため、bool_default="false"（欠損=確定false、例:
    motor_vehicle_no・is_designated）の材料でも「不明」[灰色]表示になってしまう
    不整合があった——surface_good等bool_default="nan"[欠損=真に不明]の材料でのみ
    正しかった）。

    `spec.tile_property_categorical_true_values`が設定されている材料（改善計画T404、
    is_designated等）は、タイル側が真偽値プロパティではなく複数値の文字列
    （categorical）プロパティのため、`categories`ベースで表現する（該当時は
    `true_score`、非該当[categories未登録の値・欠損]時は寄与0）。`categories`は
    未登録を常に0扱いする仕組みしか持たないため、`false_score`が厳密に0.0の
    場合のみ数学的に正確に表現できる——それ以外は安全側でNoneを返し自動導出を諦める。
    """
    has_unknown_fallback = spec.bool_default == "nan"
    if spec.tile_property_categorical_true_values is not None:
        if false_score != 0.0:
            return None
        assert spec.tile_property is not None  # 呼び出し元で保証済み
        return TileInputSpec(
            property=spec.tile_property,
            categories={value: true_score for value in spec.tile_property_categorical_true_values},
            has_unknown_fallback=has_unknown_fallback,
        )
    assert spec.tile_property is not None  # 呼び出し元で保証済み
    return TileInputSpec(
        property=spec.tile_property,
        boolean=True,
        true_value=true_score,
        false_value=false_score,
        has_unknown_fallback=has_unknown_fallback,
    )


def _rescale_tile_input(tile_input: TileInputSpec, weight: float) -> TileInputSpec:
    """再帰解決した参照先の軸のTileInputSpec1件に、外側の`MaterialTerm.weight`を
    乗せる（改善計画T404）。`categories`・真偽値(`boolean`)のTileInputSpecは寄与値を
    `categories`の値・`true_value`/`false_value`へ直接（＝最終的な寄与値そのものとして）
    持つ設計のため、それらの値をweight倍する。それ以外（`weight`フィールド自体が
    倍率を表すTileInputSpec、素朴な数値・`breakpoints`自己変換材料）は`weight`
    フィールドを乗せる。"""
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
    """`MaterialTerm.material`が他の軸を指す場合（改善計画T292の軸階層、例:
    car_stressが参照する5つの内部軸）に、その参照先の軸を再帰的に解決し、外側の
    重み(`weight`)を乗せた1件のTileInputSpecへ変換する（改善計画T404）。

    安全に変換できるケースを限定する（`derive_ramp_inputs`本体と同じ「安全に自動導出
    できるケースに限定する」設計方針、モジュールdocstring参照）:

    - 参照先が`CategoricalShape`: 評価時の値は`mapping.get(value)`をそのまま返す
      （追加の変換なし）ため、`derive_ramp_inputs`を再帰的に呼んで得られる唯一の
      tile_inputを`_rescale_tile_input`で再スケールしてそのまま使える。
    - 参照先が`BreakpointLinearShape`（単一term・その内側の`term.weight==1.0`・
      `preprocess="identity"`）: 評価時の値は`evaluate_breakpoint_linear(材料値,
      shape.breakpoints)`という区分線形変換そのもの。`TileInputSpec.breakpoints`
      （自己変換材料、registry.py参照）がフロント側で同じ変換をタイル生値へ直接
      適用できるため、`TileInputSpec(property=..., breakpoints=shape.breakpoints,
      weight=weight)`へ変換できる（内側の`term.weight!=1.0`や複数termは「重み付けして
      から折れ点変換」という順序を`TileInputSpec.breakpoints`は表現できないため対象外、
      安全側でNone）。この分岐の内側termはさらに別の軸を参照する2段階以上のネストには
      対応しない（car_stressの現行構成には存在しない。将来必要になれば拡張する）。
    - それ以外（複数termの`BreakpointLinearShape`・非identity前処理・内側`term.weight!=1.0`
      の単一term）は安全に変換できないためNone（car_stressの現行5内部軸には該当しないが、
      将来別の軸がこのパターンに当てはまった場合の安全弁）。

    循環参照は軸スタジオ側で拒否済みだが、`visited`集合で安全側に保護する
    （`primary_attribute_ids_for`と同じパターン）。
    """
    if axis_id in visited:
        return None
    referenced = AXIS_DEFINITIONS.get(axis_id)
    if referenced is None:
        return None
    shape = referenced.shape
    if isinstance(shape, CategoricalShape):
        ramp = derive_ramp_inputs(referenced, visited)
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
            # 参照先の内側termがさらに別の軸を指す2段階以上のネストは非対応（安全側）。
            return None
        if (
            inner_spec.tile_property is None
            or inner_spec.tile_property_direction_dependent
            or inner_spec.tile_property_needs_runtime_scale
            or inner_spec.dtype == "boolean"
        ):
            # dtype=="boolean"はbreakpoints自己変換の対象外（数値材料の区分線形変換のみを
            # 表現する仕組みのため、既存のBreakpointLinearShape分岐と同じ制約）。
            return None
        return TileInputSpec(property=inner_spec.tile_property, breakpoints=shape.breakpoints, weight=weight)
    return None


def derive_ramp_inputs(definition: AxisDefinition, _visited: frozenset[str] = frozenset()) -> RampInputs | None:
    if definition.axis_id in _visited:
        return None
    visited = _visited | {definition.axis_id}

    materials = definition.materials
    specs: dict[str, MaterialSpec | None] = {m: MATERIAL_CATALOG.get(m) for m in materials}
    for material_id, spec in specs.items():
        if spec is None:
            if material_id not in AXIS_DEFINITIONS:
                # 材料でも既知の軸参照でもない未知の参照は安全側でNone。
                return None
            continue  # 軸参照（改善計画T404）: 個別のtile_property等はここでは検証しない
            # （_resolve_referenced_axis_tile_inputが参照先の材料を辿って検証する）。
        if spec.tile_property is None or spec.tile_property_direction_dependent:
            return None
        # tile_property_needs_runtime_scale（改善計画T404）はここでは弾かない。
        # tile_property自体は使えるため、weightフィールドへの静的な変換は無理でも、
        # フロント側で実行時スケール定数（GET /api/axis-catalogのmaterial_runtime_scales）を
        # 追加で掛け合わせれば解決できる（TileInputSpec.needs_runtime_scaleで印を付ける、
        # モジュールdocstring参照）。

    shape = definition.shape

    if isinstance(shape, CategoricalShape):
        spec = specs.get(shape.material)
        if spec is None or spec.tile_property is None:
            # shape.materialが材料ではなく軸参照、またはタイル非依存の場合は非対応
            # （現行AXIS_DEFINITIONSに実例なし。CategoricalShapeの軸参照対応は
            # BreakpointLinearShapeと異なりスコープ外、安全側でNone）。
            return None
        if set(shape.mapping.keys()) == {True, False}:
            true_score = shape.mapping[True]
            false_score = shape.mapping[False]
            lower, upper = sorted([true_score, false_score])
            tile_input = _boolean_score_tile_input(spec, true_score, false_score)
            if tile_input is None:
                return None
            return RampInputs(tile_inputs=[tile_input], thresholds=[(lower + upper) / 2])
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

    if isinstance(shape, BreakpointLinearShape):
        if shape.preprocess != "identity":
            # abs前処理は実装しないと確定済み（改善計画T404→T423、モジュールdocstring
            # 「`preprocess="abs"`対応は実装しないと最終決定した」節参照）。安全側でNone。
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
        # 認識した上で運用すること（改善計画T409で旧手書き上書き`display_override`は
        # 削除済みのため、現時点で個別の軸だけ回避する手段は無い）。
        tile_inputs = []
        for term in shape.terms:
            spec = specs.get(term.material)
            if spec is None:
                # 改善計画T404: 材料ではなく他の軸を指す（軸階層、例: car_stressの
                # 5つの内部軸参照）。参照先を再帰的に解決する。
                resolved = _resolve_referenced_axis_tile_input(term.material, term.weight, visited)
                if resolved is None:
                    return None
                tile_inputs.append(resolved)
                continue
            assert spec.tile_property is not None  # 上のspecsループで確認済み
            if spec.dtype == "boolean":
                # 改善計画T396: 旧FlagSumShapeの代替。該当時term.weight・非該当時0の2値。
                tile_inputs.append(
                    TileInputSpec(
                        property=spec.tile_property,
                        boolean=True,
                        true_value=term.weight,
                        false_value=0.0,
                    )
                )
            else:
                # 改善計画T404: tile_property_needs_runtime_scaleな材料（例:
                # accident_count_per_km_year）もここで受け入れる（specsループの
                # ガード緩和とセット）。weightは元のterm.weightのまま静的に確定し、
                # 実行時スケール定数はフロント側がTileInputSpec.needs_runtime_scaleを
                # 見て追加で掛け合わせる。
                tile_inputs.append(
                    TileInputSpec(
                        property=spec.tile_property,
                        weight=term.weight,
                        needs_runtime_scale=spec.tile_property_needs_runtime_scale,
                    )
                )

        if all((s := specs.get(term.material)) is not None and s.dtype == "boolean" for term in shape.terms):
            # 改善計画T396: 全termがboolean材料なら、達成しうる合計値は部分和集合に限られる
            # （連続値と異なり中間の値を取らない）ため、その隣接中間点を閾値とする
            # （旧FlagSumShapeの`_flag_sum_thresholds`と同じロジック、cap相当はbreakpointsの
            # 最終x値）。旧`FlagSumShape.flags`はPydantic側でmax_length=12を持っていたが
            # （全部分和2^N-1通りの組合せ爆発を避けるため）、統合後のtermsにその制約が
            # 無くなったので、同じ安全弁をここに移設する（GUIは今のところ「材料の天井」で
            # 実質12を超えない想定だが、直接API呼び出しでは制限されないため）。
            if len(shape.terms) > 12:
                return None
            cap = shape.breakpoints[-1][0]
            thresholds = _boolean_terms_thresholds([term.weight for term in shape.terms], cap)
        else:
            # 改善計画T308: 単一term・weight=1.0限定を撤廃。total=Σ(material_value×term.weight)
            # は評価側の量とフロント表示側の量が完全に同一の演算のため、term数・重みによらず
            # shape.breakpointsのx値（先頭除く）をそのまま閾値として流用できる（モジュール
            # docstring参照。連続値は中間の値も取りうるためboolean限定ケースと異なる）。
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
    """軸の地図表示宣言（改善計画T308、T310で軸id別の特別扱いを解消、T404で
    display_override廃止方針に合わせ優先順位を書き換え、T409でdisplay_override自体を
    削除）。`GET /api/axis-catalog`が公開軸すべてに対して呼ぶ想定の純粋関数
    （`AXIS_DEFINITIONS`・`MATERIAL_CATALOG`というプロセス内メモリだけを見る、DB/IO無し）。

    優先順位（改善計画T404、docs/tasks/T404.md）:
    ①`derive_ramp_inputs()`が自動導出に成功し、かつ`definition.display_thresholds_override`
    （軸スタジオのGUIが編集する、色分けしきい値だけの軽量な上書き）が設定されていれば、
    自動導出した`tile_inputs`とこのしきい値を組み合わせる。
    ②`derive_ramp_inputs()`が成功し`display_thresholds_override`が無ければ、自動導出した
    しきい値をそのまま使う。
    ③`derive_ramp_inputs()`自体が失敗すれば`kind="none"`（改善計画T409以前は
    `definition.display_override`という生JSON上書きを後方互換フォールバックとして使う
    ③'があったが、`car_stress`/`stop_density`/`accident`の3軸をT404で
    `display_thresholds_override`へ移行しdisplay_overrideが不要になったことを確認した
    うえでT409でフィールド・DBカラムごと削除した。docs/tasks/T409.md参照）。

    `unit`・`category`（凡例の単位・地図レイヤーパネルの並び順区分）は材料構成から
    機械的に導出できないため、自動導出ケースではAxisDisplaySpecの既定値
    （`unit=""`・`category="trafficSafety"`）にフォールバックする
    （docs/decisions/t308-axis-map-display-auto-derivation.md「凡例・色分けの
    描画方法」節参照）。
    """
    ramp = derive_ramp_inputs(definition)
    if ramp is not None:
        thresholds = (
            list(definition.display_thresholds_override)
            if definition.display_thresholds_override is not None
            else ramp.thresholds
        )
        return AxisDisplaySpec(
            kind="ramp",
            label=definition.label,
            tile_inputs=ramp.tile_inputs,
            thresholds=thresholds,
        )
    return AxisDisplaySpec(kind="none", label=definition.label)
