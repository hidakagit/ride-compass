import math

import mapbox_vector_tile

# Web Mercator (EPSG:3857) の座標範囲は赤道換算で ±20037508.34m。
EARTH_RADIUS_M = 6378137.0
MERCATOR_EXTENT_M = math.pi * EARTH_RADIUS_M

TILE_EXTENT = 4096
ROAD_SURFACE_LAYER_NAME = "road_surface"

# Web Mercatorで表現できる緯度の限界（domain/region.pyの_MAX_MERCATOR_LATITUDEと同じ値）。
# lat=-90ちょうどではtan(0)=0でmath.log(0)がValueErrorになる。Overpassのway座標は
# タイル境界でクリップせずそのまま渡るため、極めて稀に異常な入力座標が来た場合の
# クラッシュを避けるためクランプする。
_MAX_MERCATOR_LATITUDE = 85.05112878


def _lonlat_to_mercator(lon: float, lat: float) -> tuple[float, float]:
    clamped_lat = max(-_MAX_MERCATOR_LATITUDE, min(lat, _MAX_MERCATOR_LATITUDE))
    x = lon * MERCATOR_EXTENT_M / 180.0
    y = math.log(math.tan((90.0 + clamped_lat) * math.pi / 360.0)) / (math.pi / 180.0)
    y = y * MERCATOR_EXTENT_M / 180.0
    return x, y


def _tile_bounds_mercator(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    n = 2**z
    tile_size = 2 * MERCATOR_EXTENT_M / n
    min_x = -MERCATOR_EXTENT_M + x * tile_size
    max_x = min_x + tile_size
    max_y = MERCATOR_EXTENT_M - y * tile_size
    min_y = max_y - tile_size
    return min_x, min_y, max_x, max_y


def encode_road_surface_tile(z: int, x: int, y: int, ways: list[dict]) -> bytes:
    """路面way（{"coordinates": [[lat, lon], ...], "surface_good": bool | None,
    "surface": str | None, "highway": str | None}の配列）をz/x/yのMVT（Mapbox Vector Tile）に
    エンコードする。surface/highwayはPostGIS側生成（_ROAD_SURFACE_TILE_MVT_SQL）と同じ契約で、
    値がNone（キー無しも同義）のプロパティはmapbox_vector_tileがfeatureから省略する。

    タイル座標系はMVT仕様通り、原点(0,0)がタイル左上・y軸下向き（標準的な画像ピクセル座標と同じ）。
    Web Mercatorへ投影してからタイルのMercator範囲に対する線形スケールでタイルローカル座標
    （0-TILE_EXTENT）を求める。Overpassの取得範囲がタイル境界を跨ぐwayをそのまま含む
    （クリップしない）ため、タイル範囲をわずかに超える座標が含まれることがあるが、
    MVT仕様上は許容される値であり、MapLibre側の描画時クリップに委ねる。
    """
    min_x, min_y, max_x, max_y = _tile_bounds_mercator(z, x, y)

    def project(lon: float, lat: float) -> tuple[float, float]:
        merc_x, merc_y = _lonlat_to_mercator(lon, lat)
        px = (merc_x - min_x) / (max_x - min_x) * TILE_EXTENT
        py = (max_y - merc_y) / (max_y - min_y) * TILE_EXTENT
        return px, py

    features = []
    for way in ways:
        coordinates = [project(lon, lat) for lat, lon in way["coordinates"]]
        if len(coordinates) < 2:
            continue
        features.append(
            {
                "geometry": {"type": "LineString", "coordinates": coordinates},
                "properties": {
                    "surface_good": way["surface_good"],
                    "surface": way.get("surface"),
                    "highway": way.get("highway"),
                },
            }
        )

    return mapbox_vector_tile.encode(
        [{"name": ROAD_SURFACE_LAYER_NAME, "features": features}],
        default_options={"y_coord_down": True, "extents": TILE_EXTENT},
    )
