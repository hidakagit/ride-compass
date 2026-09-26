import math
from collections.abc import Sequence

from pydantic import Field, model_validator

from app.domain.geo import KM_PER_DEGREE_LATITUDE, LatLon, km_per_degree_longitude
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
    """緯度経度の矩形。緯度と経度それぞれがmin < maxであることを型が保証する。

    組み立てる側は4値を並べて渡すため、緯度と経度の取り違え・minとmaxの入れ替わりが
    数としては通ってしまう。範囲の検証をここに持たせないと、入れ替わった矩形は
    `tiles_covering_bbox`がx,yを昇順へ並べ替えるぶんだけ「それらしいタイル一覧」に化け、
    黙って別の場所を指す。
    """

    min_latitude: float = Field(ge=-90.0, le=90.0)
    min_longitude: float = Field(ge=-180.0, le=180.0)
    max_latitude: float = Field(ge=-90.0, le=90.0)
    max_longitude: float = Field(ge=-180.0, le=180.0)

    @model_validator(mode="after")
    def _check_increasing(self) -> "BoundingBox":
        if self.min_latitude >= self.max_latitude:
            raise ValueError(
                f"緯度はmin < maxが必要です: min={self.min_latitude} max={self.max_latitude}"
            )
        if self.min_longitude >= self.max_longitude:
            raise ValueError(
                f"経度はmin < maxが必要です: min={self.min_longitude} max={self.max_longitude}"
            )
        return self


def bbox_covering_points(points: Sequence[LatLon], margin_km: float) -> BoundingBox:
    """複数地点すべてを覆う外接矩形に、`margin_km`の余裕を足したもの。経度方向の余裕は
    地点の平均緯度で度へ換算する。"""
    center_lat = sum(p.latitude for p in points) / len(points)
    lat_margin_deg = margin_km / KM_PER_DEGREE_LATITUDE
    lon_margin_deg = margin_km / km_per_degree_longitude(center_lat)
    return BoundingBox(
        min_latitude=min(p.latitude for p in points) - lat_margin_deg,
        max_latitude=max(p.latitude for p in points) + lat_margin_deg,
        min_longitude=min(p.longitude for p in points) - lon_margin_deg,
        max_longitude=max(p.longitude for p in points) + lon_margin_deg,
    )


def parse_bbox(text: str) -> BoundingBox:
    """CLIの--bbox（"min_lat,min_lon,max_lat,max_lon"）をBoundingBoxへ変換する。

    緯度経度の順序はCLI間で揃える。値そのものの妥当性は`BoundingBox`が見る。
    """
    parts = [float(p) for p in text.split(",")]
    if len(parts) != 4:
        raise ValueError("--bboxは min_lat,min_lon,max_lat,max_lon の4値が必要です")
    min_lat, min_lon, max_lat, max_lon = parts
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


#: Web Mercator（EPSG:3857）が世界を写す正方形の一辺の半分（m）。
WEB_MERCATOR_HALF_M = 20037508.342789244


def tile_bounds_3857(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """XYZタイルが覆う範囲（Web Mercatorのメートル、west/south/east/north）。"""
    size = 2 * WEB_MERCATOR_HALF_M / (2**z)
    west = -WEB_MERCATOR_HALF_M + x * size
    north = WEB_MERCATOR_HALF_M - y * size
    return west, north - size, west + size, north


# Web Mercatorで表現できる緯度の限界。極ではmath.tan(lat)と1/math.cos(lat)が打ち消し合い、
# _lonlat_to_tile_indexのmath.logが非正の値を受けてmath domain errorになる。
# BoundingBoxが許す±90度まではこの限界の外側にあるため、クランプしてから使う。
_MAX_MERCATOR_LATITUDE = 85.05112878


def _lonlat_to_tile_index(lon: float, lat: float, z: int) -> tuple[int, int]:
    """緯度経度からそれを含むXYZタイルのx,yを求める（tile_bounds_lonlatの逆関数）。"""
    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    clamped_lat = max(-_MAX_MERCATOR_LATITUDE, min(lat, _MAX_MERCATOR_LATITUDE))
    lat_rad = math.radians(clamped_lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def tile_position_sql(lon: str, lat: str, zoom: str) -> tuple[str, str]:
    """`_lonlat_to_tile_index`と同じ式をSQLで書いたもの。経度・緯度の式`lon`・`lat`と
    ズームの式`zoom`から、タイル座標を小数のまま返す`(x, y)`の式（整数部がタイルの番号、
    小数部がタイルの中の位置）。緯度は丸めないため、Web Mercatorの限界の外を渡さないこと。"""
    scale = f"(2::double precision ^ {zoom})"
    x = f"({lon} + 180.0) / 360.0 * {scale}"
    y = f"(1.0 - ln(tan(radians({lat})) + 1.0 / cos(radians({lat}))) / pi()) / 2.0 * {scale}"
    return x, y


def tiles_covering_bbox(bbox: BoundingBox, z: int) -> list[tuple[int, int]]:
    """bboxを覆うXYZタイル群の(x, y)一覧を返す。

    XYZタイルはyが北から南へ増加する（緯度と逆向き）ため、北西端と南東端のタイル座標から
    x,yそれぞれの範囲を求める。bboxの東端・南端がタイルの境目ちょうどに乗るときは、境目の
    東・南の隣のタイルも含む（境目上の点を東・南のタイルに属するとみなすため。覆い漏れの無い側へ
    倒れ、余分に1列・1行を含むだけ）。
    """
    n = 2**z
    x_start, y_start = _lonlat_to_tile_index(bbox.min_longitude, bbox.max_latitude, z)
    x_end, y_end = _lonlat_to_tile_index(bbox.max_longitude, bbox.min_latitude, z)
    x_start, x_end = sorted((max(0, min(x_start, n - 1)), max(0, min(x_end, n - 1))))
    y_start, y_end = sorted((max(0, min(y_start, n - 1)), max(0, min(y_end, n - 1))))
    return [(x, y) for x in range(x_start, x_end + 1) for y in range(y_start, y_end + 1)]
