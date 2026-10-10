"""`infrastructure/gsi_dem_png.py`——地理院の標高タイル（dem_png）をTerrain-RGBのPNGへ移す。

入口は`gsi_dem_png_to_terrain_rgb`。期待値は実装の定数から作らず、2つの公開の仕様から作る:
- 地理院の標高タイル: `tests/source_ingest.py: gsi_dem_png`が仕様から作る（欠測の画素だけは、ここで仕様の色を直に置く）
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
from tests.source_ingest import gsi_dem_png

GSI_NO_DATA = (128, 0, 0)


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
    meters = terrain_rgb_meters(gsi_dem_png_to_terrain_rgb(gsi_dem_png((centimeters / 100).tolist())))

    np.testing.assert_allclose(meters, centimeters / 100, atol=0.05 + 1e-6)


def test_a_pixel_without_elevation_becomes_sea_level_not_a_cliff():
    rgb = np.array([[GSI_NO_DATA]], dtype=np.uint8)

    meters = terrain_rgb_meters(gsi_dem_png_to_terrain_rgb(png_of(rgb)))

    np.testing.assert_allclose(meters, [[0.0]], atol=1e-6)

