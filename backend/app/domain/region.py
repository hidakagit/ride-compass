import math

from pydantic import BaseModel

# 路面の地域レイヤーは標準的なXYZベクタタイル（MapLibreのvector source）として配信する。
# ズームレベルでタイルの細かさ・生成範囲を制御することで、ビューポートの対角距離を
# 都度計算して広域リクエストを拒否する必要がなくなった（MapLibre自体がminzoom未満では
# タイルを要求しないため）。ROAD_TILE_MIN_ZOOM未満のタイル要求はバックエンド側でも
# 念のため拒否する（直接APIを叩かれた場合の安全弁）。
ROAD_TILE_MIN_ZOOM = 12
ROAD_TILE_MAX_ZOOM = 15


class BoundingBox(BaseModel):
    min_latitude: float
    min_longitude: float
    max_latitude: float
    max_longitude: float


def tile_bounds_lonlat(z: int, x: int, y: int) -> BoundingBox:
    """標準的なXYZスライピータイル（Web Mercator）のz/x/yから、そのタイルが覆う緯度経度の範囲を求める。"""
    n = 2**z
    lon_left = x / n * 360.0 - 180.0
    lon_right = (x + 1) / n * 360.0 - 180.0
    lat_top = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_bottom = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return BoundingBox(
        min_latitude=lat_bottom,
        min_longitude=lon_left,
        max_latitude=lat_top,
        max_longitude=lon_right,
    )
