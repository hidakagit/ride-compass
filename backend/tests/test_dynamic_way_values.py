"""domain/dynamic_way_values.py: dynamic_way_value_materials()宣言のテスト
（改善計画T423、T458でAXIS_DEFINITIONS由来の動的導出へ変更）。"""

from app.domain.axis_definitions import AXIS_DEFINITIONS, AxisDefinition, BreakpointLinearShape, MaterialTerm
from app.domain.dynamic_way_values import (
    dynamic_way_value_materials,
    map_value_kind,
    map_value_unit,
    transform_dedicated_way_values,
)
from tests.realistic_axis_fixtures import axis_definitions_snapshot


def _axis(
    axis_id: str,
    dedicated_way_value_layer: bool,
    dynamic_way_value_needs_time: bool = False,
    dynamic_way_value_needs_bearing: bool = False,
) -> AxisDefinition:
    return AxisDefinition(
        axis_id=axis_id,
        shape=BreakpointLinearShape(terms=[MaterialTerm(material="gradient_percent")], breakpoints=[(0.0, 0.0), (10.0, 100.0)]),
        default_weight=0.1,
        label=f"テスト軸[{axis_id}]",
        dedicated_way_value_layer=dedicated_way_value_layer,
        dynamic_way_value_needs_time=dynamic_way_value_needs_time,
        dynamic_way_value_needs_bearing=dynamic_way_value_needs_bearing,
    )


def test_derives_only_dedicated_way_value_layer_axes():
    fake_definitions = {
        "wind": _axis("wind", dedicated_way_value_layer=True, dynamic_way_value_needs_time=True, dynamic_way_value_needs_bearing=True),
        "gradient": _axis("gradient", dedicated_way_value_layer=True, dynamic_way_value_needs_bearing=True),
        "car_stress": _axis("car_stress", dedicated_way_value_layer=False),
    }
    with axis_definitions_snapshot():
        AXIS_DEFINITIONS.clear()
        AXIS_DEFINITIONS.update(fake_definitions)

        materials = dynamic_way_value_materials()

        assert set(materials) == {"wind", "gradient"}


def test_wind_needs_time_and_bearing(monkeypatch):
    monkeypatch.setitem(
        AXIS_DEFINITIONS, "wind",
        _axis("wind", dedicated_way_value_layer=True, dynamic_way_value_needs_time=True, dynamic_way_value_needs_bearing=True),
    )

    wind = dynamic_way_value_materials()["wind"]

    assert wind.needs_time is True
    assert wind.needs_bearing is True


def test_gradient_needs_bearing_only(monkeypatch):
    # docs/tasks/T423.md確定済みの設計判断: 勾配は時刻非依存・向きのみ依存。
    monkeypatch.setitem(
        AXIS_DEFINITIONS, "gradient",
        _axis("gradient", dedicated_way_value_layer=True, dynamic_way_value_needs_bearing=True),
    )

    gradient = dynamic_way_value_materials()["gradient"]

    assert gradient.needs_time is False
    assert gradient.needs_bearing is True


def test_material_id_matches_dict_key():
    for key, material in dynamic_way_value_materials().items():
        assert material.material_id == key


def test_map_value_kind_is_signed_material_only_for_single_abs_term_axes():
    assert map_value_kind(AXIS_DEFINITIONS["gradient"]) == "signed_material"
    assert map_value_kind(AXIS_DEFINITIONS["wind"]) == "difficulty"
    assert map_value_kind(AXIS_DEFINITIONS["car_stress"]) == "difficulty"


def test_map_value_unit_comes_from_material_catalog_for_signed_material_only():
    assert map_value_unit(AXIS_DEFINITIONS["gradient"]) == "%"
    assert map_value_unit(AXIS_DEFINITIONS["wind"]) == ""


def test_transform_evaluates_difficulty_with_axis_breakpoints_and_clamps():
    wind = AXIS_DEFINITIONS["wind"]  # breakpoints [(0,0),(8,100)]
    result = transform_dedicated_way_values(wind, "wind_penalty", {1: 0.0, 2: 4.0, 3: 8.0, 4: -3.0, 5: 12.0})
    assert result == {1: 0.0, 2: 50.0, 3: 100.0, 4: 0.0, 5: 100.0}


def test_transform_passes_signed_material_through_unchanged():
    gradient = AXIS_DEFINITIONS["gradient"]
    values = {10: -4.2, 11: 3.1}
    assert transform_dedicated_way_values(gradient, "gradient_percent", values) == values


def test_transform_drops_ways_the_axis_cannot_evaluate_from_one_material():
    two_materials = AxisDefinition(
        axis_id="two_materials",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="wind_penalty"), MaterialTerm(material="lanes_count")],
            breakpoints=[(0.0, 0.0), (10.0, 100.0)],
        ),
        default_weight=0.1,
        label="2材料",
        dedicated_way_value_layer=True,
    )
    assert transform_dedicated_way_values(two_materials, "wind_penalty", {1: 3.0}) == {}
