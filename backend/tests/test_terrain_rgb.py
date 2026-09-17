import io

import numpy as np
import pytest
from PIL import Image

from app.domain.terrain_rgb import decode_terrain_rgb_meters, gsi_dem_png_to_terrain_rgb


def gsi_tile(values_cm: list[list[int]]) -> bytes:
    """センチメートル単位の値（地理院の生値）をそのまま詰めた標高タイルを作る。"""
    array = np.array(values_cm, dtype=np.int64) % (1 << 24)
    rgb = np.empty((*array.shape, 3), dtype=np.uint8)
    rgb[:, :, 0] = (array >> 16) & 0xFF
    rgb[:, :, 1] = (array >> 8) & 0xFF
    rgb[:, :, 2] = array & 0xFF
    buffer = io.BytesIO()
    Image.fromarray(rgb, mode="RGB").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("value_cm", "expected_m"),
    [
        (0, 0.0),
        (1_234, 12.3),  # 12.34m → Terrain-RGBの刻み（0.1m）へ丸める
        (377_600, 3776.0),  # 富士山
        (-500, -5.0),  # 海面下（地理院は2の補数で置く）
    ],
)
def test_標高の値がTerrainRGBへそのまま移る(value_cm: int, expected_m: float) -> None:
    converted = gsi_dem_png_to_terrain_rgb(gsi_tile([[value_cm]]))

    assert decode_terrain_rgb_meters(converted)[0][0] == pytest.approx(expected_m, abs=0.05)


def test_標高なしの画素は海抜0mになる() -> None:
    # Terrain-RGBは「値が無い」を表せない。そのまま大きな数として渡すと、標高のある画素との
    # 境界が数万メートルの崖になり陰影が黒い縁で埋まる。
    no_data = 1 << 23
    converted = gsi_dem_png_to_terrain_rgb(gsi_tile([[no_data, 1_000]]))

    meters = decode_terrain_rgb_meters(converted)
    assert meters[0][0] == pytest.approx(0.0, abs=0.05)
    assert meters[0][1] == pytest.approx(10.0, abs=0.05)


def test_タイルの大きさと画素の並びが保たれる() -> None:
    values = [[0, 100, 200], [300, 400, 500]]

    converted = gsi_dem_png_to_terrain_rgb(gsi_tile(values))

    meters = decode_terrain_rgb_meters(converted)
    assert meters.shape == (2, 3)
    np.testing.assert_allclose(meters, np.array(values) / 100.0, atol=0.05)
