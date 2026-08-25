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
    """他のテストファイル（test_registry_defaults.py等）のimportで登録された内容が
    残っていても、このファイルの各テストは空のレジストリから始まり、終了後も空に戻す。"""
    reset_registry_for_testing()
    yield
    reset_registry_for_testing()


def _attr(attr_id: str, shared: bool = False) -> PrimaryAttributeSpec:
    return PrimaryAttributeSpec(
        attr_id=attr_id,
        label=f"test label {attr_id}",
        shared=shared,
    )


class TestRegisterPrimaryAttribute:
    def test_registers_and_retrieves(self):
        register_primary_attribute(_attr("surface"))
        assert all_primary_attributes()[0].attr_id == "surface"
        assert len(all_primary_attributes()) == 1

    def test_duplicate_attr_id_raises(self):
        register_primary_attribute(_attr("surface"))
        with pytest.raises(ValueError, match="already registered"):
            register_primary_attribute(_attr("surface"))


class TestRegisterAxis:
    def test_registers_axis_with_known_inputs(self):
        register_primary_attribute(_attr("surface"))
        register_axis(AxisSpec(axis_id="surface_q", inputs=["surface"]))
        assert all_axes()[0].axis_id == "surface_q"
        assert len(all_axes()) == 1

    def test_unknown_input_raises(self):
        with pytest.raises(ValueError, match="unregistered primary attribute"):
            register_axis(AxisSpec(axis_id="surface_q", inputs=["surface"]))

    def test_duplicate_axis_id_raises(self):
        register_primary_attribute(_attr("surface"))
        spec = AxisSpec(axis_id="surface_q", inputs=["surface"])
        register_axis(spec)
        with pytest.raises(ValueError, match="already registered"):
            register_axis(spec)

    def test_two_axes_with_disjoint_inputs_both_register(self):
        register_primary_attribute(_attr("surface"))
        register_primary_attribute(_attr("lit"))
        register_axis(AxisSpec(axis_id="surface_q", inputs=["surface"]))
        register_axis(AxisSpec(axis_id="night", inputs=["lit"]))
        assert {axis.axis_id for axis in all_axes()} == {"surface_q", "night"}

    def test_overlapping_non_shared_input_raises_axis_input_conflict(self):
        register_primary_attribute(_attr("highway"))
        register_axis(AxisSpec(axis_id="car_stress", inputs=["highway"]))
        with pytest.raises(AxisInputConflictError) as exc_info:
            register_axis(AxisSpec(axis_id="safety", inputs=["highway"]))
        assert exc_info.value.new_axis_id == "safety"
        assert exc_info.value.existing_axis_id == "car_stress"
        assert exc_info.value.overlapping_attrs == {"highway"}
        # 衝突した軸は登録されないまま(部分登録によるレジストリの不整合を防ぐ)
        assert "safety" not in {axis.axis_id for axis in all_axes()}

    def test_shared_input_does_not_conflict(self):
        register_primary_attribute(_attr("highway"))
        register_primary_attribute(_attr("geometry", shared=True))
        register_axis(AxisSpec(axis_id="car_stress", inputs=["highway", "geometry"]))
        # 2つ目の軸も"geometry"(shared)を使うが、highwayを使わなければ衝突しない
        register_axis(AxisSpec(axis_id="gradient", inputs=["geometry"]))
        assert {axis.axis_id for axis in all_axes()} == {"car_stress", "gradient"}
