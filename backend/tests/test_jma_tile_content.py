"""`infrastructure/jma_tile_content.py`——タイルに描くものが無いかの判定。"""

import io

import pytest
from PIL import Image

from app.infrastructure.jma_tile_content import is_empty_tile

TRANSPARENT = (0, 0, 0, 0)


def _png(pixels: dict[tuple[int, int], tuple[int, int, int, int]] | None = None) -> bytes:
    image = Image.new("RGBA", (256, 256), TRANSPARENT)
    for position, color in (pixels or {}).items():
        image.putpixel(position, color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_a_fully_transparent_raster_is_empty():
    assert is_empty_tile(_png(), "png") is True


@pytest.mark.parametrize(
    "color",
    [(242, 231, 0, 255), (255, 40, 0, 40)],
    ids=["不透明", "わずかに透ける"],
)
def test_a_single_drawn_pixel_makes_the_raster_not_empty(color):
    # 危険度は局所的に出るため、わずかな塗りを取りこぼすと危険情報が表示されなくなる。
    assert is_empty_tile(_png({(128, 128): color}), "png") is False


@pytest.mark.parametrize(("content", "expected"), [(b"", True), (b"\x1a\x02\x0a", False)])
def test_a_vector_tile_is_empty_only_when_it_has_no_bytes(content, expected):
    assert is_empty_tile(content, "pbf") is expected


def test_content_that_cannot_be_decoded_is_treated_as_having_something():
    # 空と誤判定すると、取りに行かない・実体を持たない根拠に使われ、危険情報が消える。
    assert is_empty_tile(b"not-a-png", "png") is False
