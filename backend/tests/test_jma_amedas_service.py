"""jma_amedas_service.pyのテスト。

差し替えるのはプロセス境界だけ——気象庁への取得は応答の形のままURLごとに返す上流の代役
（`RoutingHttpClient`）、Redisはメモリのフェイク。応答の形を解くクライアントは本物を通す。

JMAの観測値エンドポイントは1地点だけを絞り込めず全国分を1レスポンスで返すため、取得は
`refresh_all_stations`（main.pyの定期バッチが呼ぶ）が一括で担い、`get_nearest_observation`
（リクエスト経路）はRedis読み取り専用である。
"""

from datetime import datetime, timedelta

import numpy as np
import pytest
from cachetools import TTLCache

from app.domain.jma_amedas import apparent_temperature_from_amedas
from app.domain.rain import HOURS_SINCE_RAIN, RAIN_HISTORY_HOURS, rain_window_material_id
from app.domain.route import Coordinates
from app.domain.time_zone import JST
from app.infrastructure import jma_amedas_client, redis_json_cache
from app.services import jma_amedas_service
from app.services.jma_amedas_service import RAIN_HISTORY_MAX_AGE, JmaAmedasService, load_station_rain_materials
from tests.fake_api_http import FakeResponse, RoutingHttpClient

POINT = Coordinates(latitude=35.68, longitude=139.76)
LATEST_TIME = "2026-08-29T12:00:00+09:00"

STATIONS = {
    "44132": {"lat": [35, 41.4], "lon": [139, 45.6], "kjName": "東京"},
    "99999": {"lat": [0, 0], "lon": [0, 0], "kjName": "遠い場所"},
}

OBSERVATION_MAP = {
    "44132": {
        "temp": [26.5, 0],
        "humidity": [70, 0],
        "wind": [3.5, 0],
        "windDirection": [8, 0],
        "precipitation10m": [0.0, 0],
        "sun10m": [5.0, 0],
    },
    "99999": {
        "temp": [10.0, 0],
        "wind": [1.0, 0],
        "windDirection": [1, 0],
        "precipitation10m": [0.0, 0],
        # 湿度センサー無し（雨量計のみ等）の観測所を再現——体感温度はNoneのままになるはず。
    },
}


class FakeRedis:
    def __init__(self):
        self.hashes: dict[str, dict[str, str]] = {}
        self.strings: dict[str, str] = {}

    async def hgetall(self, key):
        return self.hashes.get(key, {})

    async def get(self, key):
        return self.strings.get(key)

    async def set(self, key, value, ex=None):
        self.strings[key] = value

    def pipeline(self, transaction=False):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis: FakeRedis):
        self._redis = redis
        self._ops = []

    def hset(self, key, mapping):
        self._ops.append(("hset", key, mapping))
        return self

    def expire(self, key, ttl):
        self._ops.append(("expire", key, ttl))
        return self

    async def execute(self):
        for op in self._ops:
            if op[0] == "hset":
                _, key, mapping = op
                self._redis.hashes.setdefault(key, {}).update({k: str(v) for k, v in mapping.items()})


def _upstream(*, stations=STATIONS, latest_time=LATEST_TIME, observation_map=lambda timestamp: OBSERVATION_MAP):
    """気象庁アメダスの代役。観測値は要求された時刻（URLの`YYYYMMDDHHMMSS`）ごとに`observation_map`が返す。
    どれもNoneなら、その取得は接続の失敗になる。"""
    prefix, suffix = jma_amedas_client.AMEDAS_OBSERVATION_URL_TEMPLATE.split("{timestamp}")

    def route(url):
        if url == jma_amedas_client.AMEDAS_STATION_TABLE_URL:
            payload = stations
        elif url == jma_amedas_client.AMEDAS_LATEST_TIME_URL:
            return None if latest_time is None else FakeResponse(text=latest_time)
        else:
            payload = observation_map(url.removeprefix(prefix).removesuffix(suffix))
        return None if payload is None else FakeResponse(payload)

    return RoutingHttpClient(route)


def _patch_redis(monkeypatch, redis=None):
    """Redisをフェイクへ、クライアントのプロセス内キャッシュを空にする（観測所マスタ・最新時刻は
    テストをまたいで残るため）。"""
    monkeypatch.setattr(jma_amedas_client, "_station_table_cache", TTLCache(maxsize=1, ttl=60))
    monkeypatch.setattr(jma_amedas_client, "_latest_time_cache", TTLCache(maxsize=1, ttl=60))
    fake_redis = redis if redis is not None else FakeRedis()
    monkeypatch.setattr(jma_amedas_service, "get_redis_client_or_none", lambda: fake_redis)
    monkeypatch.setattr(redis_json_cache, "get_redis_client_or_none", lambda: fake_redis)
    return fake_redis


async def test_refresh_all_stations_caches_every_station_in_one_batch(monkeypatch):
    fake_redis = _patch_redis(monkeypatch)
    service = JmaAmedasService(http_client=_upstream())

    count = await service.refresh_all_stations()

    assert count == 2
    assert set(fake_redis.hashes.keys()) == {"jma:amedas:44132", "jma:amedas:99999"}
    assert fake_redis.hashes["jma:amedas:44132"]["station_name"] == "東京"
    expected_apparent = apparent_temperature_from_amedas(26.5, 70, 3.5)
    assert float(fake_redis.hashes["jma:amedas:44132"]["apparent_temperature_c"]) == expected_apparent
    # 湿度センサー無しの観測所（99999）は体感温度を計算できずNone（空文字）のまま。
    assert fake_redis.hashes["jma:amedas:99999"]["apparent_temperature_c"] == ""


async def test_refresh_all_stations_warns_when_station_table_fetch_fails(monkeypatch, caplog):
    # 呼び出し元は例外の有無しか見ないため、1件も書けていないことはサービス層自身が
    # WARNINGで残すしかない。
    _patch_redis(monkeypatch)
    service = JmaAmedasService(http_client=_upstream(stations=None))

    with caplog.at_level("WARNING", logger="ridecompass.jma_amedas_service"):
        count = await service.refresh_all_stations()

    assert count == 0
    assert any("観測所マスタ" in record.message for record in caplog.records)


async def test_refresh_all_stations_warns_when_latest_observation_time_fetch_fails(monkeypatch, caplog):
    _patch_redis(monkeypatch)
    service = JmaAmedasService(http_client=_upstream(latest_time=None))

    with caplog.at_level("WARNING", logger="ridecompass.jma_amedas_service"):
        count = await service.refresh_all_stations()

    assert count == 0
    assert any("最新観測時刻" in record.message for record in caplog.records)


async def test_refresh_all_stations_warns_when_observation_map_fetch_fails(monkeypatch, caplog):
    _patch_redis(monkeypatch)
    service = JmaAmedasService(http_client=_upstream(observation_map=lambda timestamp: None))

    with caplog.at_level("WARNING", logger="ridecompass.jma_amedas_service"):
        count = await service.refresh_all_stations()

    assert count == 0
    assert any("観測値マップ" in record.message for record in caplog.records)


async def test_get_nearest_observation_reads_from_redis_without_fetching(monkeypatch):
    _patch_redis(monkeypatch)
    upstream = _upstream()
    service = JmaAmedasService(http_client=upstream)
    # バッチ（定期実行想定）が先に全国分をキャッシュ済みという前提を再現する。
    await service.refresh_all_stations()
    upstream.requested_urls.clear()

    result = await service.get_nearest_observation(POINT)

    # 観測所マスタはクライアントのキャッシュから引き、観測値は気象庁へ取りに行かない。
    assert upstream.requested_urls == []
    assert result is not None
    assert result.station_id == "44132"
    assert result.station_name == "東京"
    assert result.temperature_c == 26.5
    assert result.apparent_temperature_c == apparent_temperature_from_amedas(26.5, 70, 3.5)
    assert result.wind_speed_ms == 3.5
    assert result.wind_direction is not None and result.wind_direction.label == "南"
    assert result.precipitation_10min_mm == 0.0
    assert result.sunshine_10min_minutes == 5.0
    # 日の出・日没はRedisには無く、クエリ地点に対してその場で計算される。
    assert result.twilight is not None


async def test_get_nearest_observation_returns_none_when_not_yet_cached(monkeypatch):
    _patch_redis(monkeypatch)
    service = JmaAmedasService(http_client=_upstream())

    # refresh_all_stationsを呼んでいない（＝定期バッチがまだ一度も成功していない）状態。
    result = await service.get_nearest_observation(POINT)

    assert result is None


async def test_get_nearest_observation_fails_open_when_redis_client_unavailable(monkeypatch):
    # 設定ミス等でクライアント生成自体が失敗する場合、`get_redis_client_or_none`はNoneを
    # 返す。例外を外へ漏らさず「観測値なし」へ倒すこと。
    _patch_redis(monkeypatch)
    monkeypatch.setattr(jma_amedas_service, "get_redis_client_or_none", lambda: None)
    service = JmaAmedasService(http_client=_upstream())

    result = await service.get_nearest_observation(POINT)

    assert result is None


async def test_refresh_all_stations_fails_open_when_redis_client_unavailable(monkeypatch, caplog):
    # 書き込み側も同じfail-open契約を守る。書き込みだけをスキップし、バッチは完了する。
    _patch_redis(monkeypatch)
    monkeypatch.setattr(jma_amedas_service, "get_redis_client_or_none", lambda: None)
    service = JmaAmedasService(http_client=_upstream())

    count = await service.refresh_all_stations()

    # 観測値マップ自体の取得（JMA API側）は成功しているためcountは通常どおり返る。
    # Redisへの書き込みだけがスキップされる。
    assert count == 2


# --- 毎正時の1時間雨量の履歴（雨の材料の元） ---


@pytest.fixture(autouse=True)
def _fresh_rain_materials_cache(monkeypatch):
    monkeypatch.setattr(jma_amedas_service, "_rain_materials_cache", TTLCache(maxsize=1, ttl=300))


def _latest_hour(now: datetime) -> datetime:
    """直近の完全な正時の1つ前。観測時刻は正時の50分に置き、正時の地図JSONを別に取りに行かせる。"""
    return now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)


class RainMaps:
    """正時ごとの地図JSON。東京（44132）だけが雨量計を持ち、`rain_by_back`（何時間前の正時→mm）の雨を返す。"""

    def __init__(self, latest_hour: datetime, rain_by_back: dict[int, float], failing_backs: set[int] = frozenset()):
        self.latest_hour = latest_hour
        self.rain_by_back = rain_by_back
        self.failing_backs = set(failing_backs)
        self.requested_hours: list[int] = []

    def observation_map(self, timestamp):
        at = datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(tzinfo=JST)
        if at.minute != 0:
            return OBSERVATION_MAP
        back = int((self.latest_hour - at) / timedelta(hours=1))
        self.requested_hours.append(back)
        if back in self.failing_backs:
            return None
        rain = self.rain_by_back.get(back, 0.0)
        return {**OBSERVATION_MAP, "44132": {**OBSERVATION_MAP["44132"], "precipitation1h": [rain, 0]}}


def _rain_service(monkeypatch, maps: RainMaps, redis=None) -> JmaAmedasService:
    _patch_redis(monkeypatch, redis)
    latest_time = (maps.latest_hour + timedelta(minutes=50)).isoformat()
    return JmaAmedasService(http_client=_upstream(latest_time=latest_time, observation_map=maps.observation_map))


async def test_rain_history_is_backfilled_from_past_hourly_maps(monkeypatch):
    now = datetime.now(JST)
    maps = RainMaps(_latest_hour(now), rain_by_back={2: 3.0, 3: 3.0})

    await _rain_service(monkeypatch, maps).refresh_all_stations()
    materials = await load_station_rain_materials(now)

    assert sorted(maps.requested_hours) == list(range(RAIN_HISTORY_HOURS))
    assert materials is not None
    # 雨量計を持たない観測所（99999）は最寄りの候補に入らない。
    assert len(materials.latitudes) == 1
    assert materials.values[rain_window_material_id(1)][0] == 0.0
    assert materials.values[rain_window_material_id(3)][0] == 3.0
    assert materials.values[rain_window_material_id(4)][0] == 6.0
    assert materials.values[HOURS_SINCE_RAIN][0] == 2.0


async def test_rain_history_fetches_only_hours_it_does_not_have(monkeypatch):
    now = datetime.now(JST)
    latest_hour = _latest_hour(now)
    earlier = RainMaps(latest_hour - timedelta(hours=1), rain_by_back={})
    fake_redis = FakeRedis()
    await _rain_service(monkeypatch, earlier, fake_redis).refresh_all_stations()

    later = RainMaps(latest_hour, rain_by_back={0: 1.5})
    await _rain_service(monkeypatch, later, fake_redis).refresh_all_stations()
    materials = await load_station_rain_materials(now)

    assert later.requested_hours == [0]
    assert materials is not None
    assert materials.values[rain_window_material_id(1)][0] == 1.5


async def test_an_hour_that_could_not_be_fetched_is_retried_and_leaves_its_windows_empty_meanwhile(monkeypatch):
    now = datetime.now(JST)
    latest_hour = _latest_hour(now)
    failing = RainMaps(latest_hour, rain_by_back={}, failing_backs={5})
    fake_redis = FakeRedis()
    await _rain_service(monkeypatch, failing, fake_redis).refresh_all_stations()
    materials = await load_station_rain_materials(now)

    assert materials is not None
    assert materials.values[rain_window_material_id(4)][0] == 0.0
    assert np.isnan(materials.values[rain_window_material_id(6)][0])

    retry = RainMaps(latest_hour, rain_by_back={})
    await _rain_service(monkeypatch, retry, fake_redis).refresh_all_stations()

    assert retry.requested_hours == [5]


async def test_rain_history_is_not_refetched_while_redis_is_down(monkeypatch):
    """置き場が使えないたびに全本を取り直すと、10分ごとに気象庁へ全本を問い合わせ続ける。"""
    class DownRedis(FakeRedis):
        async def get(self, key):
            raise ConnectionError("redis is down")

    maps = RainMaps(_latest_hour(datetime.now(JST)), rain_by_back={})

    await _rain_service(monkeypatch, maps, DownRedis()).refresh_all_stations()

    assert maps.requested_hours == []


async def test_rain_materials_are_not_served_from_a_stale_history(monkeypatch):
    now = datetime.now(JST)
    maps = RainMaps(_latest_hour(now), rain_by_back={})
    await _rain_service(monkeypatch, maps).refresh_all_stations()

    assert await load_station_rain_materials(now) is not None
    assert await load_station_rain_materials(maps.latest_hour + RAIN_HISTORY_MAX_AGE + timedelta(minutes=1)) is None
