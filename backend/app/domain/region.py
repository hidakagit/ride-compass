import math

from app.domain.strict_model import StrictModel

# 路面の地域レイヤーが配信されるXYZズームの範囲。MapLibreはminzoom未満でタイルを
# 要求しないが、直接APIを叩かれた場合に備えてバックエンド側でもこの範囲外を拒否する。
ROAD_TILE_MIN_ZOOM = 12
ROAD_TILE_MAX_ZOOM = 15

# Road Graphの永続化キャッシュ単位。表示ズームに追従するROAD_TILE_MIN/MAX_ZOOMと違い、
# 「このタイルは取得済みか」を単純な真偽で判定するために単一の固定ズームとする。
# z12は東京付近で1辺約8km（1辺=360/2^12度）。
ROAD_GRAPH_TILE_ZOOM = 12


class BoundingBox(StrictModel):
    min_latitude: float
    min_longitude: float
    max_latitude: float
    max_longitude: float


def parse_bbox(text: str) -> BoundingBox:
    """CLIの--bbox（"min_lat,min_lon,max_lat,max_lon"）をBoundingBoxへ変換する。

    緯度経度の順序はCLI間で揃える（片方だけ経度先にすると、値が入れ替わっても4値の
    数として通ってしまい、黙って別の場所を指す）。
    """
    parts = [float(p) for p in text.split(",")]
    if len(parts) != 4:
        raise ValueError("--bboxは min_lat,min_lon,max_lat,max_lon の4値が必要です")
    min_lat, min_lon, max_lat, max_lon = parts
    if min_lat >= max_lat or min_lon >= max_lon:
        raise ValueError("--bboxはmin < maxとなる範囲が必要です")
    return BoundingBox(
        min_latitude=min_lat, min_longitude=min_lon, max_latitude=max_lat, max_longitude=max_lon
    )


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


# Web Mercatorで表現できる緯度の限界。BoundingBoxはCoordinatesと異なり緯度の範囲を
# 検証しないため、範囲外の値が来ると_lonlat_to_tile_indexのmath.logがmath domain errorを
# 送出する。これを避けるためクランプしてから使う。
_MAX_MERCATOR_LATITUDE = 85.05112878


def _lonlat_to_tile_index(lon: float, lat: float, z: int) -> tuple[int, int]:
    """緯度経度からそれを含むXYZタイルのx,yを求める（tile_bounds_lonlatの逆関数）。"""
    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    clamped_lat = max(-_MAX_MERCATOR_LATITUDE, min(lat, _MAX_MERCATOR_LATITUDE))
    lat_rad = math.radians(clamped_lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def tile_ancestor(z: int, x: int, y: int, ancestor_zoom: int) -> tuple[int, int]:
    """XYZタイル(z, x, y)を含む、より粗いズームancestor_zoomの祖先タイルの(x, y)を返す。

    z < ancestor_zoomは前提違反（祖先ではなく子孫になり、一意に定まらない）。
    """
    if z < ancestor_zoom:
        raise ValueError(f"z={z} is coarser than ancestor_zoom={ancestor_zoom}")
    shift = z - ancestor_zoom
    return x >> shift, y >> shift


def tiles_covering_bbox(bbox: BoundingBox, z: int) -> list[tuple[int, int]]:
    """bboxを覆う最小限のXYZタイル群の(x, y)一覧を返す。

    XYZタイルはyが北から南へ増加する（緯度と逆向き）ため、北西端と南東端のタイル座標から
    x,yそれぞれの範囲を求める。
    """
    n = 2**z
    x_start, y_start = _lonlat_to_tile_index(bbox.min_longitude, bbox.max_latitude, z)
    x_end, y_end = _lonlat_to_tile_index(bbox.max_longitude, bbox.min_latitude, z)
    x_start, x_end = sorted((max(0, min(x_start, n - 1)), max(0, min(x_end, n - 1))))
    y_start, y_end = sorted((max(0, min(y_start, n - 1)), max(0, min(y_end, n - 1))))
    return [(x, y) for x in range(x_start, x_end + 1) for y in range(y_start, y_end + 1)]
