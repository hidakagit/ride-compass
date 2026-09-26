"""鍵→雨の材料の配信層（`services/rain_way_service.py`）。ルートを出す前の地図の雨。

各道は中ほどに最も近い雨量計の値を引く。差し替えるのはDB（リポジトリ）・気象庁への取得・Redisだけで、
履歴の組み立てと材料の計算は本物を通す（履歴はアメダスの定期バッチの入口から作る）。
"""

import inspect
from datetime import datetime, timedelta

import pytest
from cachetools import TTLCache

from app.domain.rain import HOURS_SINCE_RAIN, RAIN_HISTORY_HOURS, rain_window_material_id
from app.domain.time_zone import JST
from app.infrastructure import jma_amedas_client, redis_json_cache
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services import jma_amedas_service
from app.services.jma_amedas_service import JmaAmedasService
from app.services.rain_way_service import RainWayService

Z, X, Y = 14, 14551, 6447

STATIONS = {
    "44132": {"lat": [35, 41.4], "lon": [139, 45.6], "kjName": "東京"},
    "46106": {"lat": [35, 26.3], "lon": [139, 39.1], "kjName": "横浜"},
    # 雨量計を持たない観測所。東京駅のすぐそばに置いても、最寄りの候補にならない。
    "99999": {"lat": [35, 40.8], "lon": [139, 46.0], "kjName": "雨量計なし"},
}


class FakeRedis:
    def __init__(self):
        self.strings: dict[str, str] = {}

    async def hgetall(self, key):
        return {}

    def pipeline(self, transaction=False):
        return FakePipeline()

    async def get(self, key):
        return self.strings.get(key)

    async def set(self, key, value, ex=None):
        self.strings[key] = value


class FakePipeline:
    def hset(self, key, mapping):
        return self

    def expire(self, key, ttl):
        return self

    async def execute(self):
        return []


class FakeMidpointsRepository:
    """RoadGraphRepositoryのうちget_feature_midpoints_in_tileだけを実装したフェイク。引数は本物の定義へ当てて照合する。"""

    def __init__(self, midpoints):
        self._midpoints = midpoints

    async def get_feature_midpoints_in_tile(self, *args, **kwargs):
        inspect.signature(RoadGraphRepository.get_feature_midpoints_in_tile).bind(self, *args, **kwargs)
        return self._midpoints


async def _async_return(value):
    return value


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(jma_amedas_service, "get_redis_client_or_none", lambda: fake)
    monkeypatch.setattr(redis_json_cache, "get_redis_client_or_none", lambda: fake)
    monkeypatch.setattr(jma_amedas_service, "_rain_materials_cache", TTLCache(maxsize=1, ttl=300))
    return fake


async def _observe(monkeypatch, rain_mm: dict[str, float]):
    """アメダスの定期バッチを1回通す。どの正時も、観測所ごとに`rain_mm`の1時間雨量を返す。"""
    latest_time = datetime.now(JST).replace(minute=0, second=0, microsecond=0) - timedelta(minutes=10)

    async def fetch_map(http_client, timestamp):
        observation = {station_id: {"temp": [20.0, 0]} for station_id in STATIONS}
        for station_id, rain in rain_mm.items():
            observation[station_id]["precipitation1h"] = [rain, 0]
        return observation

    monkeypatch.setattr(jma_amedas_client, "fetch_station_table", lambda http_client: _async_return(STATIONS))
    monkeypatch.setattr(
        jma_amedas_client, "fetch_latest_observation_time", lambda http_client: _async_return(latest_time.isoformat())
    )
    monkeypatch.setattr(jma_amedas_client, "fetch_observation_map", fetch_map)
    await JmaAmedasService(http_client=None).refresh_all_stations()


async def test_each_road_takes_the_value_of_its_nearest_rain_gauge(monkeypatch):
    await _observe(monkeypatch, {"44132": 2.0, "46106": 0.5})
    repository = FakeMidpointsRepository({"tokyo": (35.68, 139.77), "yokohama": (35.45, 139.64)})

    values = await RainWayService(repository, rain_window_material_id(3)).get_way_values(Z, X, Y, None, None)

    assert values == {"tokyo": 6.0, "yokohama": 1.5}


async def test_a_gauge_with_a_missing_reading_leaves_its_roads_without_a_value(monkeypatch):
    """近くの雨量計が欠測なら、遠くの雨量計で埋めずに「データなし」にする。"""
    await _observe(monkeypatch, {"44132": None, "46106": 0.0})
    repository = FakeMidpointsRepository({"tokyo": (35.68, 139.77), "yokohama": (35.45, 139.64)})

    values = await RainWayService(repository, HOURS_SINCE_RAIN).get_way_values(Z, X, Y, None, None)

    assert values == {"yokohama": float(RAIN_HISTORY_HOURS)}


async def test_no_history_yet_gives_no_values():
    repository = FakeMidpointsRepository({"tokyo": (35.68, 139.77)})

    assert await RainWayService(repository, rain_window_material_id(1)).get_way_values(Z, X, Y, None, None) == {}


async def test_outside_the_imported_area_gives_no_values(monkeypatch):
    await _observe(monkeypatch, {"44132": 2.0})

    assert await RainWayService(FakeMidpointsRepository(None), rain_window_material_id(1)).get_way_values(
        Z, X, Y, None, None
    ) == {}
