"""wind_forecast_cache.py（改善計画T398、気象グリッドのRedis cache-aside層）のテスト。

実Redisは使わず、使用するコマンド（mget/pipeline.set）だけを実装したFakeRedisで検証する
（docs/testing.md: 実I/Oを伴わない単体テストの原則。test_road_graph_tile_cache.pyと同じ
パターン）。
"""

import pytest

from app.infrastructure import wind_forecast_cache


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
    monkeypatch.setattr(wind_forecast_cache, "get_redis_client_or_none", lambda: fake)
    return fake


async def test_get_wind_forecast_many_empty_keys_returns_empty_dict():
    assert await wind_forecast_cache.get_wind_forecast_many([]) == {}


async def test_get_wind_forecast_many_miss_returns_empty_dict():
    result = await wind_forecast_cache.get_wind_forecast_many([(35.0, 139.0)])
    assert result == {}


async def test_set_then_get_roundtrip():
    await wind_forecast_cache.set_wind_forecast_many({(35.0, 139.0): (123.0, {"tag": "roundtrip"})})

    result = await wind_forecast_cache.get_wind_forecast_many([(35.0, 139.0)])

    assert result[(35.0, 139.0)] == (123.0, {"tag": "roundtrip"})


async def test_get_wind_forecast_many_returns_only_found_keys():
    await wind_forecast_cache.set_wind_forecast_many({(35.1, 139.1): (1.0, {"tag": "found"})})

    result = await wind_forecast_cache.get_wind_forecast_many([(35.1, 139.1), (35.2, 139.2)])

    assert list(result.keys()) == [(35.1, 139.1)]


async def test_set_wind_forecast_many_overwrites_existing_entry():
    await wind_forecast_cache.set_wind_forecast_many({(35.3, 139.3): (1.0, {"tag": "old"})})
    await wind_forecast_cache.set_wind_forecast_many({(35.3, 139.3): (2.0, {"tag": "new"})})

    result = await wind_forecast_cache.get_wind_forecast_many([(35.3, 139.3)])

    assert result[(35.3, 139.3)] == (2.0, {"tag": "new"})


async def test_get_wind_forecast_many_fails_open_on_redis_error(monkeypatch):
    monkeypatch.setattr(wind_forecast_cache, "get_redis_client_or_none", lambda: BrokenRedis())
    result = await wind_forecast_cache.get_wind_forecast_many([(1.0, 2.0)])
    assert result == {}


async def test_set_wind_forecast_many_swallows_redis_error(monkeypatch):
    monkeypatch.setattr(wind_forecast_cache, "get_redis_client_or_none", lambda: BrokenRedis())
    # 例外を送出せず静かに失敗することだけを確認する。
    await wind_forecast_cache.set_wind_forecast_many({(1.0, 2.0): (1.0, {"tag": "x"})})


async def test_get_wind_forecast_many_ignores_corrupt_entry(_reset_redis):
    # 手動編集・フォーマット変更等で壊れたエントリはJSON解析エラーになるが、例外を
    # 呼び出し元へ伝播させず「未キャッシュ」として扱う（fail-open）ことを確認する。
    _reset_redis.store["wind:forecast:35.0:139.0"] = "not-json"

    result = await wind_forecast_cache.get_wind_forecast_many([(35.0, 139.0)])

    assert result == {}
