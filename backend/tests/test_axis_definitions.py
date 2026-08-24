import pytest

from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    AxisMaterialConflictError,
    AxisPublishedImmutableError,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
    check_material_exclusivity,
    check_publish_immutability,
    evaluate_axis_scalar,
)


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


def test_car_stress_motor_vehicle_no_safety_margin_exceeds_other_internal_axes_max_total():
    # 改善計画T292回帰テスト: car_stress_motor_vehicle_no_adjustmentの-1000は、他の
    # 全内部軸（highway基準値+bicycle_infra/maxspeed/lanes/designation補正）の点数
    # レンジ合計を確実に下回る大きさの安全マージンとして選ばれている（axis_definitions.py:
    # car_stress_motor_vehicle_no_adjustmentのコメント「この値を変更する場合、他の
    # 内部軸の点数レンジの合計を必ず上回る負の大きさを維持すること」参照）。この不変条件は
    # コード上で検査されずコメントの注意書きのみで守られていたため、将来いずれかの内部軸の
    # 点数レンジが拡張された際に安全マージンが不足する回帰を検知できるようテスト化する。
    other_internal_axis_ids = [
        "car_stress_highway_base",
        "car_stress_bicycle_infra_adjustment",
        "car_stress_maxspeed_adjustment",
        "car_stress_lanes_adjustment",
        "car_stress_designation_adjustment",
    ]
    max_other_total = 0.0
    for axis_id in other_internal_axis_ids:
        shape = AXIS_DEFINITIONS[axis_id].shape
        if isinstance(shape, CategoricalShape):
            max_other_total += max(shape.mapping.values())
        else:
            assert isinstance(shape, BreakpointLinearShape)
            max_other_total += max(y for _, y in shape.breakpoints)

    motor_vehicle_no_shape = AXIS_DEFINITIONS["car_stress_motor_vehicle_no_adjustment"].shape
    assert isinstance(motor_vehicle_no_shape, CategoricalShape)
    safety_margin_value = motor_vehicle_no_shape.mapping[True]

    assert safety_margin_value < -max_other_total


def test_car_stress_lanes_adjustment_applies_regardless_of_separated_cycleway():
    # 改善計画T292回帰テスト: 旧car_stress_levelは「分離自転車道(cycleway=track)がある
    # 区間ではlanes_low(-1)補正を無効化する」という条件分岐を持っていたが、実データ確認
    # （dev DB 2026-08-19、該当ほぼ皆無）によりユーザー承認の上で撤廃し常時適用にした
    # （axis_definitions.py: car_stress_lanes_adjustmentのコメント参照）。この単純化を
    # 将来誤って部分的に復活させないための回帰テスト（旧
    # test_single_lane_does_not_reduce_when_separated_cycleway_presentの置き換え）。
    lanes_adjustment = AXIS_DEFINITIONS["car_stress_lanes_adjustment"]

    with_separated_cycleway = evaluate_axis_scalar(lanes_adjustment, {"lanes_count": 1.0, "bicycle_infra": "separated"})
    without_cycleway = evaluate_axis_scalar(lanes_adjustment, {"lanes_count": 1.0, "bicycle_infra": None})

    assert with_separated_cycleway == -1.0
    assert without_cycleway == -1.0
