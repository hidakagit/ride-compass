"""registry_defaults.register_defaults()（既存の一次属性・二次軸の既定登録）が、
コード変更なしに実行できること・排他検証を通ることを確認する（改善計画T137）。
"""

import pytest

from app.domain import registry
from app.domain.registry_defaults import register_defaults


@pytest.fixture(autouse=True)
def _defaults_registered():
    registry.reset_registry_for_testing()
    register_defaults()
    yield
    registry.reset_registry_for_testing()


def test_default_primary_attributes_are_registered():
    attr_ids = {attr.attr_id for attr in registry.all_primary_attributes()}
    assert {
        "highway",
        "lanes",
        "maxspeed",
        "cycleway",
        "surface",
        "bicycle_access",
        "motor_vehicle_access",
        "lit",
        "tunnel",
        "designation",
        "elevation",
        "stop_poi",
        "supply_poi",
        "accident_point",
        "intersection",
        "geometry",
    }.issubset(attr_ids)


def test_default_axes_are_registered_without_conflict():
    # 設計プロンプトが示す目標の6軸（car_stress/accident/surface_q/stop_density/gradient/night）
    # と一致する（T137〜T149を経て到達）。
    axis_ids = {axis.axis_id for axis in registry.all_axes()}
    assert axis_ids == {"gradient", "surface_q", "stop_density", "accident", "car_stress", "night"}


def test_intersection_density_is_not_a_standalone_axis():
    """交差点密度は単独軸を持たず、stop_density軸のinputsへ吸収する
    （設計プロンプト改訂2026-08-18「現行9軸からの帰属先」、改善計画T149で実装済み）。"""
    axis_ids = {axis.axis_id for axis in registry.all_axes()}
    assert "intersection_density" not in axis_ids
    assert registry.get_axis("stop_density").inputs == ["stop_poi", "intersection"]


def test_safety_and_bicycle_infra_axes_are_deliberately_not_registered():
    """安全度（旧`domain/safety.py`）は難易度合成からT139で外れ、そもそも軸として登録した
    ことがなく、T148で`domain/safety.py`自体も削除済み。自転車インフラはT138でcar_stressへ
    統合済みのため独立軸を持たない（モジュールdocstring参照）。"""
    axis_ids = {axis.axis_id for axis in registry.all_axes()}
    assert axis_ids.isdisjoint({"traffic_stress", "safety", "bicycle_infra"})


def test_car_stress_axis_input_is_exclusive_of_cycleway():
    car_stress_axis = registry.get_axis("car_stress")
    assert "cycleway" in car_stress_axis.inputs
    for axis in registry.all_axes():
        if axis.axis_id != "car_stress":
            assert "cycleway" not in axis.inputs


def test_night_axis_inputs_are_lit_and_tunnel():
    night_axis = registry.get_axis("night")
    assert set(night_axis.inputs) == {"lit", "tunnel"}


def test_accident_axis_input_is_exclusively_accident_point():
    accident_axis = registry.get_axis("accident")
    assert accident_axis.inputs == ["accident_point"]


def test_supply_poi_is_registered_but_used_by_no_axis():
    assert registry.get_primary_attribute("supply_poi") is not None
    for axis in registry.all_axes():
        assert "supply_poi" not in axis.inputs


def test_register_defaults_is_idempotent_guarded():
    """2回連続で呼ぶと(register_primary_attributeが)ValueErrorを送出する
    （二重登録によるレジストリ不整合を防ぐ、モジュールdocstring参照）。"""
    with pytest.raises(ValueError, match="already registered"):
        register_defaults()
