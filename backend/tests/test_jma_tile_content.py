"""`infrastructure/jma_tile_content.py`——気象庁のタイルに描くものが無いかの判定。

入口は`is_empty_tile`。空と誤って判じると、キャッシュも在否インデックスも「取りに行かなくてよい」と
扱い、危険度の色が地図に出なくなる。迷う入力は「中身あり」に倒れることを見る。

ここで見ないもの:
- 空と判じたタイルをフラグで持つこと → `test_jma_tile_redis_cache.py`
- 在否インデックスへ載せないこと → `test_jma_tile_prewarm_service.py`
"""

import io

from hypothesis import given
from hypothesis import strategies as st
from PIL import Image

from app.infrastructure.jma_tile_content import is_empty_tile

SIZE = 256


def encode(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def transparent() -> Image.Image:
    return Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))


def test_a_palette_raster_whose_every_pixel_is_the_transparent_entry_is_empty():
    """配信元のタイルの形（パレットの0番を透明にした画像）。"""
    image = Image.new("P", (SIZE, SIZE), 0)
    image.putpalette([0, 0, 0, 255, 40, 0] + [0, 0, 0] * 254)
    image.info["transparency"] = 0

    assert is_empty_tile(encode(image), "png")


@given(
    x=st.integers(0, SIZE - 1),
    y=st.integers(0, SIZE - 1),
    alpha=st.integers(1, 255),
)
def test_a_single_pixel_that_is_not_fully_transparent_makes_the_raster_not_empty(x, y, alpha):
    image = transparent()
    image.putpixel((x, y), (255, 40, 0, alpha))

    assert not is_empty_tile(encode(image), "png")


def test_a_raster_without_an_alpha_channel_is_not_empty():
    """透明を表せない画像は、どの画素も描かれている。"""
    assert not is_empty_tile(encode(Image.new("RGB", (SIZE, SIZE), (0, 0, 0))), "png")


def test_bytes_that_cannot_be_read_as_an_image_are_not_empty():
    assert not is_empty_tile(b"", "png")


def test_a_vector_tile_is_empty_only_when_it_carries_no_bytes():
    """配信元は地物の無いベクタタイルを0バイトで返す。中身を解かずに長さで決まる。"""
    assert is_empty_tile(b"", "pbf")
    assert not is_empty_tile(b"\x1a\x00", "pbf")
