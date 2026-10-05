"""`infrastructure/redis_json_cache.py`——Redisへ持つcache-asideの骨格（JSONと生のバイト列）。

入口は`get_json`・`set_json`・`get_bytes`・`set_bytes`。Redisはfakeredis、時計はfreezegunで与え、
キャッシュの当たり外れと失敗は`/api/debug/stats`の集計（`debug_log.py: get_stats`）で見る。

ここで見ないもの:
- 冷却の長さそのもの・クライアントの作り方 → `test_redis_client.py`。ここでは冷却の長さを本物の定数から読む
- 骨格を写さずにここを通しているか → `tests/structure/test_redis_skeleton.py`
- キー設計・TTL・値の意味づけ → 呼び出し元のテスト（例: `test_jma_tile_redis_cache.py`）
"""

import logging

import pytest

from app.config import settings
from app.infrastructure import redis_client, redis_json_cache
from app.infrastructure.debug_log import get_stats
from app.infrastructure.redis_client import CIRCUIT_COOLDOWN_SECONDS

pytestmark = pytest.mark.usefixtures("empty_debug_counters")

KEY = "sample:key"
CATEGORY = "sample_cache"
TTL = 60


def stats():
    return get_stats().external[CATEGORY]


def decode_tagged(raw: bytes) -> bytes | None:
    """先頭が`T`の値だけを読める値とみなす。"""
    return raw[1:] if raw.startswith(b"T") else None


async def test_a_stored_json_value_comes_back_and_counts_as_a_hit(fake_redis):
    value = {"name": "観測所", "values": [1, 2.5, None], "nested": {"ok": True}}

    await redis_json_cache.set_json(KEY, value, ttl_seconds=TTL, category=CATEGORY)

    assert await redis_json_cache.get_json(KEY, category=CATEGORY) == value
    assert stats().cache_hits == 1
    assert stats().errors == 0


@pytest.mark.parametrize(
    ("raw", "expected", "counted"),
    [("{not json", None, (0, 1)), ("0", 0, (1, 0))],
)
async def test_an_entry_that_is_not_json_is_treated_as_not_cached_but_a_falsy_value_comes_back(
    fake_redis, raw, expected, counted
):
    """壊れた値で呼び出し元を落とさず、上流へ取りに行く道へ進める。偽になる値は未保存と区別して返る。"""
    await fake_redis.set(KEY, raw)

    assert await redis_json_cache.get_json(KEY, category=CATEGORY) == expected
    assert (stats().cache_hits, stats().cache_misses, stats().errors) == (*counted, 0)


async def test_bytes_reach_the_decoder_undecoded_and_come_back_decoded(fake_redis):
    """UTF-8として読めないバイト列とNULを含む値が、文字列を経ずにそのまま解釈関数へ届く。"""
    raw = b"T\xff\x00\x89PNG\x00"

    await redis_json_cache.set_bytes(KEY, raw, ttl_seconds=TTL, category=CATEGORY)

    assert await redis_json_cache.get_bytes(KEY, decode=decode_tagged, category=CATEGORY) == raw[1:]
    assert stats().cache_hits == 1


async def test_bytes_never_stored_do_not_reach_the_decoder(fake_redis):
    def decode(value: bytes) -> bytes:
        raise AssertionError("未保存のキーで解釈関数が呼ばれた")

    assert await redis_json_cache.get_bytes(KEY, decode=decode, category=CATEGORY) is None
    assert stats().cache_misses == 1


async def test_a_failing_redis_is_not_cached_and_raises_nothing(fake_redis, redis_server, caplog):
    """Redisの障害でタイル配信・ルート生成を止めない。失敗は集計とWARNINGへ、呼び出し元が渡した付帯情報つきで出る。"""
    redis_server.connected = False

    with caplog.at_level(logging.WARNING):
        await redis_json_cache.set_json(KEY, [1], ttl_seconds=TTL, category=CATEGORY, tile="10/908/403")

    assert stats().errors == 1
    assert stats().error_types
    assert "10/908/403" in caplog.text


@pytest.mark.usefixtures("fake_redis")
async def test_after_a_failed_read_redis_is_not_called_until_the_cooldown_passes(redis_server, clock):
    """失敗のたびに接続の待ちを重ねないよう、冷却の間はRedisにある値も読まずに未キャッシュで進む。"""
    await redis_json_cache.set_json(KEY, [1], ttl_seconds=3600, category=CATEGORY)
    redis_server.connected = False
    assert await redis_json_cache.get_json(KEY, category=CATEGORY) is None
    calls_after_failure = stats().calls
    redis_server.connected = True

    clock.tick(CIRCUIT_COOLDOWN_SECONDS - 1)
    assert await redis_json_cache.get_json(KEY, category=CATEGORY) is None
    assert stats().calls == calls_after_failure

    clock.tick(1)
    assert await redis_json_cache.get_json(KEY, category=CATEGORY) == [1]
    assert stats().calls == calls_after_failure + 1


async def test_after_a_failed_write_nothing_is_written_until_the_cooldown_passes(fake_redis, redis_server, clock):
    redis_server.connected = False
    await redis_json_cache.set_json(KEY, [1], ttl_seconds=TTL, category=CATEGORY)
    redis_server.connected = True

    clock.tick(CIRCUIT_COOLDOWN_SECONDS - 1)
    await redis_json_cache.set_json(KEY, [2], ttl_seconds=TTL, category=CATEGORY)
    await redis_json_cache.set_bytes(KEY + ":bytes", b"Tx", ttl_seconds=TTL, category=CATEGORY)
    assert await fake_redis.exists(KEY, KEY + ":bytes") == 0

    clock.tick(1)
    await redis_json_cache.set_json(KEY, [3], ttl_seconds=TTL, category=CATEGORY)
    assert await redis_json_cache.get_json(KEY, category=CATEGORY) == [3]


async def test_without_a_client_nothing_is_tried_and_nothing_is_raised(monkeypatch):
    """接続先の設定の誤りでクライアントを作れなくても、未キャッシュで進む。"""
    await redis_client.close_redis_clients()
    monkeypatch.setattr(settings, "redis_url", "not-a-redis-url")

    await redis_json_cache.set_json(KEY, [1], ttl_seconds=TTL, category=CATEGORY)
    assert await redis_json_cache.get_json(KEY, category=CATEGORY) is None

    assert CATEGORY not in get_stats().external
