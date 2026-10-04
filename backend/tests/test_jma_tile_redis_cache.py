"""`infrastructure/jma_tile_redis_cache.py`——気象庁のタイルの本体をRedisへ持つ置き場。

入口は`get`・`set`・`set_empty`。Redisはfakeredis、時計はfreezegunで与える。

ここで見ないもの:
- どのタイルを空とみなすか（透明・0バイト・読めない画像） → `test_jma_tile_content.py`。ここでは空の代表を1つずつ使う
- いつ`set_empty`を呼ぶか（確定した404） → `test_jma_tile_client.py`
- Redisの障害で接続を止める回路そのもの → `test_redis_client.py`
"""

import io

from PIL import Image

from app.infrastructure import jma_tile_redis_cache
from app.infrastructure.jma_tile_redis_cache import EmptyTile

TILE = "bosai/jmatile/data/risk/20260101000000/none/20260101000000/surf/land/10/908/403.png"
OTHER_TILE = "bosai/jmatile/data/risk/20260101000000/none/20260101000000/surf/land/10/908/404.png"
VECTOR_TILE = "bosai/jmatile/data/risk/20260101000000/none/20260101000000/surf/flood/10/908/403.pbf"


def png(alpha: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (4, 4), (255, 0, 0, alpha)).save(buffer, format="PNG")
    return buffer.getvalue()


async def test_a_tile_never_stored_is_a_miss(fake_redis):
    assert await jma_tile_redis_cache.get(TILE) is None


async def test_a_stored_tile_comes_back_byte_for_byte_with_its_content_type(fake_redis):
    """本体は区切りのNULを含みうる。区切りで本体を切ると、画像が途中で切れて壊れて届く。"""
    content = png(255) + b"\0trailing\0bytes"

    await jma_tile_redis_cache.set(TILE, content, "image/png; charset=binary")

    assert await jma_tile_redis_cache.get(TILE) == (content, "image/png; charset=binary")


async def test_each_path_keeps_its_own_entry(fake_redis):
    await jma_tile_redis_cache.set(TILE, png(255), "image/png")

    assert await jma_tile_redis_cache.get(OTHER_TILE) is None


async def test_a_tile_with_nothing_to_draw_comes_back_as_the_flag(fake_redis):
    await jma_tile_redis_cache.set(TILE, png(0), "image/png")

    assert isinstance(await jma_tile_redis_cache.get(TILE), EmptyTile)


async def test_a_vector_tile_is_judged_as_a_vector_by_its_path(fake_redis):
    """ベクタは長さで空を見る。画像として読もうとすると、空のベクタも「中身あり」で実体を持つ。"""
    await jma_tile_redis_cache.set(VECTOR_TILE, b"", "application/x-protobuf")
    await jma_tile_redis_cache.set(VECTOR_TILE + "?v=1", b"\x1a\x02", "application/x-protobuf")

    assert isinstance(await jma_tile_redis_cache.get(VECTOR_TILE), EmptyTile)
    assert await jma_tile_redis_cache.get(VECTOR_TILE + "?v=1") == (b"\x1a\x02", "application/x-protobuf")


async def test_a_path_recorded_as_having_nothing_to_draw_comes_back_as_the_flag(fake_redis):
    await jma_tile_redis_cache.set_empty(TILE)

    assert isinstance(await jma_tile_redis_cache.get(TILE), EmptyTile)


async def test_a_later_tile_replaces_what_was_recorded(fake_redis):
    await jma_tile_redis_cache.set_empty(TILE)
    await jma_tile_redis_cache.set(TILE, png(255), "image/png")

    assert await jma_tile_redis_cache.get(TILE) == (png(255), "image/png")


async def test_tiles_and_flags_are_forgotten_after_twenty_minutes(fake_redis, clock):
    """プリウォームの間隔（10分）より長く持ち、1回温め損ねても地図から消えない。"""
    await jma_tile_redis_cache.set(TILE, png(255), "image/png")
    await jma_tile_redis_cache.set_empty(OTHER_TILE)

    clock.tick(20 * 60 - 1)
    assert await jma_tile_redis_cache.get(TILE) is not None
    assert await jma_tile_redis_cache.get(OTHER_TILE) is not None
    clock.tick(2)
    assert await jma_tile_redis_cache.get(TILE) is None
    assert await jma_tile_redis_cache.get(OTHER_TILE) is None


async def test_without_redis_nothing_is_kept_and_nothing_is_raised(fake_redis, redis_server):
    """Redisが落ちても、呼び出し元は上流へ取りに行く道へ進める。"""
    redis_server.connected = False

    await jma_tile_redis_cache.set(TILE, png(255), "image/png")
    await jma_tile_redis_cache.set_empty(OTHER_TILE)

    assert await jma_tile_redis_cache.get(TILE) is None
    assert await jma_tile_redis_cache.get(OTHER_TILE) is None
