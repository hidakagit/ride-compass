"""`domain/terrain_rgb.py`——地理院の標高タイルをMapLibreのTerrain-RGBへ詰め直す。

両者の詰め方の違いは実装のdocstringが持つ。タイルの取得と配信は
`services/terrain_tile_service.py`側で、ここでは見ない。
"""

import io

import numpy as np
from PIL import Image

from app.domain.terrain_rgb import gsi_dem_png_to_terrain_rgb

GSI_NO_DATA_PIXEL = (128, 0, 0)


def _gsi_png(pixels: list[tuple[int, int, int]]) -> bytes:
    image = Image.new("RGB", (len(pixels), 1))
    image.putdata(pixels)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _gsi_pixel(meters: float) -> tuple[int, int, int]:
    centimeters = round(meters * 100)
    packed = centimeters if centimeters >= 0 else centimeters + (1 << 24)
    return ((packed >> 16) & 0xFF, (packed >> 8) & 0xFF, packed & 0xFF)


def _decoded_meters(png: bytes) -> list[float]:
    """刻みが0.1mなので、0.1m単位へ丸めてから比べる（二進小数の端数を持ち込まない）。"""
    with Image.open(io.BytesIO(png)) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.int64).reshape(-1, 3)
    packed = (rgb[:, 0] << 16) | (rgb[:, 1] << 8) | rgb[:, 2]
    return [round(-10000 + int(value) * 0.1, 1) for value in packed]


def _convert(meters: list[float]) -> list[float]:
    return _decoded_meters(gsi_dem_png_to_terrain_rgb(_gsi_png([_gsi_pixel(m) for m in meters])))


def test_positive_elevation_survives_the_round_trip():
    assert _convert([0.0, 12.3, 1500.0, 3776.0]) == [0.0, 12.3, 1500.0, 3776.0]


def test_negative_elevation_is_read_as_two_s_complement():
    """符号を戻さないと、数千kmの高地として出る。"""
    assert _convert([-1.0, -25.5]) == [-1.0, -25.5]


def test_missing_elevation_becomes_sea_level():
    png = gsi_dem_png_to_terrain_rgb(_gsi_png([GSI_NO_DATA_PIXEL]))

    assert _decoded_meters(png) == [0.0]


def test_centimetre_detail_is_rounded_to_the_terrain_rgb_step():
    assert _convert([1.04, 1.06]) == [1.0, 1.1]


def test_below_the_origin_is_clamped_instead_of_wrapping():
    """折り返すと海溝が高山として出る。"""
    assert _convert([-10000.0, -12000.0]) == [-10000.0, -10000.0]


def test_the_image_keeps_its_shape():
    png = gsi_dem_png_to_terrain_rgb(_gsi_png([_gsi_pixel(1.0), _gsi_pixel(2.0), _gsi_pixel(3.0)]))

    with Image.open(io.BytesIO(png)) as image:
        assert image.size == (3, 1)
        assert image.mode == "RGB"
