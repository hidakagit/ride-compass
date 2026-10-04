"""`services/dedicated_way_values.py`の登録表——材料→配信サービスの対応を、登録済みの全サービスに対して確かめる。

材料idが材料カタログの既知材料であること、組み立てたサービスがその材料の値を返すこと、受け取る条件を
要求から組み立てられること、1つの材料を2つのサービスが担当していないことを見る。

ここで見ないもの:
- 軸から配信を選ぶこと・区間インスペクタが足す材料（`DirectionalMaterialService`） → `test_region_routes.py`
- 地図が載せる条件の名前（`dedicated_way_value_conditions`） → `test_axis_catalog_routes.py`
- 各サービスが返す値 → `test_gradient_way_service.py`・`test_rain_way_service.py`・`test_wind_way_service.py`
"""

from dataclasses import fields
from typing import get_args

import pytest

from app.domain.dynamic_way_values import WayValueConditionName, WayValueQuery
from app.services.dedicated_way_values import (
    DEDICATED_WAY_VALUE_SERVICES,
    DEDICATED_WAY_VALUE_SERVICES_BY_MATERIAL,
    services_by_material,
)
from app.domain.material_catalog import is_known_material
from app.services.weather_service import WeatherService


def test_every_service_material_id_is_a_known_material():
    """`material_id`は材料カタログの既知材料であること（軸idを誤って渡すと
    `transform_dedicated_way_values`が軸を評価できず無音で全道路が色なしになる）。"""
    weather_service = WeatherService()
    for material_id, service_type in DEDICATED_WAY_VALUE_SERVICES_BY_MATERIAL.items():
        service = service_type.build(object(), weather_service, material_id=material_id)
        assert service.material_id == material_id
        assert is_known_material(material_id)


def test_every_service_takes_only_conditions_the_request_carries():
    """条件の欄は要求（`WayValueQuery`）の同じ名前の欄から組み立て（`assemble_conditions`）、欄の名前は
    `WayValueConditionName`として地図へ配る。どちらかに無い名前の欄を持つと、その材料の配信は毎回組み立てで
    落ちるか、地図がその条件を載せない。"""
    carried = set(get_args(WayValueConditionName)) & {field.name for field in fields(WayValueQuery)}
    for service in DEDICATED_WAY_VALUE_SERVICES:
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
        services_by_material((First, Second))
