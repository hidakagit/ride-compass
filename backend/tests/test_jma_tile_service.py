"""jma_tile_service.py（改善計画T387）のテスト。"""

from app.infrastructure import jma_tile_client
from app.services import jma_tile_service

TARGET_TIMES = [
    {"basetime": "20260829124500", "validtime": "20260829130000", "elements": ["hrpns_nd"]},
    {"basetime": "20260829124500", "validtime": "20260829124500", "elements": ["hrpns", "hrpns_nd"]},
]


class FakeRedis:
    def __init__(self):
        self.hashes: dict[str, dict[str, str]] = {}
        self.keys: dict[str, str] = {}

    async def hgetall(self, key):
        return self.hashes.get(key, {})

    async def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update({k: str(v) for k, v in mapping.items()})

    async def expire(self, key, ttl):
        pass

    async def set(self, key, value, ex=None):
        self.keys[key] = value

    async def exists(self, key):
        return 1 if key in self.keys else 0


class BrokenRedis:
    async def hgetall(self, key):
        raise ConnectionError("boom")

    async def exists(self, key):
        raise ConnectionError("boom")

    async def set(self, key, value, ex=None):
        raise ConnectionError("boom")


async def test_get_latest_nowcast_timestamp_picks_hrpns_entry(monkeypatch):
    monkeypatch.setattr(jma_tile_client, "fetch_target_times", lambda http_client: _async_return(TARGET_TIMES))
    monkeypatch.setattr(jma_tile_service, "get_redis_client", lambda: FakeRedis())

    result = await jma_tile_service.get_latest_nowcast_timestamp(http_client=None)

    assert result is not None
    assert result.basetime == "20260829124500"
    assert result.validtime == "20260829124500"
    assert "20260829124500" in result.tile_url_template
    assert "{z}/{x}/{y}.png" in result.tile_url_template


async def test_tile_fetched_flag_roundtrip(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(jma_tile_service, "get_redis_client", lambda: fake)

    assert await jma_tile_service.is_tile_fetched(5, 10, 20) is False
    await jma_tile_service.mark_tile_fetched(5, 10, 20)
    assert await jma_tile_service.is_tile_fetched(5, 10, 20) is True


async def test_is_tile_fetched_fails_open_to_false_on_redis_error(monkeypatch):
    monkeypatch.setattr(jma_tile_service, "get_redis_client", lambda: BrokenRedis())
    assert await jma_tile_service.is_tile_fetched(5, 10, 20) is False


async def _async_return(value):
    return value
