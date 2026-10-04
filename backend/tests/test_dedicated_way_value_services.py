"""専用way値配信サービス（WindWayService/GradientWayService/RainWayService）の登録規約のテスト。

サービスは自分が担当する材料（`material_ids`）だけを宣言し、軸との対応は軸定義が参照する
材料から引く。材料idが材料カタログの既知材料であること、組み立てたサービスがその材料の値を
返すこと、受け取る条件を要求から組み立てられること、1つの材料を2つのサービスが担当していないことを、
登録済みの全サービスに対して確かめる。
"""

from dataclasses import fields
from typing import get_args

import pytest

from app.domain.dynamic_way_values import WayValueConditionName, WayValueQuery
from app.services.dedicated_way_values import (
    _DEDICATED_WAY_VALUE_SERVICES,
    _DEDICATED_WAY_VALUE_SERVICES_BY_MATERIAL,
    _services_by_material,
)
from app.domain.material_catalog import is_known_material
from app.services.weather_service import WeatherService


def test_every_service_material_id_is_a_known_material():
    """`material_id`は材料カタログの既知材料であること（軸idを誤って渡すと
    `transform_dedicated_way_values`が軸を評価できず無音で全道路が色なしになる）。"""
    weather_service = WeatherService()
    for material_id, service_type in _DEDICATED_WAY_VALUE_SERVICES_BY_MATERIAL.items():
        service = service_type.build(object(), weather_service, material_id=material_id)
        assert service.material_id == material_id
        assert is_known_material(material_id)


def test_every_service_takes_only_conditions_the_request_carries():
    """条件の欄は要求（`WayValueQuery`）の同じ名前の欄から組み立てる（`assemble_conditions`）。
    要求に無い名前の欄を持つと、その材料の配信は毎回組み立てで落ちる。軸カタログは欄の名前を
    `WayValueConditionName`として地図へ配るので、その名前の並びも要求の欄と一致する。"""
    carried = {field.name for field in fields(WayValueQuery)}
    assert set(get_args(WayValueConditionName)) == carried
    for service in _DEDICATED_WAY_VALUE_SERVICES:
        assert {field.name for field in fields(service.conditions_type)} <= carried, service


def test_two_services_for_one_material_fail_at_registration():
    class First:
        material_ids = ("gradient_percent",)

        @classmethod
        def build(cls, repository, weather_service, material_id):
            return cls()

    class Second(First):
        pass

    with pytest.raises(RuntimeError, match="gradient_percent"):
        _services_by_material((First, Second))
