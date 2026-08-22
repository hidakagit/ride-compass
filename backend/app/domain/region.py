import math

from pydantic import BaseModel

# 路面の地域レイヤーは標準的なXYZベクタタイル（MapLibreのvector source）として配信する。
# ズームレベルでタイルの細かさ・生成範囲を制御することで、ビューポートの対角距離を
# 都度計算して広域リクエストを拒否する必要がなくなった（MapLibre自体がminzoom未満では
# タイルを要求しないため）。ROAD_TILE_MIN_ZOOM未満のタイル要求はバックエンド側でも
# 念のため拒否する（直接APIを叩かれた場合の安全弁）。
ROAD_TILE_MIN_ZOOM = 12
ROAD_TILE_MAX_ZOOM = 15

# Road Graphの永続化キャッシュ単位（GraphService, road_graph_repository.py）。
# RegionServiceのROAD_TILE_MIN_ZOOM/MAX_ZOOMはMapLibreの表示ズームに追従するための範囲だが、
# Road Graphには「現在の表示ズーム」という概念が無く、キャッシュの正確なカバレッジ判定
# （「このタイルは取得済みか」という単純な真偽判定にできる）だけが目的のため、
# 単一の固定ズームレベルとする。z12は東京付近で1辺約8km程度（1辺=360/2^12度）。
# 細かすぎるとOverpassへの問い合わせ回数（=タイル数）が増え、粗すぎると1回の
# 問い合わせが大きくなり公開Overpassインスタンスへの負荷が増す、というトレードオフの
# 暫定値であり、実データが蓄積された段階で見直す余地がある。
ROAD_GRAPH_TILE_ZOOM = 12


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


# Web Mercatorで表現できる緯度の限界（tile_bounds_lonlat(0, 0, 0)の緯度範囲と一致）。
# BoundingBoxはCoordinatesと異なり緯度の範囲を検証しない（仕様上どんな値も受け付ける）ため、
# 万一範囲外の値（例: 90度を超える不正な入力）が渡された場合、_lonlat_to_tile_indexの
# math.log(負の値)がValueError（math domain error）を送出しうる。これを避けるため
# 呼び出し前に有効範囲へクランプする。
_MAX_MERCATOR_LATITUDE = 85.05112878


def _lonlat_to_tile_index(lon: float, lat: float, z: int) -> tuple[int, int]:
    """緯度経度からそれを含むXYZタイルのx,yを求める（tile_bounds_lonlatの逆関数）。"""
    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    clamped_lat = max(-_MAX_MERCATOR_LATITUDE, min(lat, _MAX_MERCATOR_LATITUDE))
    lat_rad = math.radians(clamped_lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def lonlat_to_tile_pixel(lon: float, lat: float, z: int, tile_size: int = 256) -> tuple[int, int, float, float]:
    """緯度経度から、そのタイルの(tile_x, tile_y)と、タイル内の連続位置(px, py、
    0.0〜tile_sizeの浮動小数点)を返す（`_lonlat_to_tile_index`と同じWeb Mercator変換の
    式だが、タイル内の小数位置も同時に求める点が異なる。改善計画T10: DEMタイルの
    双線形補間で、対象地点がタイル内のどのピクセル位置に当たるかを求めるために使う）。
    """
    n = 2**z
    x_f = (lon + 180.0) / 360.0 * n
    clamped_lat = max(-_MAX_MERCATOR_LATITUDE, min(lat, _MAX_MERCATOR_LATITUDE))
    lat_rad = math.radians(clamped_lat)
    y_f = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    tile_x, px_frac = divmod(x_f, 1.0)
    tile_y, py_frac = divmod(y_f, 1.0)
    return int(tile_x), int(tile_y), px_frac * tile_size, py_frac * tile_size


def tile_ancestor(z: int, x: int, y: int, ancestor_zoom: int) -> tuple[int, int]:
    """XYZタイル(z, x, y)を含む、より粗いズームancestor_zoomの祖先タイルの(x, y)を返す。

    路面タイル（ROAD_TILE_MIN_ZOOM..MAX_ZOOM）が、Road Graphのタイル単位カバレッジ
    （ROAD_GRAPH_TILE_ZOOM=12の取得済みマーカー）に含まれるかを判定するために使う。
    XYZタイルはズームが1段細かくなるごとにx,yが2分割されるため、右シフトで求まる。
    z < ancestor_zoomの呼び出しは前提違反（子孫は一意に定まらない）。
    """
    if z < ancestor_zoom:
        raise ValueError(f"z={z} is coarser than ancestor_zoom={ancestor_zoom}")
    shift = z - ancestor_zoom
    return x >> shift, y >> shift


def tiles_covering_bbox(bbox: BoundingBox, z: int) -> list[tuple[int, int]]:
    """bboxを覆う最小限のXYZタイル群の(x, y)一覧を返す（Road Graphのタイル単位キャッシュ用）。

    XYZタイルはyが北から南へ増加する（緯度と逆向き）ため、北西端（min_longitude,
    max_latitude）と南東端（max_longitude, min_latitude）のタイル座標からx,yそれぞれの
    範囲を求める。
    """
    n = 2**z
    x_start, y_start = _lonlat_to_tile_index(bbox.min_longitude, bbox.max_latitude, z)
    x_end, y_end = _lonlat_to_tile_index(bbox.max_longitude, bbox.min_latitude, z)
    x_start, x_end = sorted((max(0, min(x_start, n - 1)), max(0, min(x_end, n - 1))))
    y_start, y_end = sorted((max(0, min(y_start, n - 1)), max(0, min(y_end, n - 1))))
    return [(x, y) for x in range(x_start, x_end + 1) for y in range(y_start, y_end + 1)]
