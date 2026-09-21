"""専用way値配信サービス（WindWayService/GradientWayService）の登録規約のテスト。

これらの双子サービスは「3件目の雛形」として複写されることを前提にしているため、
axis_id（ルーティングキー＝キャッシュの名前空間）とmaterial_id（返す生値の材料）という
2つの名前空間がサービス間で同じ規約で名付けられていることを機械的に固定する。
"""

from app.api.dependencies import _DEDICATED_WAY_VALUE_SERVICE_FACTORIES
from app.domain.material_catalog import is_known_material
from app.services.weather_service import WeatherService


def _build_all():
    weather_service = WeatherService()
    return [factory(None, weather_service) for factory in _DEDICATED_WAY_VALUE_SERVICE_FACTORIES.values()]


def test_every_service_material_id_is_a_known_material():
    """`material_id`は材料カタログの既知材料であること（axis_idを誤って
    渡すと`transform_dedicated_way_values`が軸を評価できず無音で全道路が色なしになる）。"""
    for service in _build_all():
        assert is_known_material(service.material_id)


def test_axis_id_and_material_id_are_distinct_namespaces():
    """2つの属性が同じ値でないことを確かめ、片方だけを持つ実装（両者の区別が
    ついていない写経）を検出する。"""
    for service in _build_all():
        assert service.axis_id != service.material_id
