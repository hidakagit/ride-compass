"""国土地理院の標高タイル（dem_png）を、MapLibreの`raster-dem`が読むTerrain-RGBへ移す。

両者はどちらも標高を1画素のRGBへ詰めるが、詰め方が違う。地理院はセンチメートル単位の
符号付き整数を2の補数で置き、標高が無い画素へ`_GSI_NO_DATA`という決め打ちの値を入れる。
Terrain-RGBは-10000mを原点とする0.1m刻みの符号なし整数で、無効値の表し方を持たない。

**無効値を海抜0mへ倒すのは、Terrain-RGBに「値が無い」を表す手段が無いため**。そのまま
大きな数として渡すと、標高の無い画素との境界がすべて数万メートルの崖になり、陰影が
真っ黒な縁で埋まる。
"""

import io

import numpy as np
from PIL import Image

# 地理院が「標高なし」に使う値（2^23）。実画素では(128, 0, 0)として現れる。
_GSI_NO_DATA = 1 << 23
_GSI_WRAP = 1 << 24
# 地理院の値の単位（m）。Terrain-RGBの刻み（0.1m）より細かいため、詰め直すとき丸める。
_GSI_UNIT_M = 0.01
_TERRAIN_RGB_UNIT_M = 0.1
_TERRAIN_RGB_BASE_M = -10000.0
_TERRAIN_RGB_MAX = _GSI_WRAP - 1


def gsi_dem_png_to_terrain_rgb(png: bytes) -> bytes:
    """地理院の標高タイル1枚をTerrain-RGBのPNGへ変換する。"""
    with Image.open(io.BytesIO(png)) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.int64)

    packed = (rgb[:, :, 0] << 16) | (rgb[:, :, 1] << 8) | rgb[:, :, 2]
    signed = np.where(packed > _GSI_NO_DATA, packed - _GSI_WRAP, packed)
    meters = np.where(packed == _GSI_NO_DATA, 0.0, signed * _GSI_UNIT_M)

    encoded = np.rint((meters - _TERRAIN_RGB_BASE_M) / _TERRAIN_RGB_UNIT_M).astype(np.int64)
    encoded = np.clip(encoded, 0, _TERRAIN_RGB_MAX)

    out = np.empty((*encoded.shape, 3), dtype=np.uint8)
    out[:, :, 0] = (encoded >> 16) & 0xFF
    out[:, :, 1] = (encoded >> 8) & 0xFF
    out[:, :, 2] = encoded & 0xFF

    buffer = io.BytesIO()
    Image.fromarray(out, mode="RGB").save(buffer, format="PNG")
    return buffer.getvalue()

