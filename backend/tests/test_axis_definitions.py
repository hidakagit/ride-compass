import itertools

import pytest

from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    AxisInternalAxisPublishError,
    AxisMaterialConflictError,
    AxisPublishedImmutableError,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
    car_stress_display_level,
    check_internal_axis_not_published,
    check_material_exclusivity,
    check_publish_immutability,
    evaluate_axis_scalar,
)
from app.domain.recipe import bicycle_infra_flags, cycleway_values

# 改善計画T350: 本ファイルは実際のcar_stress内部軸階層（highway基準値+5補正の加重合成、
# -1000マイナス項の安全マージン等）そのものを検証するため、本番相当の14軸が必要。
# tests/conftest.pyのセッションスコープautouseフィクスチャが全テスト共通で用意する
# （tests/realistic_axis_fixtures.py参照）。

# 改善計画T292由来の旧`_CAR_STRESS_BICYCLE_INFRA_MAPPING`と同じ5値
# （axis_definitions.py参照、地図表示ramp用に現在も定数として維持している）。
_OLD_BICYCLE_INFRA_MAPPING = {
    "separated": -2.0,
    "lane": -1.0,
    "shared_busway": 0.0,
    "shared_pedestrian": 0.0,
    "roadway": 1.0,
}


def _classify_bicycle_infrastructure_reference(tags: dict[str, str], highway: str | None) -> str:
    """改善計画T347で削除したdomain/traffic.py: classify_bicycle_infrastructure
    （優先順位付き分類）の複製。本番コードとしては「Pythonに生データ加工ロジックを
    持たせない」設計原則に反するとして削除したが、このテストファイルが検証している
    「正規化フラグの線形結合が旧分類とどれだけ一致するか（decisions/material-
    normalization-for-axis-composition.md、実データ検証0.0127%ズレ）」という
    回帰保証自体は引き続き価値があるため、テスト専用の参照実装としてここにだけ残す
    （本番からは呼ばれない）。"""
    values = cycleway_values(tags)
    if highway == "cycleway" or "track" in values:
        return "separated"
    if "lane" in values:
        return "lane"
    if any(v in ("share_busway", "shared_lane") for v in values):
        return "shared_busway"
    if highway in ("path", "footway") and tags.get("bicycle") in ("yes", "designated", "permissive"):
        return "shared_pedestrian"
    if tags.get("bicycle") == "no":
        return "prohibited"
    if highway is not None:
        return "roadway"
    return "unknown"


def test_car_stress_bicycle_infra_adjustment_flag_combinations():
    """改善計画T336回帰テスト: car_stress_bicycle_infra_adjustmentをbicycle_infra材料
    （優先順位付き分類）から正規化フラグ材料の線形結合へ置き換えた後も、単独成立時の
    5値（separated/lane/shared_busway/shared_pedestrianの近似先=roadway/roadway）を
    再現すること。"""
    axis = AXIS_DEFINITIONS["car_stress_bicycle_infra_adjustment"]
    base = {
        "highway_is_cycleway": False,
        "cycleway_has_track": False,
        "cycleway_has_lane": False,
        "cycleway_has_shared": False,
    }

    def score(**flags: bool) -> float | None:
        return evaluate_axis_scalar(axis, {**base, **flags})

    assert score() == 1.0  # roadway相当（何も該当しない既定状態）
    assert score(cycleway_has_shared=True) == 0.0  # shared_busway相当
    assert score(cycleway_has_lane=True) == -1.0  # lane相当
    assert score(cycleway_has_track=True) == -2.0  # separated相当
    assert score(highway_is_cycleway=True) == -2.0  # separated相当（highway=cycleway側）
    # 優先順位保持: lane+shared同時成立でもlaneが勝つ（classify_bicycle_infrastructureと
    # 同じ優先順位、線形結合の単純な積み上げでは本来ズレうる箇所）。
    assert score(cycleway_has_lane=True, cycleway_has_shared=True) == -1.0
    # 優先順位保持: track/highway=cyclewayはlane/sharedと同時成立してもseparatedのまま。
    assert score(cycleway_has_track=True, cycleway_has_lane=True, cycleway_has_shared=True) == -2.0
    assert score(highway_is_cycleway=True, cycleway_has_lane=True) == -2.0


def test_car_stress_bicycle_infra_adjustment_matches_bicycle_infra_mapping_exhaustively():
    """改善計画T336回帰テスト: 正規化フラグ材料群への置き換え後も、旧bicycle_infra材料
    ベースのスコア（_OLD_BICYCLE_INFRA_MAPPING、prohibited/unknownは補正なし0点扱い）と
    実質的に一致することを、cycleway系タグ・highway・bicycleタグの組み合わせを網羅する
    形で検証する（decisions/material-normalization-for-axis-composition.mdの実データ検証
    [ズレ0.0127%]と同じ性質の許容ズレを、DBアクセス無しの全数combinatorialで裏付ける）。

    唯一のズレはbicycle由来の分岐（shared_pedestrian: highway×bicycleのAND条件、
    prohibited: bicycle=no）——正規化フラグの線形結合では表現しないと設計判断済みの箇所
    （material_catalog.py: _extract_highway_is_cycleway等のdocstring参照）。cycleway/
    highway由来の判定（track/lane/shared_busway/roadwayの優先順位）は1件のズレも
    無いことをここで担保する。
    """
    axis = AXIS_DEFINITIONS["car_stress_bicycle_infra_adjustment"]
    cycleway_values_domain = [None, "no", "track", "lane", "share_busway", "shared_lane", "opposite_lane", "separate"]
    highways = ["cycleway", "path", "footway", "residential", "primary", "trunk", "living_street"]
    bicycles = [None, "yes", "designated", "permissive", "no", "dismount"]

    mismatches_with_infra_flag = []
    mismatches_without_infra_flag = 0
    total = 0
    for cw, cwl, cwr, cwb, highway, bicycle in itertools.product(
        cycleway_values_domain, cycleway_values_domain, cycleway_values_domain, cycleway_values_domain,
        highways, bicycles,
    ):
        tags = {
            k: v
            for k, v in {
                "cycleway": cw,
                "cycleway:left": cwl,
                "cycleway:right": cwr,
                "cycleway:both": cwb,
                "bicycle": bicycle,
            }.items()
            if v is not None
        }
        total += 1
        old_score = _OLD_BICYCLE_INFRA_MAPPING.get(_classify_bicycle_infrastructure_reference(tags, highway), 0.0)
        flags = bicycle_infra_flags(tags, highway)
        new_score = evaluate_axis_scalar(axis, flags)
        if old_score != new_score:
            if any(flags.values()):
                mismatches_with_infra_flag.append((tags, highway, old_score, new_score))
            else:
                mismatches_without_infra_flag += 1

    assert total > 0
    # cycleway/highway由来の判定（正規化フラグが1つでも成立するケース）は1件もズレない。
    assert mismatches_with_infra_flag == []
    # bicycle由来の分岐（正規化フラグが全て不成立、roadway側へ丸められるケース）のみが
    # ズレうる。0件になった場合はこのアサーションごと更新してよい（設計上許容している
    # 近似の存在を示すための下限チェックであり、0への改善を妨げる意図ではない）。
    assert mismatches_without_infra_flag > 0


def test_car_stress_lanes_adjustment_applies_regardless_of_separated_cycleway():
    # 改善計画T292回帰テスト: 旧car_stress_levelは「分離自転車道(cycleway=track)がある
    # 区間ではlanes_low(-1)補正を無効化する」という条件分岐を持っていたが、実データ確認
    # （dev DB 2026-08-19、該当ほぼ皆無）によりユーザー承認の上で撤廃し常時適用にした
    # （axis_definitions.py: car_stress_lanes_adjustmentのコメント参照）。この単純化を
    # 将来誤って部分的に復活させないための回帰テスト。
    lanes_adjustment = AXIS_DEFINITIONS["car_stress_lanes_adjustment"]

    # lanes_countだけを材料とするaxisのため、分離自転車道の正規化フラグ（cycleway_has_track
    # 等）が立っているかどうかに関わらず同じ結果になることを確認する。
    with_separated_cycleway = evaluate_axis_scalar(
        lanes_adjustment, {"lanes_count": 1.0, "cycleway_has_track": True}
    )
    without_cycleway = evaluate_axis_scalar(lanes_adjustment, {"lanes_count": 1.0, "cycleway_has_track": False})

    assert with_separated_cycleway == -1.0
    assert without_cycleway == -1.0


def _definition(axis_id: str, material: str, is_published: bool = False) -> AxisDefinition:
    return AxisDefinition(
        axis_id=axis_id,
        shape=BreakpointLinearShape(terms=[MaterialTerm(material=material)], breakpoints=[(0.0, 0.0), (10.0, 100.0)]),
        default_weight=0.1,
        label=f"テスト軸[{axis_id}]",
        description="テスト用ダミー軸",
        category="推定",
        is_published=is_published,
    )


def test_builtin_seven_axes_pass_exclusivity_check():
    # 改善計画T268完了条件: 既存7軸のシードデータが検査を通過する（現状の共有設計と
    # 矛盾しない）ことの確認。各軸を「自分以外の全軸」に対して検査する。
    for axis_id, definition in AXIS_DEFINITIONS.items():
        others = {other_id: other for other_id, other in AXIS_DEFINITIONS.items() if other_id != axis_id}
        check_material_exclusivity(definition, others)  # 例外が出ないことを確認


def test_rejects_new_axis_reusing_existing_material():
    existing = {"gradient": AXIS_DEFINITIONS["gradient"]}
    candidate = _definition("gradient_variant", "gradient_percent")

    with pytest.raises(AxisMaterialConflictError) as exc_info:
        check_material_exclusivity(candidate, existing)

    assert exc_info.value.overlapping_materials == {"gradient_percent"}
    assert exc_info.value.conflicting_axis_id == "gradient"


def test_allows_disjoint_materials():
    existing = {"gradient": AXIS_DEFINITIONS["gradient"]}
    candidate = _definition("new_axis", "brand_new_material")

    check_material_exclusivity(candidate, existing)  # 例外が出ないことを確認


def test_update_skips_self_comparison():
    # 更新時、existing辞書に自分自身（同じaxis_id）が含まれていても衝突扱いしない。
    existing = {"gradient": AXIS_DEFINITIONS["gradient"]}
    candidate = _definition("gradient", "gradient_percent")

    check_material_exclusivity(candidate, existing)  # 例外が出ないことを確認


PUBLISHED_AXIS_IDS = frozenset(
    {"gradient", "wind", "surface_q", "stop_density", "car_stress", "accident", "night", "bicycle_infra_quality"}
)


def test_builtin_seven_axes_are_all_published():
    # 改善計画T271完了条件: 既存7軸（本番稼働中、一般ユーザーへ既に公開済み）は
    # is_published=Trueでなければならない（backfill漏れ・既定値の取り違えを防ぐ）。
    # 改善計画T292: car_stress軸を支える内部軸（is_published=False、他の公開軸から
    # 参照される専用の推定軸）がAXIS_DEFINITIONSへ加わったため、対象を公開軸へ絞る。
    # 改善計画T347でbicycle_infra_qualityが加わり公開軸は8つになった（関数名は歴史的名残）。
    for axis_id in PUBLISHED_AXIS_IDS:
        assert AXIS_DEFINITIONS[axis_id].is_published is True


def test_internal_axes_are_not_published():
    # 上のテストと対になる確認: 公開軸（PUBLISHED_AXIS_IDS）以外（car_stressを支える
    # 内部軸）はis_published=Falseのまま運用する（改善計画T292、内部軸の恒久的な終着点）。
    for axis_id, definition in AXIS_DEFINITIONS.items():
        if axis_id not in PUBLISHED_AXIS_IDS:
            assert definition.is_published is False, axis_id


def test_check_publish_immutability_allows_draft():
    draft = _definition("draft_axis", "material_a", is_published=False)

    check_publish_immutability(draft, "updated")  # 例外が出ないことを確認


def test_check_publish_immutability_rejects_published():
    published = _definition("published_axis", "material_a", is_published=True)

    with pytest.raises(AxisPublishedImmutableError) as exc_info:
        check_publish_immutability(published, "deleted")

    assert exc_info.value.axis_id == "published_axis"
    assert exc_info.value.action == "deleted"


# --- check_internal_axis_not_published（T311フォローアップ回帰テスト） ---
# 軸スタジオを開くと未公開の推定軸（内部軸）がルート設定画面に漏れ出た実障害
# （migration適用ラグでDB読み込みが失敗し続け、汚染データが隠れていたケース）を受けて
# 追加したガード。内部軸（他の軸から参照されている軸）をis_published=Trueで保存
# しようとした場合に拒否する。


def _referencing_definition(axis_id: str, referenced_axis_id: str, is_published: bool = True) -> AxisDefinition:
    return AxisDefinition(
        axis_id=axis_id,
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material=referenced_axis_id)], breakpoints=[(0.0, 0.0), (10.0, 100.0)]
        ),
        default_weight=0.1,
        label=f"テスト軸[{axis_id}]",
        description="テスト用ダミー軸",
        category="推定",
        is_published=is_published,
    )


def test_check_internal_axis_not_published_allows_draft():
    internal = _definition("internal_axis", "material_a", is_published=False)
    existing = {"public_axis": _referencing_definition("public_axis", "internal_axis")}

    check_internal_axis_not_published(internal, existing)  # 例外が出ないことを確認


def test_check_internal_axis_not_published_allows_unreferenced_publish():
    unreferenced = _definition("standalone_axis", "material_a", is_published=True)
    existing = {"public_axis": _referencing_definition("public_axis", "internal_axis")}

    check_internal_axis_not_published(unreferenced, existing)  # 例外が出ないことを確認


def test_check_internal_axis_not_published_rejects_publishing_referenced_axis():
    internal = _definition("internal_axis", "material_a", is_published=True)
    existing = {"public_axis": _referencing_definition("public_axis", "internal_axis")}

    with pytest.raises(AxisInternalAxisPublishError) as exc_info:
        check_internal_axis_not_published(internal, existing)

    assert exc_info.value.axis_id == "internal_axis"
    assert exc_info.value.referencing_axis_id == "public_axis"


def test_check_internal_axis_not_published_skips_self_comparison():
    # 更新時、existing辞書に自分自身（同じaxis_id）が含まれていても自己参照とは見なさない。
    existing = {"public_axis": _referencing_definition("public_axis", "public_axis", is_published=True)}
    candidate = existing["public_axis"]

    check_internal_axis_not_published(candidate, existing)  # 例外が出ないことを確認


def test_car_stress_internal_axes_reject_publish_attempt():
    # 実障害の直接的な回帰テスト: car_stressを支える内部軸6つのいずれかを、実際の
    # AXIS_DEFINITIONS構成の中でis_published=Trueにして保存しようとすると拒否される。
    others = {aid: d for aid, d in AXIS_DEFINITIONS.items() if aid != "car_stress_highway_base"}
    candidate = AXIS_DEFINITIONS["car_stress_highway_base"].model_copy(update={"is_published": True})

    with pytest.raises(AxisInternalAxisPublishError) as exc_info:
        check_internal_axis_not_published(candidate, others)

    assert exc_info.value.axis_id == "car_stress_highway_base"
    assert exc_info.value.referencing_axis_id == "car_stress"


# --- car_stress_motor_vehicle_no_adjustmentの-1000固定マイナス項（改善計画T292） ---


def _axis_max_abs_output(definition: AxisDefinition) -> float:
    """1軸が取りうる出力の絶対値の最大（car_stressのBreakpointLinear合成へ加算する
    「点数」としての最大寄与）。car_stress内部軸はCategoricalShapeとBreakpointLinearShapeの
    どちらかのため、この2種類だけを扱う（新しい種類の内部軸が増えたら、このテストの
    メンテナンス時に対応を追加する必要があることを示すため、既知の2種類以外は
    AssertionErrorで明示的に落とす）。
    """
    shape = definition.shape
    if isinstance(shape, CategoricalShape):
        return max(abs(v) for v in shape.mapping.values())
    if isinstance(shape, BreakpointLinearShape):
        return max(abs(y) for _, y in shape.breakpoints)
    raise AssertionError(f"car_stress内部軸に想定外のshape種別: {type(shape).__name__}")


def test_car_stress_motor_vehicle_no_adjustment_dominates_other_internal_axes():
    # コードレビュー指摘の修正確認(finding #4): car_stress_motor_vehicle_no_adjustmentの
    # -1000は「他の全内部軸(motor_vehicle_no補正自身を除く)が同時に最大値を取っても
    # 上回れない」という安全マージンの上で成り立つ設計（axis_definitions.pyの
    # car_stress_motor_vehicle_no_adjustment定義直前のコメント参照）。この不変条件を
    # コード側で検証せず定数だけ変更すると、他の内部軸の点数レンジ次第で
    # motor_vehicle=noの「必ず最良値へ張り付く」保証が黙って壊れる（旧ロジックとの
    # 不一致が再発する）ため、将来の軸編集を検知する回帰テストとして固定する。
    motor_vehicle_no_axis = AXIS_DEFINITIONS["car_stress_motor_vehicle_no_adjustment"]
    assert isinstance(motor_vehicle_no_axis.shape, CategoricalShape)
    guard_value = motor_vehicle_no_axis.shape.mapping[True]

    car_stress = AXIS_DEFINITIONS["car_stress"]
    assert isinstance(car_stress.shape, BreakpointLinearShape)
    other_axis_ids = [
        term.material
        for term in car_stress.shape.terms
        if term.material != "car_stress_motor_vehicle_no_adjustment"
    ]
    max_other_total = sum(_axis_max_abs_output(AXIS_DEFINITIONS[axis_id]) for axis_id in other_axis_ids)

    assert guard_value < 0
    assert abs(guard_value) > max_other_total


# --- car_stress_display_level（改善計画T292のコードレビュー指摘の修正、finding #9/#10） ---


def test_car_stress_display_level_returns_none_for_none():
    assert car_stress_display_level(None) is None


def test_car_stress_display_level_endpoints_match_breakpoints():
    # car_stress軸のbreakpoints((1.0, 0.0), (5.0, 100.0))の逆変換であることの確認。
    assert car_stress_display_level(0.0) == 1
    assert car_stress_display_level(100.0) == 5


def test_car_stress_display_level_rounds_half_up_not_banker_rounding():
    # コードレビュー指摘の修正確認: 組み込みround()は偶数丸め(banker's rounding)のため、
    # difficulty=37.5(level=2.5)はround()だと2、difficulty=62.5(level=3.5)は4という
    # 非対称な結果になっていた。四捨五入(0.5は常に切り上げ)であればどちらもlevel側の
    # 整数部+1で統一される。
    assert car_stress_display_level(37.5) == 3
    assert car_stress_display_level(62.5) == 4


def test_car_stress_display_level_clamps_out_of_range_difficulty():
    assert car_stress_display_level(-10.0) == 1
    assert car_stress_display_level(110.0) == 5


def test_car_stress_display_level_returns_none_when_shape_is_not_breakpoint_linear(monkeypatch):
    """改善計画T320: 以前は`AXIS_DEFINITIONS["car_stress"].shape`が
    BreakpointLinearShapeであることをassertで前提しており、運用者が軸スタジオで
    car_stressの評価式をcategorical等へ作り替えるとAssertionErrorがルート生成の
    たびに500として表面化していた。逆変換が意味を持たない形状へ変わった場合は
    Noneへ安全側に倒すことを確認する。"""
    non_linear_shape = CategoricalShape(material="surface_good", mapping={True: 0.0, False: 80.0})
    monkeypatch.setitem(
        AXIS_DEFINITIONS, "car_stress",
        AXIS_DEFINITIONS["car_stress"].model_copy(update={"shape": non_linear_shape}),
    )

    assert car_stress_display_level(50.0) is None
