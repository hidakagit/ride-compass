"""雨の材料の元になる1時間雨量の履歴を、アメダスの定期バッチの入口から作るための道具。

差し替えるのは気象庁への取得とRedisだけで、履歴の組み立て・材料の計算は本物を通す。
Redisは呼び出す側のテストが`fake_redis`（`tests/conftest.py`）で空から始める。
"""

from datetime import datetime, timedelta

import respx
from cachetools import TTLCache

from app.domain.time_zone import JST
from app.infrastructure import jma_amedas_client
from app.services import jma_amedas_service
from app.services.jma_amedas_service import JmaAmedasService
from tests.fake_http import client_for


def forget_rain_materials(monkeypatch) -> None:
    """観測所ごとの材料の値のプロセス内の保持を空から始める（前のテストが作った値が残るため）。"""
    monkeypatch.setattr(jma_amedas_service, "_rain_materials_cache", TTLCache(maxsize=1, ttl=300))


async def observe(monkeypatch, stations: dict, rain_mm: dict[str, float | None]) -> None:
    """アメダスの定期バッチを1回通す。`stations`は気象庁の観測所の表の形（`lat`・`lon`は[度, 分]）。
    どの正時も、観測所ごとに`rain_mm`の1時間雨量を返す（`rain_mm`に無い観測所は雨量計を持たない）。"""
    latest_time = datetime.now(JST).replace(minute=0, second=0, microsecond=0) - timedelta(minutes=10)
    observation = {station_id: {"temp": [20.0, 0]} for station_id in stations}
    for station_id, rain in rain_mm.items():
        observation[station_id]["precipitation1h"] = [rain, 0]

    upstream = respx.Router()
    upstream.get(jma_amedas_client.AMEDAS_STATION_TABLE_URL).respond(json=stations)
    upstream.get(jma_amedas_client.AMEDAS_LATEST_TIME_URL).respond(text=latest_time.isoformat())
    upstream.route().respond(json=observation)

    monkeypatch.setattr(jma_amedas_client, "_station_table_cache", TTLCache(maxsize=1, ttl=60))
    monkeypatch.setattr(jma_amedas_client, "_latest_time_cache", TTLCache(maxsize=1, ttl=60))
    await JmaAmedasService(http_client=client_for(upstream)).refresh_all_stations()
