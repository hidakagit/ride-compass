"""wind_way_penalty_cache.py（改善計画T405→T414で作り直し、way_id→wind_penalty配信層の
Redis cache-aside層）のテスト。test_wind_forecast_cache.pyと同じパターン（実Redisは使わず、
get/setだけを実装したFakeRedisで検証）。

T414での設計変更（モジュールdocstring参照）: キーはway_idではなく
(z, x, y, hour_bucket, bearing_bucket)。1タイルにつきスカラー値1個をキャッシュする。
"""

import pytest

from app.infrastructure import wind_way_penalty_cache

Z, X, Y = 14, 14551, 6447


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
    monkeypatch.setattr(wind_way_penalty_cache, "get_redis_client", lambda: fake)
    return fake


HOUR = "2026-08-30T09"


async def test_get_tile_penalty_miss_returns_none():
    result = await wind_way_penalty_cache.get_tile_penalty(Z, X, Y, HOUR, 0.0)
    assert result is None


async def test_set_then_get_roundtrip():
    await wind_way_penalty_cache.set_tile_penalty(Z, X, Y, HOUR, 0.0, 2.34)

    result = await wind_way_penalty_cache.get_tile_penalty(Z, X, Y, HOUR, 0.0)

    assert result == 2.34


async def test_different_tile_is_a_different_entry():
    await wind_way_penalty_cache.set_tile_penalty(Z, X, Y, HOUR, 0.0, 1.0)

    result = await wind_way_penalty_cache.get_tile_penalty(Z, X, Y + 1, HOUR, 0.0)

    assert result is None


async def test_different_hour_bucket_is_a_different_entry():
    # 同じタイルでも時刻バケットが違えば別キー（風が変わった時刻境界で古い値を返さないため）。
    await wind_way_penalty_cache.set_tile_penalty(Z, X, Y, "2026-08-30T09", 0.0, 1.0)

    result = await wind_way_penalty_cache.get_tile_penalty(Z, X, Y, "2026-08-30T10", 0.0)

    assert result is None


async def test_different_bearing_bucket_is_a_different_entry():
    # ユーザー指定の向きが大きく違えば別キー（BEARING_BUCKET_DEG=5、0度と90度は別バケット）。
    await wind_way_penalty_cache.set_tile_penalty(Z, X, Y, HOUR, 0.0, 1.0)

    result = await wind_way_penalty_cache.get_tile_penalty(Z, X, Y, HOUR, 90.0, )

    assert result is None


async def test_bearing_within_same_bucket_hits_cache():
    # 5度刻みのバケットのため、1度・2度程度の違いは同じバケットへ丸められキャッシュが効く。
    await wind_way_penalty_cache.set_tile_penalty(Z, X, Y, HOUR, 10.0, 1.0)

    result = await wind_way_penalty_cache.get_tile_penalty(Z, X, Y, HOUR, 11.0)

    assert result == 1.0


def test_bearing_bucket_normalizes_360_to_0():
    assert wind_way_penalty_cache.bearing_bucket(360.0) == wind_way_penalty_cache.bearing_bucket(0.0)


def test_bearing_bucket_wraps_negative_values():
    assert wind_way_penalty_cache.bearing_bucket(-5.0) == wind_way_penalty_cache.bearing_bucket(355.0)


async def test_set_tile_penalty_overwrites_existing_entry():
    await wind_way_penalty_cache.set_tile_penalty(Z, X, Y, HOUR, 0.0, 1.0)
    await wind_way_penalty_cache.set_tile_penalty(Z, X, Y, HOUR, 0.0, -2.5)

    result = await wind_way_penalty_cache.get_tile_penalty(Z, X, Y, HOUR, 0.0)

    assert result == -2.5


async def test_get_tile_penalty_fails_open_on_redis_error(monkeypatch):
    monkeypatch.setattr(wind_way_penalty_cache, "get_redis_client", lambda: BrokenRedis())
    result = await wind_way_penalty_cache.get_tile_penalty(Z, X, Y, HOUR, 0.0)
    assert result is None


async def test_set_tile_penalty_swallows_redis_error(monkeypatch):
    monkeypatch.setattr(wind_way_penalty_cache, "get_redis_client", lambda: BrokenRedis())
    # 例外を送出せず静かに失敗することだけを確認する。
    await wind_way_penalty_cache.set_tile_penalty(Z, X, Y, HOUR, 0.0, 1.0)


async def test_get_tile_penalty_ignores_corrupt_entry(_reset_redis):
    _reset_redis.store[f"wind:tile-penalty:{Z}:{X}:{Y}:{HOUR}:0"] = "not-a-float"

    result = await wind_way_penalty_cache.get_tile_penalty(Z, X, Y, HOUR, 0.0)

    assert result is None
