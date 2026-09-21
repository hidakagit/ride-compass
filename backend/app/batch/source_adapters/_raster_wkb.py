"""画素の並びを、PostGISのrasterが読める形（WKB）へ包む。

面のソースはタイル1枚=1行で入る。**画素はDB側で引く**ので、位置・画素の大きさ・型・
欠測値をこちらが`attrs`へ書いて読み手に解釈させるのではなく、rasterの値自身に持たせる。

包むだけで、画素の並びには触らない——PostGISのバンドはリトルエンディアンの並びを
そのまま受け取るため、取込が作った配列をヘッダの後ろへ置けばよい。

タイルはWebメルカトル（EPSG:3857）で正方格子になるので、その座標系で位置を与える。
経緯度（4326）だと緯度方向の画素幅が一定でなく、位置から画素を引けない。
"""

import struct

import shapely
from shapely.geometry import box

from app.domain.region import tile_bounds_lonlat

#: Webメルカトルが世界を写す一辺の半分（m）。
_WORLD_HALF_M = 20037508.342789244

#: 取込が`attrs`へ書く型 → PostGISのバンド種別と、欠測値の詰め方。
_BAND_TYPE: dict[str, tuple[int, str]] = {
    "uint8": (4, "<B"),      # 8BUI
    "int16_le": (5, "<h"),   # 16BSI
    "int32_le": (7, "<i"),   # 32BSI
}

#: バンドが欠測値を持つことを表すフラグ。下位4ビットが種別。
_HAS_NODATA = 0x40


def tile_raster_wkb(pixels: bytes, *, zoom: int, x: int, y: int,
                    width: int, height: int, dtype: str, nodata: int) -> bytes:
    """タイル1枚のraster WKB。`pixels`はそのまま1バンドの中身になる。"""
    band_type, nodata_format = _BAND_TYPE[dtype]
    span = 2 * _WORLD_HALF_M / (2 ** zoom)
    header = struct.pack(
        "<BHH dddd dd i HH",
        1,                              # リトルエンディアン
        0,                              # 版
        1,                              # バンド数
        span / width,                   # 画素の幅
        -span / height,                 # 画素の高さ（上から下へ）
        -_WORLD_HALF_M + x * span,      # 左上のX
        _WORLD_HALF_M - y * span,       # 左上のY
        0.0, 0.0,                       # ゆがみ
        3857,
        width, height,
    )
    band = struct.pack("<B", _HAS_NODATA | band_type) + struct.pack(nodata_format, nodata)
    return header + band + pixels


def tile_bbox_wkb(zoom: int, x: int, y: int) -> bytes:
    """タイルが覆う範囲のWKB（SRID 4326の座標で作る）。"""
    bounds = tile_bounds_lonlat(zoom, x, y)
    return shapely.to_wkb(box(bounds.min_longitude, bounds.min_latitude,
                              bounds.max_longitude, bounds.max_latitude))
