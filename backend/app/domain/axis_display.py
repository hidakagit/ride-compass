"""地図表示ルール（kind=ramp）の自動導出。

`AXIS_DEFINITIONS`の軸が参照する材料（`domain/material_catalog.py: MATERIAL_CATALOG`）が
全てMVTタイルへ焼き込み済み（`tile_property`保持）であれば、その軸の地図ramp表示
（`registry.py: TileInputSpec`のΣproperty×weight・真偽値のcase分岐）を自動導出できる。
自動導出できるshapeの形・条件は`docs/modules/backend/axis-studio.md`「地図表示ルールの
自動導出」節の表を参照（本モジュールはその表の実装）。

それ以外（`preprocess="abs"`・タイル非依存材料・実行時スケール変換が必要な材料
[`tile_property_needs_runtime_scale=True`]・方向依存材料
[`tile_property_direction_dependent=True`]を含む軸、参照先を再帰的に解決できない軸参照を
含む軸）は`None`を返す（自動導出対象外——地図に出ない。既存のkind="none"軸を壊さない
安全側の判断）。

**`preprocess="abs"`対応は実装しないと確定している**。absを使う軸は現行
`AXIS_DEFINITIONS`では`gradient`のみで、`gradient`が参照する材料`gradient_percent`は
`tile_property_direction_dependent=True`（方向依存材料、`material_catalog.py`参照）でも
あるため、上記のとおり方向依存材料を含む軸はこの時点で`None`が確定する——
`preprocess="abs"`対応を実装しても`gradient`のkind="ramp"化には一切寄与しない
（2つの独立した制約が両方ともこの軸を弾く）。かつ`gradient`の地図表示はRedis経由の
way_id→値配信（`gradient_way_service.py`）という別経路のため、そもそもramp
（MVTタイル焼き込み）を必要としない。absを使う他の軸が今後追加される見込みも無いため、
「動機のない機能を先回りして作らない」という複雑度平衡の原則
（docs/complexity-review-2026-08-16.md）に沿い、フロント
（`buildAxisRampValueExpression`）側の対応も含めて実装しない。新たにabs前処理を使う軸
（方向非依存の材料にabsを適用したい場合等）が具体的に必要になった時点で、改めて着手を
検討すること。

この関数が対象外と判定した軸は`axis_display_for()`が`kind="none"`を返す（地図に出ない）。

**軸参照の再帰解決**: `MaterialTerm.material`が材料idではなく他の軸id（軸階層）を指す
場合、`_resolve_referenced_axis_tile_input()`がその参照先の軸を再帰的に解決し、末端の
材料（タイル焼き込み済み・方向非依存）まで辿れればフラットな`tile_inputs`へ展開する
（car_stressが5つの内部軸を参照する構成の自動導出を可能にする、詳細は同関数のdocstring
参照）。

**実行時スケール変換の定数化**: `tile_property_needs_runtime_scale=True`な材料
（例: `accident_count_per_km_year`）も、`TileInputSpec.needs_runtime_scale`で
印を付けたうえで自動導出の対象に含める。タイル生値→材料スケールの変換係数は
実行時（DBの収録年数等）にしか決まらないため、`weight`フィールドへ静的に
焼き込めない代わりに、`GET /api/axis-catalog`が返す`material_runtime_scales`
（実行時に1回だけ解決するグローバル定数）をフロントのJS式が追加で掛け合わせる
（`frontend/src/components/Map/axisLayers.ts: buildAxisRampValueExpression`参照）。

auto-derive自体は成功しても、`derive_ramp_inputs`が返す`thresholds`は元の
`AxisDefinition.shape.breakpoints`のX軸スケールをそのまま流用するため、複数材料の
組み合わせ（car_stress）や単純な線形正規化（accident）では1〜2段階の
粗い色分けしか作れないことがある。この「色分け粒度の好み」は自動導出の能力とは
別問題のため、`AxisDefinition.display_thresholds_override`（軸スタジオのGUIが編集する
軽量な数値配列）で上書きする（`axis_display_for()`参照）。
"""

from dataclasses import dataclass
from itertools import combinations
from typing import cast


from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
)
from app.domain.material_catalog import MATERIAL_CATALOG, MaterialSpec
from app.domain.registry import AxisDisplaySpec, TileInputSpec
from app.domain.strict_model import StrictModel


class RampInputs(StrictModel):
    tile_inputs: list[TileInputSpec]
    thresholds: list[float]


def _adjacent_midpoint_thresholds(scores: list[float]) -> list[float]:
    """スコアの集合から、ソート済み隣接値の中間点を閾値として返す
    （bool2値の`[(lower+upper)/2]`をN値へ一般化したもの）。"""
    ordered = sorted(set(scores))
    return [(a + b) / 2 for a, b in zip(ordered, ordered[1:])]


def _boolean_terms_thresholds(weights: list[float], cap: float | None) -> list[float]:
    """全termがboolean材料のBreakpointLinearShape向け。各termは該当時weight・非該当時0の
    2値しか取らないため、達成しうる合計値は「重みの空集合込み全部分和」に限られる
    （連続値と異なり中間の値を取らない）。この部分和集合（capでクランプ後）の隣接中間点を
    閾値として返す。

    達成しうる合計値の集合を求めるところまでをここが担い、閾値化自体は
    `_adjacent_midpoint_thresholds`へ委ねる（将来中間点の計算式[丸め・重み付け等]を
    変更する際、片方だけ直し忘れて挙動が乖離するのを防ぐ）。
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
    変換する共通ヘルパー。

    `has_unknown_fallback`は`spec.bool_default`から決める——固定でTrueにすると、
    bool_default="false"（欠損=確定false、例: motor_vehicle_no・is_designated）の材料でも
    「不明」[灰色]表示になってしまう（surface_good等bool_default="nan"[欠損=真に不明]の
    材料でのみ正しい）。

    `spec.tile_property_categorical_true_values`が設定されている材料（
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
    乗せる。`categories`・真偽値(`boolean`)のTileInputSpecは寄与値を
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
    """`MaterialTerm.material`が他の軸を指す場合（軸階層、例:
    car_stressが参照する5つの内部軸）に、その参照先の軸を再帰的に解決し、外側の
    重み(`weight`)を乗せた1件のTileInputSpecへ変換する。

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


def raw_value_unit(definition: AxisDefinition) -> str | None:
    """軸の**生値**（折れ点を通す前の重み付き和）の単位。定まらない場合はNone。

    ルート結果は得点（0〜100の相対評価）だけでは軸単体で経路を判断できない。生値を
    その単位とともに添えると、他の軸を見ずに「多いか少ないか」を判断できる
    （docs/tasks/T687.md参照）。

    単位が定まる条件は次の4つ。重み0の項は生値へ寄与しないため判定から除く。

    1. 材料が単位を持ち、複数あるならすべて一致する（異なる単位の材料を足した値には
       単位が無い。例: 車の圧迫感は内部軸の合成）。
    2. 重みがすべて正である（負の重みが混じると和は物理量の符号を反転したものになる）。
    3. 重みがすべてちょうど1である。生値は`Σ(材料値 × weight)`なので、1以外の重みは
       材料の値をスケールし直した量になり、材料の単位では読めない（重み付きの
       「1kmあたり1.5回として数えた踏切」を含む和は、実際の回/kmではない）。
    4. 項が2つ以上なら、全材料が`additive`（足し合わせて意味を持つ量）である。

    4が要るのは、**単位が揃っていても和の意味は保証されない**ため。%・km/h・倍率のような
    割合・率は、母数の違うものを足しても何も表さない（開放度の`樹木% + 建物%`が実例）。
    足せるのは回・件・個のような個数と、それを同じ距離で割った密度だけ。項が1つのときは
    そもそも和ではないので、この条件は課さない（勾配の「平均3.2%」は意味を持つ）。
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


@dataclass(frozen=True, slots=True)
class AxisMaterialShare:
    """軸が参照する材料1件と、それが軸の生値に占める正規化重み。"""

    material_id: str
    #: 各階層で `|w| / Σ|w|` を取り、根から葉まで掛け合わせた値（0〜1）。
    share: float
    #: 根の軸からの探索の深さ（直接のtermが0）。同率の並び替えに使う。
    depth: int


def _shape_terms(definition: AxisDefinition) -> list[tuple[str, float]]:
    """shapeの参照先を `(材料idまたは軸id, 重み)` の列で返す。

    `CategoricalShape`は単一の参照先を持ち重みの概念が無いため、重み1の1項として扱う。
    """
    shape = definition.shape
    if isinstance(shape, BreakpointLinearShape):
        return [(term.material, term.weight) for term in shape.terms]
    return [(shape.material, 1.0)]


def axis_material_shares(definition: AxisDefinition) -> list[AxisMaterialShare]:
    """軸を材料まで再帰的に分解し、正規化重みの降順（同率は浅い順・定義順）で返す。

    得点（0〜100）は目盛りの引き方に依存する相対評価のため、軸単体では経路を判断できない。
    単位が定まる軸は生値を添えれば足りるが（`raw_value_unit`）、単位が定まらない軸
    （合成軸・真偽値やカテゴリの材料を持つ軸）はそれができない。材料まで降りれば、
    どの軸も「較正に依存しない絶対の事実」を出せる（docs/tasks/T689.md参照）。

    **辿る先は必ず材料**で、途中の軸の得点は結果に含めない。得点を内訳へ混ぜると、
    この関数が解こうとしている「較正依存の数字しか出せない」問題が入れ子で再発する。

    **重みは階層ごとに正規化してから掛ける。** 生の重みを階層をまたいで掛けても意味が無い
    （内部軸の`breakpoints`・`mapping`は非線形変換のため、外側の重み1.0と内側の重み1.0は
    別のスケール）。一方、同じshapeの中のtermどうしは比較可能である——重み付き和が得点として
    意味を持つよう作者が重みを決めていることが前提だから。したがって各階層で
    `|w| / Σ|w|`を取ってから掛け合わせれば、葉まで一貫した「占める割合」になる。

    重み0の項は除く（得点に一切寄与しないものを事実として出すと誤読を招く）。同じ材料へ
    別経路から到達した場合は最初の1件だけを残す（同じ物理量を2回出しても情報が増えない）。

    **参照先が1件へ分解される軸は空リストを返す。** 呼び出し側は`raw_value_unit`による
    軸単位の生値をそのまま使う。分解しても情報が増えないうえ、`shape.preprocess`
    （勾配の`"abs"`）が材料単位では効かず、登りと下りが相殺されて平均がほぼ0になるため。
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
            continue  # 軸参照: 個別のtile_property等はここでは検証しない
            # （_resolve_referenced_axis_tile_inputが参照先の材料を辿って検証する）。
        if spec.tile_property is None or spec.tile_property_direction_dependent:
            return None
        # tile_property_needs_runtime_scaleはここでは弾かない。
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
        # bool2値以外（str N値）のramp化。`registry.py: TileInputSpec.
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
                    # `evaluate_categorical`は未登録値をNone（評価不能）として扱うため、
                    # 地図側も「未登録値=寄与0」ではなく「不明」（灰色）へ倒す。
                    # bool2値と同じくhas_unknown_fallback=True固定にする。
                    has_unknown_fallback=True,
                )
            ],
            thresholds=_adjacent_midpoint_thresholds(distinct_scores),
        )

    if isinstance(shape, BreakpointLinearShape):
        if shape.preprocess != "identity":
            # abs前処理は実装しないと確定している（モジュールdocstring
            # 「`preprocess="abs"`対応は実装しないと確定している」節参照）。安全側でNone。
            return None
        # 既知の制約（意図的に許容）: 評価側（evaluate_axis_scalar/
        # evaluate_axis_array）はrequired=Trueの材料が欠損していれば軸全体をNone/NaN
        # （評価不能）にするが、フロント側のΣ(property×weight)expression
        # （buildAxisRampValueExpression）はタイルプロパティ欠損を寄与0として扱う
        # （coalesce）。required=Falseの材料は「欠損時は寄与0」が評価側の意味論そのものの
        # ため**1つでも値がある限り**両者は一致するが、次の2つの場合は食い違い、本来
        # 「評価不能」な区間が地図上では「評価済みで良好（緑）」に誤表示されうる:
        # (a) required=Trueの材料が欠損している場合、(b) 全termがrequired=Falseで、その
        # **全ての材料が欠損**している場合（評価側は軸全体を欠損とするが、地図側は全項を
        # 0埋めして寄与0＝最良帯として塗る。全term required=Falseの軸[openness等]で
        # 事前集計が未実施のwayが該当する）
        # （TileInputSpecには数値材料の「不明」表現手段が無い——has_unknown_fallbackは
        # 真偽値/N値カテゴリカル材料専用、buildAxisRampUnknownExpression参照）。
        # required=Trueの材料を持つ軸も自動導出の対象にする（gradient・accident等、
        # 公開軸の多くが該当する）。実務上は「必須材料がway単位の事前集計で欠損する」
        # ケース自体が稀（way_attribute_countsは欠損時0埋めが基本）なため実害は限定的だが、
        # GUI作成軸でrequired=True材料が実際にタグ欠損しやすい場合は、この不整合を
        # 認識した上で運用すること（現時点で個別の軸だけ回避する手段は無い）。
        tile_inputs = []
        for term in shape.terms:
            spec = specs.get(term.material)
            if spec is None:
                # 材料ではなく他の軸を指す（軸階層、例: car_stressの
                # 5つの内部軸参照）。参照先を再帰的に解決する。
                resolved = _resolve_referenced_axis_tile_input(term.material, term.weight, visited)
                if resolved is None:
                    return None
                tile_inputs.append(resolved)
                continue
            assert spec.tile_property is not None  # 上のspecsループで確認済み
            if spec.dtype == "boolean":
                # 該当時term.weight・非該当時0の2値。
                tile_inputs.append(
                    TileInputSpec(
                        property=spec.tile_property,
                        boolean=True,
                        true_value=term.weight,
                        false_value=0.0,
                    )
                )
            else:
                # tile_property_needs_runtime_scaleな材料（例:
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
            # 全termがboolean材料なら、達成しうる合計値は部分和集合に限られる
            # （連続値と異なり中間の値を取らない）ため、その隣接中間点を閾値とする
            # （cap相当はbreakpointsの最終x値）。全部分和は2^N-1通りの組合せ爆発を
            # 避けるため、term数の上限を設ける（GUIは今のところ「材料の天井」で
            # 実質12を超えない想定だが、直接API呼び出しでは制限されないため）。
            if len(shape.terms) > 12:
                return None
            cap = shape.breakpoints[-1][0]
            thresholds = _boolean_terms_thresholds([term.weight for term in shape.terms], cap)
        else:
            # total=Σ(material_value×term.weight)は評価側の量とフロント表示側の量が
            # 完全に同一の演算のため、term数・重みによらずshape.breakpointsのx値
            # （先頭除く）をそのまま閾値として流用できる（モジュールdocstring参照。
            # 連続値は中間の値も取りうるためboolean限定ケースと異なる）。
            thresholds = [bp[0] for bp in shape.breakpoints[1:]]
        return RampInputs(tile_inputs=tile_inputs, thresholds=thresholds)

    return None


def primary_attribute_ids_for(definition: AxisDefinition) -> list[str]:
    """軸が参照する材料を一次属性idへ解決する。`AxisDefinition.materials`は材料idだけで
    なく他の軸id（階層構造、例: car_stressの内部軸6つ）も返しうるため、
    材料id側で見つからないエントリはAXIS_DEFINITIONSの軸として再帰的に解決する
    （内部軸自体も内部軸を参照しうる想定はないが、循環参照は軸スタジオ側で拒否済み
    [test_create_rejects_direct_cycle_between_two_axes]のため`visited`で安全側に保護する）。

    `api/routers/axis_catalog.py`（GET /api/axis-catalog、実行時API）と
    `registry_defaults.py`（`export_openapi.py`向けのビルド時静的axis-catalog.json生成）
    の両方がこの関数を共有する（片側import。軸ごとに手書きで重複させない）。
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
    """軸の地図表示宣言。`GET /api/axis-catalog`が公開軸すべてに対して呼ぶ想定の純粋関数
    （`AXIS_DEFINITIONS`・`MATERIAL_CATALOG`というプロセス内メモリだけを見る、DB/IO無し）。

    優先順位:
    ①`derive_ramp_inputs()`が自動導出に成功し、かつ`definition.display_thresholds_override`
    （軸スタジオのGUIが編集する、色分けしきい値だけの軽量な上書き）が設定されていれば、
    自動導出した`tile_inputs`とこのしきい値を組み合わせる。
    ②`derive_ramp_inputs()`が成功し`display_thresholds_override`が無ければ、自動導出した
    しきい値をそのまま使う。
    ③`derive_ramp_inputs()`自体が失敗すれば`kind="none"`。

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
