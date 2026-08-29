"""wind_way_penalty_cache.py（改善計画T405、way_id→wind_penalty配信層のRedis cache-aside層）の
テスト。test_wind_forecast_cache.pyと同じパターン（実Redisは使わず、mget/pipeline.setだけを
実装したFakeRedisで検証）。
"""

import pytest

from app.infrastructure import wind_way_penalty_cache


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def mget(self, keys):
        return [self.store.get(key) for key in keys]

    def pipeline(self, transaction=False):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis: FakeRedis):
        self._redis = redis
        self._ops = []

    def set(self, key, value, ex=None):
        self._ops.append((key, value))
        return self

    async def execute(self):
        for key, value in self._ops:
            self._redis.store[key] = value


class BrokenRedis:
    """疎通不能をシミュレートするフェイク（fail-open検証用）。"""

    async def mget(self, keys):
        raise ConnectionError("boom")

    def pipeline(self, transaction=False):
        raise ConnectionError("boom")


@pytest.fixture(autouse=True)
def _reset_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(wind_way_penalty_cache, "get_redis_client", lambda: fake)
    return fake


HOUR = "2026-08-30T09"


async def test_get_way_penalties_many_empty_ids_returns_empty_dict():
    assert await wind_way_penalty_cache.get_way_penalties_many([], HOUR) == {}


async def test_get_way_penalties_many_miss_returns_empty_dict():
    result = await wind_way_penalty_cache.get_way_penalties_many([1], HOUR)
    assert result == {}


async def test_set_then_get_roundtrip():
    await wind_way_penalty_cache.set_way_penalties_many({1: 2.34}, HOUR)

    result = await wind_way_penalty_cache.get_way_penalties_many([1], HOUR)

    assert result == {1: 2.34}


async def test_get_way_penalties_many_returns_only_found_ids():
    await wind_way_penalty_cache.set_way_penalties_many({1: 1.0}, HOUR)

    result = await wind_way_penalty_cache.get_way_penalties_many([1, 2], HOUR)

    assert list(result.keys()) == [1]


async def test_different_hour_bucket_is_a_different_entry():
    # 同じway_idでも時刻バケットが違えば別キー（風が変わった時刻境界で古い値を返さないため）。
    await wind_way_penalty_cache.set_way_penalties_many({1: 1.0}, "2026-08-30T09")

    result = await wind_way_penalty_cache.get_way_penalties_many([1], "2026-08-30T10")

    assert result == {}


async def test_set_way_penalties_many_overwrites_existing_entry():
    await wind_way_penalty_cache.set_way_penalties_many({1: 1.0}, HOUR)
    await wind_way_penalty_cache.set_way_penalties_many({1: -2.5}, HOUR)

    result = await wind_way_penalty_cache.get_way_penalties_many([1], HOUR)

    assert result == {1: -2.5}


async def test_get_way_penalties_many_fails_open_on_redis_error(monkeypatch):
    monkeypatch.setattr(wind_way_penalty_cache, "get_redis_client", lambda: BrokenRedis())
    result = await wind_way_penalty_cache.get_way_penalties_many([1], HOUR)
    assert result == {}


async def test_set_way_penalties_many_swallows_redis_error(monkeypatch):
    monkeypatch.setattr(wind_way_penalty_cache, "get_redis_client", lambda: BrokenRedis())
    # 例外を送出せず静かに失敗することだけを確認する。
    await wind_way_penalty_cache.set_way_penalties_many({1: 1.0}, HOUR)


async def test_get_way_penalties_many_ignores_corrupt_entry(_reset_redis):
    _reset_redis.store["wind:way-penalty:1:2026-08-30T09"] = "not-a-float"

    result = await wind_way_penalty_cache.get_way_penalties_many([1], HOUR)

    assert result == {}
