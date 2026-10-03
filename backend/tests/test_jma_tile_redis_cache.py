"""`infrastructure/jma_tile_redis_cache.py`——JMA動的タイル本体のRedis cache-aside。

ここで見ないもの:
- 空かどうかの判定そのもの → `test_jma_tile_content.py`
- 時刻一覧とタイルの振り分け・上流フェッチ → `test_jma_tile_client.py`
- サーキットブレーカーの開閉そのもの → `test_redis_client.py`

Redisへはfakeredis（`fake_redis`）を通す（実Redisは使わない）。
"""

import io

from PIL import Image

from app.infrastructure import jma_tile_redis_cache, redis_client, redis_json_cache
from app.infrastructure.jma_tile_redis_cache import EMPTY_TILE


PNG_PATH = "bosai/jmatile/data/nowc/20260101000000/none/20260101000500/surf/hrpns/6/57/25.png"
PBF_PATH = "bosai/jmatile/data/kkcr/20260101000000/none/20260101000000/surf/flood/6/57/25.pbf"
TILE_BYTES = b"\x89PNG\r\n\x1a\n\xff\xfe\x00binary"


def _transparent_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


async def test_stored_tile_comes_back_with_its_content_type(fake_redis):
    """文字列として読めない・区切りのNULを含むバイト列で往復を見る。"""
    await jma_tile_redis_cache.set(PNG_PATH, TILE_BYTES, "image/png")
    assert await jma_tile_redis_cache.get(PNG_PATH) == (TILE_BYTES, "image/png")


async def test_tile_is_stored_as_raw_bytes(fake_redis):
    """ヒットのたびにデコードを払わないよう、本体は符号化せずそのまま置く。"""
    await jma_tile_redis_cache.set(PNG_PATH, TILE_BYTES, "image/png")
    (key,) = await fake_redis.keys()
    assert TILE_BYTES in (await redis_client.get_redis_binary_client_or_none().get(key))


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


async def test_entry_without_the_separator_is_treated_as_uncached(fake_redis):
    """区切りの無い値は本体とContent-Typeに分けられない（JSONで包んだ値もこれに当たる）。"""
    await jma_tile_redis_cache.set(PNG_PATH, TILE_BYTES, "image/png")
    (key,) = await fake_redis.keys()
    for broken in ("not a tile", '{"empty": true}'):
        await fake_redis.set(key, broken)
        assert await jma_tile_redis_cache.get(PNG_PATH) is None


async def test_read_failure_falls_back_to_uncached(fake_redis, redis_server):
    redis_server.connected = False
    assert await jma_tile_redis_cache.get(PNG_PATH) is None
    assert redis_client.redis_available() is False


async def test_write_failure_is_not_raised_to_the_caller(fake_redis, redis_server):
    redis_server.connected = False
    await jma_tile_redis_cache.set(PNG_PATH, TILE_BYTES, "image/png")
    assert redis_client.redis_available() is False


async def test_failure_stops_further_calls_until_the_cooldown_passes(fake_redis):
    """障害の直後はRedisへ行かない——不通のRedisを1リクエストごとに待つと、
    タイル配信そのものが上流の遅さへ引きずられる。"""
    await jma_tile_redis_cache.set(PNG_PATH, TILE_BYTES, "image/png")
    redis_client.record_redis_failure()
    await jma_tile_redis_cache.set(PBF_PATH, TILE_BYTES, "application/vnd.mapbox-vector-tile")
    assert len(await fake_redis.keys()) == 1
    assert await jma_tile_redis_cache.get(PNG_PATH) is None


async def test_missing_client_is_treated_as_no_cache(monkeypatch):
    monkeypatch.setattr(redis_json_cache, "get_redis_binary_client_or_none", lambda: None)
    await jma_tile_redis_cache.set(PNG_PATH, TILE_BYTES, "image/png")
    assert await jma_tile_redis_cache.get(PNG_PATH) is None
