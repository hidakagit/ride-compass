"""専用way値配信サービス（WindWayService/GradientWayService）の登録規約のテスト。

サービスは自分が返す材料（`material_id`）だけを宣言し、軸との対応は軸定義が参照する
材料から引く。材料idが材料カタログの既知材料であること、1つの材料を2つのサービスが
担当していないことを、登録済みの全サービスに対して確かめる。
"""

import pytest

from app.api.dependencies import _DEDICATED_WAY_VALUE_SERVICE_FACTORIES, _factories_by_material
from app.domain.material_catalog import is_known_material
from app.services.weather_service import WeatherService


def test_every_service_material_id_is_a_known_material():
    """`material_id`は材料カタログの既知材料であること（軸idを誤って渡すと
    `transform_dedicated_way_values`が軸を評価できず無音で全道路が色なしになる）。"""
    weather_service = WeatherService()
    for material_id, factory in _DEDICATED_WAY_VALUE_SERVICE_FACTORIES.items():
        service = factory(None, weather_service)
        assert service.material_id == material_id
        assert is_known_material(material_id)


def test_two_services_for_one_material_fail_at_registration():
    class First:
        material_id = "gradient_percent"

        @classmethod
        def build(cls, repository, weather_service):
            return cls()

    class Second(First):
        pass

    with pytest.raises(RuntimeError, match="gradient_percent"):
        _factories_by_material((First, Second))
