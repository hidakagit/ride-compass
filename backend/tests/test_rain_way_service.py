"""鍵→雨の材料の配信層（`services/rain_way_service.py`）。ルートを出す前の地図の雨。

各道は中ほどに最も近い雨量計の値を引く。差し替えるのはDB（リポジトリ）・気象庁への取得・Redisだけで、
履歴の組み立てと材料の計算は本物を通す（履歴はアメダスの定期バッチの入口から作る。`tests/rain_history_fake.py`）。
"""

import inspect

import pytest

from app.domain.rain import HOURS_SINCE_RAIN, RAIN_HISTORY_HOURS, rain_window_material_id
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services.rain_way_service import RainWayService
from tests import rain_history_fake

Z, X, Y = 14, 14551, 6447

STATIONS = {
    "44132": {"lat": [35, 41.4], "lon": [139, 45.6], "kjName": "東京"},
    "46106": {"lat": [35, 26.3], "lon": [139, 39.1], "kjName": "横浜"},
    # 雨量計を持たない観測所。東京駅のすぐそばに置いても、最寄りの候補にならない。
    "99999": {"lat": [35, 40.8], "lon": [139, 46.0], "kjName": "雨量計なし"},
}


class FakeMidpointsRepository:
    """RoadGraphRepositoryのうちget_feature_midpoints_in_tileだけを実装したフェイク。引数は本物の定義へ当てて照合する。"""

    def __init__(self, midpoints):
        self._midpoints = midpoints

    async def get_feature_midpoints_in_tile(self, *args, **kwargs):
        inspect.signature(RoadGraphRepository.get_feature_midpoints_in_tile).bind(self, *args, **kwargs)
        return self._midpoints


@pytest.fixture
def empty_rain_history(monkeypatch, fake_redis):
    rain_history_fake.forget_rain_materials(monkeypatch)


async def _observe(monkeypatch, rain_mm: dict[str, float | None]):
    await rain_history_fake.observe(monkeypatch, STATIONS, rain_mm)


async def test_each_road_takes_the_value_of_its_nearest_rain_gauge(monkeypatch, empty_rain_history):
    await _observe(monkeypatch, {"44132": 2.0, "46106": 0.5})
    repository = FakeMidpointsRepository({"tokyo": (35.68, 139.77), "yokohama": (35.45, 139.64)})

    values = await RainWayService(repository, rain_window_material_id(3)).get_way_values(Z, X, Y, None, None)

    assert values == {"tokyo": 6.0, "yokohama": 1.5}


async def test_a_gauge_with_a_missing_reading_leaves_its_roads_without_a_value(monkeypatch, empty_rain_history):
    """近くの雨量計が欠測なら、遠くの雨量計で埋めずに「データなし」にする。"""
    await _observe(monkeypatch, {"44132": None, "46106": 0.0})
    repository = FakeMidpointsRepository({"tokyo": (35.68, 139.77), "yokohama": (35.45, 139.64)})

    values = await RainWayService(repository, HOURS_SINCE_RAIN).get_way_values(Z, X, Y, None, None)

    assert values == {"yokohama": float(RAIN_HISTORY_HOURS)}


async def test_no_history_yet_gives_no_values(empty_rain_history):
    repository = FakeMidpointsRepository({"tokyo": (35.68, 139.77)})

    assert await RainWayService(repository, rain_window_material_id(1)).get_way_values(Z, X, Y, None, None) == {}


async def test_outside_the_imported_area_gives_no_values(monkeypatch, empty_rain_history):
    await _observe(monkeypatch, {"44132": 2.0})

    assert await RainWayService(FakeMidpointsRepository(None), rain_window_material_id(1)).get_way_values(
        Z, X, Y, None, None
    ) == {}
