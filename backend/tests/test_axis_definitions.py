import pytest

from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    AxisMaterialConflictError,
    AxisPublishedImmutableError,
    BreakpointLinearShape,
    MaterialTerm,
    check_material_exclusivity,
    check_publish_immutability,
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
