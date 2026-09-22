"""`infrastructure/jma_tile_content.py`——タイルに描くものがあるかの判定。

ここで見ないもの:
- 空と分かったタイルの持ち方（フラグで保存する側） → `test_jma_tile_redis_cache.py`
- 在否インデックスへの記録 → `test_jma_tile_prewarm_service.py`
"""

import io

from PIL import Image

from app.infrastructure.jma_tile_content import is_empty_tile


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_fully_transparent_raster_is_empty():
    assert is_empty_tile(_png(Image.new("RGBA", (8, 8), (0, 0, 0, 0))), "png") is True


def test_raster_with_a_single_opaque_pixel_is_not_empty():
    image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    image.putpixel((7, 7), (200, 0, 0, 255))
    assert is_empty_tile(_png(image), "png") is False


def test_raster_without_an_alpha_channel_is_not_empty():
    assert is_empty_tile(_png(Image.new("RGB", (8, 8), (255, 255, 255))), "png") is False


def test_content_that_cannot_be_read_as_an_image_is_not_empty():
    assert is_empty_tile(b"", "png") is False
    assert is_empty_tile(b"not an image", "png") is False


def test_vector_tile_is_empty_only_when_it_carries_no_bytes():
    assert is_empty_tile(b"", "pbf") is True
    assert is_empty_tile(b"\x1a\x02\x78\x02", "pbf") is False
