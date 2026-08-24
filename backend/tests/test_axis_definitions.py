import pytest

from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    AxisMaterialConflictError,
    AxisPublishedImmutableError,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
    car_stress_display_level,
    check_material_exclusivity,
    check_publish_immutability,
    evaluate_axis_scalar,
)


def test_car_stress_lanes_adjustment_applies_regardless_of_separated_cycleway():
    # 改善計画T292回帰テスト: 旧car_stress_levelは「分離自転車道(cycleway=track)がある
    # 区間ではlanes_low(-1)補正を無効化する」という条件分岐を持っていたが、実データ確認
    # （dev DB 2026-08-19、該当ほぼ皆無）によりユーザー承認の上で撤廃し常時適用にした
    # （axis_definitions.py: car_stress_lanes_adjustmentのコメント参照）。この単純化を
    # 将来誤って部分的に復活させないための回帰テスト。
    lanes_adjustment = AXIS_DEFINITIONS["car_stress_lanes_adjustment"]

    with_separated_cycleway = evaluate_axis_scalar(lanes_adjustment, {"lanes_count": 1.0, "bicycle_infra": "separated"})
    without_cycleway = evaluate_axis_scalar(lanes_adjustment, {"lanes_count": 1.0, "bicycle_infra": None})

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
    {"gradient", "wind", "surface_q", "stop_density", "car_stress", "accident", "night"}
)


def test_builtin_seven_axes_are_all_published():
    # 改善計画T271完了条件: 既存7軸（本番稼働中、一般ユーザーへ既に公開済み）は
    # is_published=Trueでなければならない（backfill漏れ・既定値の取り違えを防ぐ）。
    # 改善計画T292: car_stress軸を支える内部軸（is_published=False、他の公開軸から
    # 参照される専用の推定軸）がAXIS_DEFINITIONSへ加わったため、対象を公開7軸へ絞る。
    for axis_id in PUBLISHED_AXIS_IDS:
        assert AXIS_DEFINITIONS[axis_id].is_published is True


def test_internal_axes_are_not_published():
    # 上のテストと対になる確認: 公開7軸以外（car_stressを支える内部軸）は
    # is_published=Falseのまま運用する（改善計画T292、内部軸の恒久的な終着点）。
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
