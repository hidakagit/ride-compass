"""`domain/terrain_rgb.py`——国土地理院の標高タイル（dem_png）を、MapLibreが読むTerrain-RGBのPNGへ移す。

入口は`gsi_dem_png_to_terrain_rgb`。期待値は実装の定数からではなく、両方式の公開の仕様から書く:
- 地理院（「標高タイルの詳細仕様」）: x = 2^16R + 2^8G + B。x < 2^23 なら x×0.01m、x > 2^23 なら (x − 2^24)×0.01m、
  x = 2^23 は標高なし
- Terrain-RGB（Mapbox）: 標高 = −10000 + (R×256×256 + G×256 + B)×0.1m

ここで見ないもの:
- 地理院からの取得・中継の応答（404・502） → `test_gsi_tile_routes.py`
"""

import io

import numpy as np
from PIL import Image

from app.domain.terrain_rgb import gsi_dem_png_to_terrain_rgb


def gsi_png(heights_cm: list[list[int | None]]) -> bytes:
    """地理院の符号化で、センチメートル単位の標高（Noneは標高なし）を並べたPNG。"""
    pixels = np.zeros((len(heights_cm), len(heights_cm[0]), 3), dtype=np.uint8)
    for row, line in enumerate(heights_cm):
        for column, height in enumerate(line):
            x = 1 << 23 if height is None else height % (1 << 24)
            pixels[row, column] = (x >> 16, (x >> 8) & 0xFF, x & 0xFF)
    buffer = io.BytesIO()
    Image.fromarray(pixels, mode="RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def converted_heights(heights_cm: list[list[int | None]]) -> np.ndarray:
    """地理院の符号化のPNGを変換し、Terrain-RGBとして読み戻した標高（m）。"""
    with Image.open(io.BytesIO(gsi_dem_png_to_terrain_rgb(gsi_png(heights_cm)))) as image:
        assert image.format == "PNG"
        assert image.mode == "RGB"
        rgb = np.asarray(image, dtype=np.int64)
    return -10000 + (rgb[:, :, 0] * 256 * 256 + rgb[:, :, 1] * 256 + rgb[:, :, 2]) * 0.1


def test_heights_above_and_below_sea_level_keep_their_value():
    heights = converted_heights([[377600, 0, -500]])

    np.testing.assert_allclose(heights, [[3776.0, 0.0, -5.0]], atol=1e-6)


def test_a_pixel_without_height_becomes_sea_level():
    """Terrain-RGBに「値なし」は無い。大きな数のまま渡すと、標高のある画素との境が崖になる。"""
    heights = converted_heights([[None, 1234]])

    np.testing.assert_allclose(heights, [[0.0, 12.3]], atol=1e-6)


def test_centimeters_round_to_the_nearest_tenth_of_a_meter():
    heights = converted_heights([[1234, 1236, -1234, -1236]])

    np.testing.assert_allclose(heights, [[12.3, 12.4, -12.3, -12.4]], atol=1e-6)


def test_the_tile_keeps_its_size_and_pixel_positions():
    source = [[100 * (row * 3 + column) for column in range(3)] for row in range(2)]

    heights = converted_heights(source)

    np.testing.assert_allclose(heights, np.array(source) / 100, atol=1e-6)
