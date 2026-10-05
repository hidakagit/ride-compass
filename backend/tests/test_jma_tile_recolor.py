"""`infrastructure/jma_tile_recolor.py`——気象庁の降水のタイルの色を、アプリの降水の段の色へ塗り替える。

入口は`recolored`。タイルは配信元と同じパレット形式（透明の項目と段の色の項目）の画像をテストの中で作る。

ここで見ないもの:
- 取得したタイルが塗り替えられてキャッシュへ入ること → `test_jma_tile_client.py`
"""

import io

import pytest
from PIL import Image, ImageColor

from app.domain.weather_display import PRECIPITATION_COLOR_STOPS
from app.infrastructure.jma_tile_recolor import JMA_PRECIPITATION_TILE_COLORS, recolored

FRAME = "bosai/jmatile/data/nowc/20260101000000/none/20260101000500/surf"
PRECIPITATION = f"{FRAME}/hrpns/6/57/25.png"
THUNDER = f"{FRAME}/thns/6/57/25.png"
UNKNOWN = "#123456"


def palette_tile(colors: list[str]) -> bytes:
    """1列目を透明にし、2列目から`colors`を1画素ずつ並べたパレット形式のPNG。"""
    image = Image.new("P", (len(colors) + 1, 1), 0)
    image.putpalette([0, 0, 0, *(value for color in colors for value in ImageColor.getrgb(color))])
    image.putdata(range(len(colors) + 1))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", transparency=0)
    return buffer.getvalue()


def pixels(content: bytes) -> list[tuple[int, int, int, int]]:
    with Image.open(io.BytesIO(content)) as image:
        return list(image.convert("RGBA").get_flattened_data())


def rgba(color: str) -> tuple[int, int, int, int]:
    return (*ImageColor.getrgb(color), 255)


def test_each_band_is_painted_with_the_legend_color_of_the_same_band():
    tile = palette_tile([*JMA_PRECIPITATION_TILE_COLORS, UNKNOWN])

    painted = pixels(recolored(PRECIPITATION, tile))

    assert painted[0][3] == 0
    assert painted[1:] == [*(rgba(stop.color) for stop in PRECIPITATION_COLOR_STOPS), rgba(UNKNOWN)]


@pytest.mark.parametrize(
    ("path", "content"),
    [
        (THUNDER, palette_tile(list(JMA_PRECIPITATION_TILE_COLORS))),
        (PRECIPITATION, b"\x89PNG broken"),
    ],
    ids=["not_precipitation", "unreadable"],
)
def test_other_tiles_and_unreadable_images_are_served_as_they_came(path, content):
    assert recolored(path, content) == content
