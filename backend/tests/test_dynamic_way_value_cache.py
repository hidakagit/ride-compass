"""dynamic_way_value_cache.py（改善計画T405→T414→T423で汎用化、動的＋向きあり材料の
「way_id→値」配信のRedis cache-aside層）のテスト。旧test_wind_way_penalty_cache.py
（風専用、`get_tile_penalty`/`set_tile_penalty`というスカラー1個のAPI）をT423で
material_id駆動・`dict[way_id, float]`のAPIへ汎用化した。test_wind_forecast_cache.pyと
同じパターン（実Redisは使わず、get/setだけを実装したFakeRedisで検証）。
"""

import pytest

from app.infrastructure import dynamic_way_value_cache

Z, X, Y = 14, 14551, 6447
TTL = 3600


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value


class BrokenRedis:
    """疎通不能をシミュレートするフェイク（fail-open検証用）。"""

    async def get(self, key):
        raise ConnectionError("boom")

    async def set(self, key, value, ex=None):
        raise ConnectionError("boom")


@pytest.fixture(autouse=True)
def _reset_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(dynamic_way_value_cache, "get_redis_client", lambda: fake)
    return fake


HOUR = "2026-08-30T09"


async def test_get_tile_values_miss_returns_none():
    result = await dynamic_way_value_cache.get_tile_values("wind", Z, X, Y, HOUR, 0.0)
    assert result is None


async def test_set_then_get_roundtrip_scalar_broadcast():
    # 風は「同じタイル内の全wayが同じ値」（T414の訂正後契約）を、複数のway_idキーへ
    # 同値をbroadcastしたdictとして表現する。
    await dynamic_way_value_cache.set_tile_values("wind", Z, X, Y, HOUR, 0.0, {1: 2.34, 2: 2.34}, TTL)

    result = await dynamic_way_value_cache.get_tile_values("wind", Z, X, Y, HOUR, 0.0)

    assert result == {1: 2.34, 2: 2.34}


async def test_set_then_get_roundtrip_per_way_values():
    # 勾配はway単位で異なる値を持ちうる（道路自身の勾配%・向きがway固有のため）。
    await dynamic_way_value_cache.set_tile_values("gradient", Z, X, Y, None, 0.0, {1: 5.5, 2: -3.2}, TTL)

    result = await dynamic_way_value_cache.get_tile_values("gradient", Z, X, Y, None, 0.0)

    assert result == {1: 5.5, 2: -3.2}


async def test_different_material_id_is_a_different_entry():
    # 同じタイル・同じ時刻/向きバケットでも、材料が違えば別キー
    # （風と勾配が互いのキャッシュへ干渉しない）。
    await dynamic_way_value_cache.set_tile_values("wind", Z, X, Y, HOUR, 0.0, {1: 1.0}, TTL)

    result = await dynamic_way_value_cache.get_tile_values("gradient", Z, X, Y, HOUR, 0.0)

    assert result is None


async def test_different_tile_is_a_different_entry():
    await dynamic_way_value_cache.set_tile_values("wind", Z, X, Y, HOUR, 0.0, {1: 1.0}, TTL)

    result = await dynamic_way_value_cache.get_tile_values("wind", Z, X, Y + 1, HOUR, 0.0)

    assert result is None


async def test_different_hour_bucket_is_a_different_entry():
    await dynamic_way_value_cache.set_tile_values("wind", Z, X, Y, "2026-08-30T09", 0.0, {1: 1.0}, TTL)

    result = await dynamic_way_value_cache.get_tile_values("wind", Z, X, Y, "2026-08-30T10", 0.0)

    assert result is None


async def test_none_hour_bucket_is_used_by_time_independent_materials():
    # 勾配は時刻に依存しないためhour_bucket=Noneで呼ぶ（dynamic_way_values.py参照）。
    await dynamic_way_value_cache.set_tile_values("gradient", Z, X, Y, None, 0.0, {1: 1.0}, TTL)

    result = await dynamic_way_value_cache.get_tile_values("gradient", Z, X, Y, None, 0.0)

    assert result == {1: 1.0}


async def test_different_bearing_bucket_is_a_different_entry():
    await dynamic_way_value_cache.set_tile_values("wind", Z, X, Y, HOUR, 0.0, {1: 1.0}, TTL)

    result = await dynamic_way_value_cache.get_tile_values("wind", Z, X, Y, HOUR, 90.0)

    assert result is None


async def test_bearing_within_same_bucket_hits_cache():
    await dynamic_way_value_cache.set_tile_values("wind", Z, X, Y, HOUR, 10.0, {1: 1.0}, TTL)

    result = await dynamic_way_value_cache.get_tile_values("wind", Z, X, Y, HOUR, 11.0)

    assert result == {1: 1.0}


def test_bearing_bucket_normalizes_360_to_0():
    assert dynamic_way_value_cache.bearing_bucket(360.0) == dynamic_way_value_cache.bearing_bucket(0.0)


def test_bearing_bucket_wraps_negative_values():
    assert dynamic_way_value_cache.bearing_bucket(-5.0) == dynamic_way_value_cache.bearing_bucket(355.0)


async def test_set_tile_values_overwrites_existing_entry():
    await dynamic_way_value_cache.set_tile_values("wind", Z, X, Y, HOUR, 0.0, {1: 1.0}, TTL)
    await dynamic_way_value_cache.set_tile_values("wind", Z, X, Y, HOUR, 0.0, {1: -2.5}, TTL)

    result = await dynamic_way_value_cache.get_tile_values("wind", Z, X, Y, HOUR, 0.0)

    assert result == {1: -2.5}


async def test_get_tile_values_fails_open_on_redis_error(monkeypatch):
    monkeypatch.setattr(dynamic_way_value_cache, "get_redis_client", lambda: BrokenRedis())
    result = await dynamic_way_value_cache.get_tile_values("wind", Z, X, Y, HOUR, 0.0)
    assert result is None


async def test_set_tile_values_swallows_redis_error(monkeypatch):
    monkeypatch.setattr(dynamic_way_value_cache, "get_redis_client", lambda: BrokenRedis())
    # 例外を送出せず静かに失敗することだけを確認する。
    await dynamic_way_value_cache.set_tile_values("wind", Z, X, Y, HOUR, 0.0, {1: 1.0}, TTL)


async def test_get_tile_values_ignores_corrupt_entry(_reset_redis):
    _reset_redis.store[f"dynway:wind:{Z}:{X}:{Y}:{HOUR}:0"] = "not-json"

    result = await dynamic_way_value_cache.get_tile_values("wind", Z, X, Y, HOUR, 0.0)

    assert result is None
