"""jma_amedas_service.py（改善計画T387）のテスト。

JMAへの実HTTP・実Redisは使わず、infrastructure.jma_amedas_clientの各関数とRedisクライアントを
monkeypatchで差し替える（docs/testing.md: 実I/Oを伴わない単体テストの原則）。

設計（2026-08-29、ユーザー指摘を受け改訂）: JMAの観測値エンドポイントは1地点だけを
絞り込めず全国分を1レスポンスで返すため、取得は`refresh_all_stations`（main.pyの
定期バッチが呼ぶ）が一括で担い、`get_nearest_observation`（リクエスト経路）はRedis
読み取り専用にした。
"""

from app.domain.jma_amedas import apparent_temperature_from_amedas
from app.domain.route import Coordinates
from app.infrastructure import jma_amedas_client
from app.services import jma_amedas_service
from app.services.jma_amedas_service import JmaAmedasService

POINT = Coordinates(latitude=35.68, longitude=139.76)

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

    async def hgetall(self, key):
        return self.hashes.get(key, {})

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


async def _async_return(value):
    return value


def _patch_client(monkeypatch, redis=None):
    monkeypatch.setattr(jma_amedas_client, "fetch_station_table", lambda http_client: _async_return(STATIONS))
    monkeypatch.setattr(
        jma_amedas_client, "fetch_latest_observation_time", lambda http_client: _async_return("2026-08-29T12:00:00+09:00")
    )
    monkeypatch.setattr(
        jma_amedas_client, "fetch_observation_map", lambda http_client, timestamp: _async_return(OBSERVATION_MAP)
    )
    fake_redis = redis if redis is not None else FakeRedis()
    monkeypatch.setattr(jma_amedas_service, "get_redis_client", lambda: fake_redis)
    return fake_redis


async def test_refresh_all_stations_caches_every_station_in_one_batch(monkeypatch):
    fake_redis = _patch_client(monkeypatch)
    service = JmaAmedasService(http_client=None)

    count = await service.refresh_all_stations()

    assert count == 2
    assert set(fake_redis.hashes.keys()) == {"jma:amedas:44132", "jma:amedas:99999"}
    assert fake_redis.hashes["jma:amedas:44132"]["station_name"] == "東京"
    expected_apparent = apparent_temperature_from_amedas(26.5, 70, 3.5)
    assert float(fake_redis.hashes["jma:amedas:44132"]["apparent_temperature_c"]) == expected_apparent
    # 湿度センサー無しの観測所（99999）は体感温度を計算できずNone（空文字）のまま。
    assert fake_redis.hashes["jma:amedas:99999"]["apparent_temperature_c"] == ""


async def test_refresh_all_stations_warns_when_station_table_fetch_fails(monkeypatch, caplog):
    # 改善計画T425（ゼロベース網羅レビュー指摘）: 全滅バッチ（count=0）が以前は無警告
    # だった。main.py: _refresh_amedas_jobは例外の有無しか見ていないため、サービス層
    # 自身がWARNINGを出す必要がある。
    _patch_client(monkeypatch)
    monkeypatch.setattr(jma_amedas_client, "fetch_station_table", lambda http_client: _async_return({}))
    service = JmaAmedasService(http_client=None)

    with caplog.at_level("WARNING", logger="app.services.jma_amedas_service"):
        count = await service.refresh_all_stations()

    assert count == 0
    assert any("観測所マスタ" in record.message for record in caplog.records)


async def test_refresh_all_stations_warns_when_latest_observation_time_fetch_fails(monkeypatch, caplog):
    _patch_client(monkeypatch)
    monkeypatch.setattr(jma_amedas_client, "fetch_latest_observation_time", lambda http_client: _async_return(None))
    service = JmaAmedasService(http_client=None)

    with caplog.at_level("WARNING", logger="app.services.jma_amedas_service"):
        count = await service.refresh_all_stations()

    assert count == 0
    assert any("最新観測時刻" in record.message for record in caplog.records)


async def test_refresh_all_stations_warns_when_observation_map_fetch_fails(monkeypatch, caplog):
    _patch_client(monkeypatch)
    monkeypatch.setattr(
        jma_amedas_client, "fetch_observation_map", lambda http_client, timestamp: _async_return(None)
    )
    service = JmaAmedasService(http_client=None)

    with caplog.at_level("WARNING", logger="app.services.jma_amedas_service"):
        count = await service.refresh_all_stations()

    assert count == 0
    assert any("観測値マップ" in record.message for record in caplog.records)


async def test_get_nearest_observation_reads_from_redis_without_fetching(monkeypatch):
    fake_redis = _patch_client(monkeypatch)
    service = JmaAmedasService(http_client=None)
    # バッチ（定期実行想定）が先に全国分をキャッシュ済みという前提を再現する。
    await service.refresh_all_stations()

    def _fail(*args, **kwargs):
        raise AssertionError("get_nearest_observationはRedis読み取りのみで、JMAへ再取得してはいけない")

    monkeypatch.setattr(jma_amedas_client, "fetch_latest_observation_time", _fail)
    monkeypatch.setattr(jma_amedas_client, "fetch_observation_map", _fail)

    result = await service.get_nearest_observation(POINT)

    assert result is not None
    assert result.station_id == "44132"
    assert result.station_name == "東京"
    assert result.temperature_c == 26.5
    assert result.apparent_temperature_c == apparent_temperature_from_amedas(26.5, 70, 3.5)
    assert result.wind_speed_ms == 3.5
    assert result.wind_direction_label == "南"
    assert result.precipitation_10min_mm == 0.0
    assert result.sunshine_10min_minutes == 5.0
    # sunrise/sunsetはRedisキャッシュではなくget_nearest_observationがクエリ地点に対して
    # その場でastral計算する（jma_amedas_service.pyのdocstring参照）。
    assert result.sunrise is not None
    assert result.sunset is not None


async def test_get_nearest_observation_returns_none_when_not_yet_cached(monkeypatch):
    _patch_client(monkeypatch)
    service = JmaAmedasService(http_client=None)

    # refresh_all_stationsを呼んでいない（＝定期バッチがまだ一度も成功していない）状態。
    result = await service.get_nearest_observation(POINT)

    assert result is None
