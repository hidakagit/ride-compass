"""雨の材料の元になる1時間雨量の履歴を、アメダスの定期バッチの入口から作るための道具。

差し替えるのは気象庁への取得とRedisだけで、履歴の組み立て・材料の計算は本物を通す。
"""

from datetime import datetime, timedelta

from cachetools import TTLCache

from app.domain.time_zone import JST
from app.infrastructure import jma_amedas_client, redis_json_cache
from app.services import jma_amedas_service
from app.services.jma_amedas_service import JmaAmedasService
from tests.fake_api_http import FakeResponse, RoutingHttpClient


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


def use_fake_redis(monkeypatch) -> FakeRedis:
    """履歴の置き場を空のRedisへ替え、観測所ごとの材料の値のプロセス内の保持も空から始める。"""
    fake = FakeRedis()
    monkeypatch.setattr(jma_amedas_service, "get_redis_client_or_none", lambda: fake)
    monkeypatch.setattr(redis_json_cache, "get_redis_client_or_none", lambda: fake)
    monkeypatch.setattr(jma_amedas_service, "_rain_materials_cache", TTLCache(maxsize=1, ttl=300))
    return fake


async def observe(monkeypatch, stations: dict, rain_mm: dict[str, float | None]) -> None:
    """アメダスの定期バッチを1回通す。`stations`は気象庁の観測所の表の形（`lat`・`lon`は[度, 分]）。
    どの正時も、観測所ごとに`rain_mm`の1時間雨量を返す（`rain_mm`に無い観測所は雨量計を持たない）。"""
    latest_time = datetime.now(JST).replace(minute=0, second=0, microsecond=0) - timedelta(minutes=10)
    observation = {station_id: {"temp": [20.0, 0]} for station_id in stations}
    for station_id, rain in rain_mm.items():
        observation[station_id]["precipitation1h"] = [rain, 0]

    def route(url):
        if url == jma_amedas_client.AMEDAS_STATION_TABLE_URL:
            return FakeResponse(stations)
        if url == jma_amedas_client.AMEDAS_LATEST_TIME_URL:
            return FakeResponse(text=latest_time.isoformat())
        return FakeResponse(observation)

    monkeypatch.setattr(jma_amedas_client, "_station_table_cache", TTLCache(maxsize=1, ttl=60))
    monkeypatch.setattr(jma_amedas_client, "_latest_time_cache", TTLCache(maxsize=1, ttl=60))
    await JmaAmedasService(http_client=RoutingHttpClient(route)).refresh_all_stations()
