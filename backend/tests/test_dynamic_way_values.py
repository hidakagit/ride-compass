"""domain/dynamic_way_values.py: DYNAMIC_WAY_VALUE_MATERIALS宣言のテスト（改善計画T423）。"""

from app.domain.dynamic_way_values import DYNAMIC_WAY_VALUE_MATERIALS


def test_wind_needs_time_and_bearing():
    wind = DYNAMIC_WAY_VALUE_MATERIALS["wind"]
    assert wind.needs_time is True
    assert wind.needs_bearing is True


def test_gradient_needs_bearing_only():
    # docs/tasks/T423.md確定済みの設計判断: 勾配は時刻非依存・向きのみ依存。
    gradient = DYNAMIC_WAY_VALUE_MATERIALS["gradient"]
    assert gradient.needs_time is False
    assert gradient.needs_bearing is True


def test_material_id_matches_dict_key():
    for key, material in DYNAMIC_WAY_VALUE_MATERIALS.items():
        assert material.material_id == key
