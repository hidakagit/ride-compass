"""地理院の標高タイルをTerrain-RGBへ移す変換（`domain/terrain_rgb.py`）。

地図の「起伏」レイヤー（`MapView.tsx: ensureTerrainHillshadeLayer`）がMapLibreの
`raster-dem`として読む唯一の出口。ここがずれると陰影が黙って変わる。

入力の仕様（https://maps.gsi.go.jp/development/demtile.html）:
- 「x = 2^16 R + 2^8 G + B」「u = 0.01」
- 「x < 2^23 のとき h = xu」「x > 2^23 のとき h = (x - 2^24)u」
- 「x = 2^23 のとき 標高値なし」「無効値の場合は (R,G,B)=(128,0,0)」

出力の仕様（Mapbox Terrain-RGB）:
- height = -10000 + (R * 256 * 256 + G * 256 + B) * 0.1
"""

import io

import numpy as np
import pytest
from PIL import Image

from app.domain.terrain_rgb import gsi_dem_png_to_terrain_rgb

GSI_NO_DATA_PIXEL = (128, 0, 0)


def _gsi_png(*meters: float | None) -> bytes:
    """標高（m）を地理院の詰め方でPNGにする。Noneは無効値。"""
    pixels = []
    for value in meters:
        if value is None:
            pixels.append(GSI_NO_DATA_PIXEL)
            continue
        x = round(value / 0.01)
        if x < 0:
            x += 1 << 24
        pixels.append(((x >> 16) & 0xFF, (x >> 8) & 0xFF, x & 0xFF))
    buffer = io.BytesIO()
    Image.fromarray(np.array([pixels], dtype=np.uint8), mode="RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def _decode(png: bytes) -> list[float]:
    """Terrain-RGBのPNGを標高（m）へ戻す。MapLibreが行う計算をそのまま書く。"""
    with Image.open(io.BytesIO(png)) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.int64).reshape(-1, 3)
    return [-10000 + (int(r) * 256 * 256 + int(g) * 256 + int(b)) * 0.1 for r, g, b in rgb]


def _roundtrip(*meters: float | None) -> list[float]:
    return _decode(gsi_dem_png_to_terrain_rgb(_gsi_png(*meters)))


@pytest.mark.parametrize("meters", [0.0, 3.5, 634.0, 3776.0])
def test_正の標高が往復する(meters):
    assert _roundtrip(meters) == pytest.approx([meters], abs=0.05)


@pytest.mark.parametrize("meters", [-0.5, -4.5, -100.0])
def test_負の標高が往復する(meters):
    """海抜より低い土地（干拓地など）。2の補数の折り返しを読み違えると数万mになる。"""
    assert _roundtrip(meters) == pytest.approx([meters], abs=0.05)


def test_無効値は海抜0mへ倒す():
    """Terrain-RGBに「値が無い」を表す手段が無い。大きな数のまま渡すと、標高のある画素との
    境界がすべて崖になり、陰影が真っ黒な縁で埋まる。"""
    assert _roundtrip(None) == pytest.approx([0.0], abs=0.05)


def test_無効値の隣に崖を作らない():
    """海沿いの1枚には有効な画素と無効な画素が隣り合う。差が数十mに収まること。"""
    values = _roundtrip(12.0, None, 12.0)
    assert max(values) - min(values) < 20.0


def test_01m刻みへ丸める():
    """地理院は0.01m単位、Terrain-RGBは0.1m刻み。切り捨てず最も近い刻みへ寄せる。"""
    assert _roundtrip(1.04, 1.06) == pytest.approx([1.0, 1.1], abs=0.001)


def test_下限を割る値でも折り返さない():
    """地理院が表せる最小は約-83,886m。Terrain-RGBの原点(-10000m)を下回るが、
    符号を巻き戻して山に見せてはいけない。"""
    assert _roundtrip(-50000.0) == pytest.approx([-10000.0], abs=0.05)


def test_画素数と形が変わらない():
    """タイルは256×256。欠けるとMapLibreがそのタイルを描かない。"""
    source = Image.new("RGB", (4, 3), GSI_NO_DATA_PIXEL)
    buffer = io.BytesIO()
    source.save(buffer, format="PNG")

    with Image.open(io.BytesIO(gsi_dem_png_to_terrain_rgb(buffer.getvalue()))) as out:
        assert (out.size, out.mode) == ((4, 3), "RGB")
