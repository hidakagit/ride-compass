"""`infrastructure/gsi_dem_png.py`——地理院の標高タイル（dem_png）をTerrain-RGBのPNGへ移す。

入口は`gsi_dem_png_to_terrain_rgb`。期待値は実装の定数から作らず、2つの公開の仕様から作る:
- 地理院の標高タイル: x = 2^16·R + 2^8·G + B、x < 2^23 なら x·0.01m、x = 2^23 は標高なし、
  x > 2^23 なら (x − 2^24)·0.01m
- Terrain-RGB（MapLibreの`raster-dem`の`mapbox`の書式）: −10000 + (R·256·256 + G·256 + B)·0.1m

ここで見ないもの:
- Terrain-RGBの原点と刻みを画面へ渡すこと → `domain/terrain_rgb.py`（生成物へ書き出す側）
- 地理院からの取得とズームの上限 → `test_gsi_tile_client.py`・`test_gsi_tile_routes.py`
- −10000mを下回る標高の扱い → 地理院の値の範囲（日本の陸地と湖底）では起きない
"""

import io

import numpy as np
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays
from PIL import Image

from app.infrastructure.gsi_dem_png import gsi_dem_png_to_terrain_rgb

GSI_NO_DATA = (128, 0, 0)


def gsi_png(centimeters: np.ndarray) -> bytes:
    """センチメートルの標高を、地理院の書式（24ビットの2の補数）のPNGにする。"""
    x = centimeters.astype(np.int64) % (1 << 24)
    rgb = np.stack([(x >> 16) & 0xFF, (x >> 8) & 0xFF, x & 0xFF], axis=-1).astype(np.uint8)
    return png_of(rgb)


def png_of(rgb: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(rgb, mode="RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def terrain_rgb_meters(png: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(png)) as image:
        assert image.mode == "RGB"
        rgb = np.asarray(image, dtype=np.int64)
    return -10000 + (rgb[:, :, 0] * 256 * 256 + rgb[:, :, 1] * 256 + rgb[:, :, 2]) * 0.1


# 日本の湖底（−400m程度）から富士山頂（3776m）までを余裕を持って覆う。
@given(arrays(np.int64, (3, 4), elements=st.integers(min_value=-100_000, max_value=500_000)))
def test_every_elevation_reads_back_to_the_nearest_tenth_of_a_metre(centimeters):
    meters = terrain_rgb_meters(gsi_dem_png_to_terrain_rgb(gsi_png(centimeters)))

    assert meters.shape == centimeters.shape
    np.testing.assert_allclose(meters, centimeters / 100, atol=0.05 + 1e-6)


def test_a_pixel_without_elevation_becomes_sea_level_not_a_cliff():
    rgb = np.array([[GSI_NO_DATA, (0, 0, 100)]], dtype=np.uint8)

    meters = terrain_rgb_meters(gsi_dem_png_to_terrain_rgb(png_of(rgb)))

    np.testing.assert_allclose(meters, [[0.0, 1.0]], atol=1e-6)

