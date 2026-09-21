import pytest

from app.domain.registry import (
    AxisInputConflictError,
    AxisSpec,
    PrimaryAttributeSpec,
    all_axes,
    all_primary_attributes,
    register_axis,
    register_primary_attribute,
    reset_registry_for_testing,
)


@pytest.fixture(autouse=True)
def _isolated_registry():
    """他のテストファイルのimportで登録された内容が残っていても、このファイルの各テストは
    空のレジストリから始まり、終了後も空に戻す。"""
    reset_registry_for_testing()
    yield
    reset_registry_for_testing()


def _attr(attr_id: str) -> PrimaryAttributeSpec:
    return PrimaryAttributeSpec(attr_id=attr_id, label=f"test label {attr_id}")


class TestRegisterPrimaryAttribute:
    def test_registers_and_retrieves(self):
        register_primary_attribute(_attr("attr_a"))
        assert all_primary_attributes()[0].attr_id == "attr_a"
        assert len(all_primary_attributes()) == 1

    def test_duplicate_attr_id_raises(self):
        register_primary_attribute(_attr("attr_a"))
        with pytest.raises(ValueError, match="already registered"):
            register_primary_attribute(_attr("attr_a"))


class TestRegisterAxis:
    def test_registers_axis_with_known_inputs(self):
        register_primary_attribute(_attr("attr_a"))
        register_axis(AxisSpec(axis_id="axis_a", inputs=["attr_a"]))
        assert all_axes()[0].axis_id == "axis_a"
        assert len(all_axes()) == 1

    def test_unknown_input_raises(self):
        with pytest.raises(ValueError, match="unregistered primary attribute"):
            register_axis(AxisSpec(axis_id="axis_a", inputs=["attr_a"]))

    def test_duplicate_axis_id_raises(self):
        register_primary_attribute(_attr("attr_a"))
        spec = AxisSpec(axis_id="axis_a", inputs=["attr_a"])
        register_axis(spec)
        with pytest.raises(ValueError, match="already registered"):
            register_axis(spec)

    def test_two_axes_with_disjoint_inputs_both_register(self):
        register_primary_attribute(_attr("attr_a"))
        register_primary_attribute(_attr("attr_b"))
        register_axis(AxisSpec(axis_id="axis_a", inputs=["attr_a"]))
        register_axis(AxisSpec(axis_id="axis_b", inputs=["attr_b"]))
        assert {axis.axis_id for axis in all_axes()} == {"axis_a", "axis_b"}

    def test_overlapping_input_raises_axis_input_conflict(self):
        register_primary_attribute(_attr("attr_a"))
        register_axis(AxisSpec(axis_id="axis_a", inputs=["attr_a"]))
        with pytest.raises(AxisInputConflictError) as exc_info:
            register_axis(AxisSpec(axis_id="axis_b", inputs=["attr_a"]))
        assert exc_info.value.new_axis_id == "axis_b"
        assert exc_info.value.existing_axis_id == "axis_a"
        assert exc_info.value.overlapping_attrs == {"attr_a"}
        # 衝突した軸は登録されないまま（部分登録によるレジストリの不整合を防ぐ）
        assert "axis_b" not in {axis.axis_id for axis in all_axes()}
