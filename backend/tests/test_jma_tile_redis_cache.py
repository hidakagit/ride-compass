"""`infrastructure/jma_tile_redis_cache.py`——JMA動的タイル本体のRedis cache-aside。

ここで見ないもの:
- 空かどうかの判定そのもの → `test_jma_tile_content.py`
- 時刻一覧とタイルの振り分け・上流フェッチ → `test_jma_tile_client.py`
- サーキットブレーカーの開閉そのもの → `test_redis_client.py`

Redisへは`tests/fake_redis.py`のフェイクを通す（実Redisは使わない）。
"""

import io

import pytest
import redis
from PIL import Image

from app.infrastructure import jma_tile_redis_cache, redis_client
from app.infrastructure.jma_tile_redis_cache import EMPTY_TILE
from tests.fake_redis import FakeRedis

PNG_PATH = "bosai/jmatile/data/nowc/20260101000000/none/20260101000500/surf/hrpns/6/57/25.png"
PBF_PATH = "bosai/jmatile/data/kkcr/20260101000000/none/20260101000000/surf/flood/6/57/25.pbf"
TILE_BYTES = b"\x89PNG\r\n\x1a\n\xff\xfe\x00binary"


@pytest.fixture
def fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(jma_tile_redis_cache, "get_redis_client_or_none", lambda: fake)
    return fake


def _transparent_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


async def test_stored_tile_comes_back_with_its_content_type(fake_redis):
    """バイト列をそのまま置けないRedisへ回すため、非テキストのバイト列で往復を見る。"""
    await jma_tile_redis_cache.set(PNG_PATH, TILE_BYTES, "image/png")
    assert await jma_tile_redis_cache.get(PNG_PATH) == (TILE_BYTES, "image/png")


async def test_uncached_path_is_a_miss(fake_redis):
    assert await jma_tile_redis_cache.get(PNG_PATH) is None


async def test_each_path_keeps_its_own_entry(fake_redis):
    await jma_tile_redis_cache.set(PNG_PATH, TILE_BYTES, "image/png")
    assert await jma_tile_redis_cache.get(PBF_PATH) is None


async def test_tile_with_nothing_to_draw_is_kept_as_a_flag(fake_redis):
    await jma_tile_redis_cache.set(PNG_PATH, _transparent_png(), "image/png")
    assert await jma_tile_redis_cache.get(PNG_PATH) is EMPTY_TILE


async def test_vector_tile_is_judged_as_a_vector_by_its_path(fake_redis):
    """空判定へ渡す拡張子はパスから取る——画像として読もうとすると0バイトのMVTを
    「中身あり」と見て、描くものが無い事実を持てなくなる。"""
    await jma_tile_redis_cache.set(PBF_PATH, b"", "application/vnd.mapbox-vector-tile")
    assert await jma_tile_redis_cache.get(PBF_PATH) is EMPTY_TILE


async def test_set_empty_records_that_there_is_nothing_to_draw(fake_redis):
    await jma_tile_redis_cache.set_empty(PNG_PATH)
    assert await jma_tile_redis_cache.get(PNG_PATH) is EMPTY_TILE


async def test_entry_that_cannot_be_decoded_is_treated_as_uncached(fake_redis):
    await jma_tile_redis_cache.set(PNG_PATH, TILE_BYTES, "image/png")
    (key,) = fake_redis.store
    for broken in ("not json", '{"content_type": "image/png"}', '{"body_b64": 1, "content_type": "image/png"}'):
        fake_redis.store[key] = broken
        assert await jma_tile_redis_cache.get(PNG_PATH) is None


async def test_read_failure_falls_back_to_uncached(monkeypatch):
    monkeypatch.setattr(
        jma_tile_redis_cache, "get_redis_client_or_none", lambda: FakeRedis(raise_on_get=redis.RedisError("down"))
    )
    assert await jma_tile_redis_cache.get(PNG_PATH) is None
    assert redis_client.redis_available() is False


async def test_write_failure_is_not_raised_to_the_caller(monkeypatch):
    monkeypatch.setattr(
        jma_tile_redis_cache, "get_redis_client_or_none", lambda: FakeRedis(raise_on_set=redis.RedisError("down"))
    )
    await jma_tile_redis_cache.set(PNG_PATH, TILE_BYTES, "image/png")
    assert redis_client.redis_available() is False


async def test_failure_stops_further_calls_until_the_cooldown_passes(fake_redis):
    """障害の直後はRedisへ行かない——不通のRedisを1リクエストごとに待つと、
    タイル配信そのものが上流の遅さへ引きずられる。"""
    await jma_tile_redis_cache.set(PNG_PATH, TILE_BYTES, "image/png")
    redis_client.record_redis_failure()
    await jma_tile_redis_cache.set(PBF_PATH, TILE_BYTES, "application/vnd.mapbox-vector-tile")
    assert len(fake_redis.store) == 1
    assert await jma_tile_redis_cache.get(PNG_PATH) is None


async def test_missing_client_is_treated_as_no_cache(monkeypatch):
    monkeypatch.setattr(jma_tile_redis_cache, "get_redis_client_or_none", lambda: None)
    await jma_tile_redis_cache.set(PNG_PATH, TILE_BYTES, "image/png")
    assert await jma_tile_redis_cache.get(PNG_PATH) is None
