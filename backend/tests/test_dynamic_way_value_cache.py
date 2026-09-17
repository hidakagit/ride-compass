"""dynamic_way_value_cache.py（動的＋向きあり材料の「フィーチャー→値」配信の
cache-aside層、`dict[feature_key, float]`のAPI）のテスト。実体へは触らず、get/setだけを
実装したフェイクで検証する。
"""

import pytest

from app.infrastructure import dynamic_way_value_cache, redis_json_cache
from tests.fake_redis import FakeRedis

Z, X, Y = 14, 14551, 6447
TTL = 3600


class BrokenRedis:
    """疎通不能をシミュレートするフェイク（fail-open検証用）。"""

    async def get(self, key):
        raise ConnectionError("boom")

    async def set(self, key, value, ex=None):
        raise ConnectionError("boom")


@pytest.fixture(autouse=True)
def _reset_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(redis_json_cache, "get_redis_client_or_none", lambda: fake)
    return fake


HOUR = "2026-08-30T09"


async def test_get_tile_values_miss_returns_none():
    result = await dynamic_way_value_cache.get_tile_values("wind", Z, X, Y, HOUR, 0.0)
    assert result is None


async def test_set_then_get_roundtrip_scalar_broadcast():
    # 風は「同じタイル内の全フィーチャーが同じ値」を、複数の鍵へ
    # 同値をbroadcastしたdictとして表現する。
    await dynamic_way_value_cache.set_tile_values("wind", Z, X, Y, HOUR, 0.0, {"1": 2.34, "2": 2.34}, TTL)

    result = await dynamic_way_value_cache.get_tile_values("wind", Z, X, Y, HOUR, 0.0)

    assert result == {"1": 2.34, "2": 2.34}


async def test_set_then_get_roundtrip_per_way_values():
    # 勾配はway単位で異なる値を持ちうる（道路自身の勾配%・向きがway固有のため）。
    await dynamic_way_value_cache.set_tile_values("gradient", Z, X, Y, None, 0.0, {"1": 5.5, "2": -3.2}, TTL)

    result = await dynamic_way_value_cache.get_tile_values("gradient", Z, X, Y, None, 0.0)

    assert result == {"1": 5.5, "2": -3.2}


async def test_different_material_id_is_a_different_entry():
    # 同じタイル・同じ時刻/向きバケットでも、材料が違えば別キー
    # （風と勾配が互いのキャッシュへ干渉しない）。
    await dynamic_way_value_cache.set_tile_values("wind", Z, X, Y, HOUR, 0.0, {"1": 1.0}, TTL)

    result = await dynamic_way_value_cache.get_tile_values("gradient", Z, X, Y, HOUR, 0.0)

    assert result is None


async def test_different_tile_is_a_different_entry():
    await dynamic_way_value_cache.set_tile_values("wind", Z, X, Y, HOUR, 0.0, {"1": 1.0}, TTL)

    result = await dynamic_way_value_cache.get_tile_values("wind", Z, X, Y + 1, HOUR, 0.0)

    assert result is None


async def test_different_road_surface_tile_version_is_a_different_entry(monkeypatch):
    """路面タイルを焼き直した版のエントリは、前の版のものを拾わない。

    ここに入る鍵は路面タイルの`feature_key`と一致して初めて意味を持つ。世代が鍵に
    入っていないと、焼き方を変えたデプロイの直後、**どの地物にも一致しないエントリが
    TTLの間そのまま返り続け、色だけが静かに消える**（エラーにならない）。
    """
    await dynamic_way_value_cache.set_tile_values("wind", Z, X, Y, HOUR, 0.0, {"1": 1.0}, TTL)

    monkeypatch.setattr(dynamic_way_value_cache, "ROAD_SURFACE_TILE_VERSION", "99-deadbeefcafe")
    result = await dynamic_way_value_cache.get_tile_values("wind", Z, X, Y, HOUR, 0.0)

    assert result is None


async def test_different_hour_bucket_is_a_different_entry():
    await dynamic_way_value_cache.set_tile_values("wind", Z, X, Y, "2026-08-30T09", 0.0, {"1": 1.0}, TTL)

    result = await dynamic_way_value_cache.get_tile_values("wind", Z, X, Y, "2026-08-30T10", 0.0)

    assert result is None


async def test_none_hour_bucket_is_used_by_time_independent_materials():
    # 勾配は時刻に依存しないためhour_bucket=Noneで呼ぶ（dynamic_way_values.py参照）。
    await dynamic_way_value_cache.set_tile_values("gradient", Z, X, Y, None, 0.0, {"1": 1.0}, TTL)

    result = await dynamic_way_value_cache.get_tile_values("gradient", Z, X, Y, None, 0.0)

    assert result == {"1": 1.0}


async def test_different_bearing_bucket_is_a_different_entry():
    await dynamic_way_value_cache.set_tile_values("wind", Z, X, Y, HOUR, 0.0, {"1": 1.0}, TTL)

    result = await dynamic_way_value_cache.get_tile_values("wind", Z, X, Y, HOUR, 90.0)

    assert result is None


async def test_bearing_within_same_bucket_hits_cache():
    await dynamic_way_value_cache.set_tile_values("wind", Z, X, Y, HOUR, 10.0, {"1": 1.0}, TTL)

    result = await dynamic_way_value_cache.get_tile_values("wind", Z, X, Y, HOUR, 11.0)

    assert result == {"1": 1.0}


def test_bearing_bucket_normalizes_360_to_0():
    assert dynamic_way_value_cache.bearing_bucket(360.0) == dynamic_way_value_cache.bearing_bucket(0.0)


def test_bearing_bucket_wraps_negative_values():
    assert dynamic_way_value_cache.bearing_bucket(-5.0) == dynamic_way_value_cache.bearing_bucket(355.0)


async def test_set_tile_values_overwrites_existing_entry():
    await dynamic_way_value_cache.set_tile_values("wind", Z, X, Y, HOUR, 0.0, {"1": 1.0}, TTL)
    await dynamic_way_value_cache.set_tile_values("wind", Z, X, Y, HOUR, 0.0, {"1": -2.5}, TTL)

    result = await dynamic_way_value_cache.get_tile_values("wind", Z, X, Y, HOUR, 0.0)

    assert result == {"1": -2.5}


async def test_get_tile_values_fails_open_on_redis_error(monkeypatch):
    monkeypatch.setattr(redis_json_cache, "get_redis_client_or_none", lambda: BrokenRedis())
    result = await dynamic_way_value_cache.get_tile_values("wind", Z, X, Y, HOUR, 0.0)
    assert result is None


async def test_set_tile_values_swallows_redis_error(monkeypatch):
    monkeypatch.setattr(redis_json_cache, "get_redis_client_or_none", lambda: BrokenRedis())
    # 例外を送出せず静かに失敗することだけを確認する。
    await dynamic_way_value_cache.set_tile_values("wind", Z, X, Y, HOUR, 0.0, {"1": 1.0}, TTL)


async def test_get_tile_values_ignores_corrupt_entry(_reset_redis):
    _reset_redis.store[f"dynway:wind:{Z}:{X}:{Y}:{HOUR}:0"] = "not-json"

    result = await dynamic_way_value_cache.get_tile_values("wind", Z, X, Y, HOUR, 0.0)

    assert result is None
