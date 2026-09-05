import mapbox_vector_tile

# PostGIS側生成（road_graph_repository.py: _ROAD_SURFACE_TILE_MVT_SQL）と同じ契約の定数。
# Python側ではジオメトリエンコード処理を行わないが、この2定数はPostGIS側のST_AsMVT
# 呼び出しと空タイル生成の両方で共有し続ける（レイヤー名・extentの手動同期を避けるため）。
TILE_EXTENT = 4096
ROAD_SURFACE_LAYER_NAME = "road_surface"

# 外部静的データソース T50（警察庁事故データ）のMVTレイヤー名。road_surfaceと同じ
# extentを共有する（地域レイヤー共通の契約、accident_repository.py参照）。
ACCIDENT_LAYER_NAME = "accidents"

# 停止要因POI（osm_raw_pois）を表示するタイルのレイヤー名。road_surfaceとは別の
# ベクタソース（region_service.get_poi_tile、road_graph_repository.py:
# _POI_TILE_MVT_SQL参照）。
STOP_POI_LAYER_NAME = "stop_poi"


def encode_empty_road_surface_tile() -> bytes:
    """道路フィーチャを持たない空のMVTを返す（カバレッジ外・DB障害・repository未接続時）。"""
    return mapbox_vector_tile.encode(
        [{"name": ROAD_SURFACE_LAYER_NAME, "features": []}],
        default_options={"y_coord_down": True, "extents": TILE_EXTENT},
    )


def encode_empty_accident_tile() -> bytes:
    """事故フィーチャを持たない空のMVTを返す（DB障害・repository未接続時）。"""
    return mapbox_vector_tile.encode(
        [{"name": ACCIDENT_LAYER_NAME, "features": []}],
        default_options={"y_coord_down": True, "extents": TILE_EXTENT},
    )


def encode_empty_poi_tile() -> bytes:
    """停止要因POIを持たない空のMVTを返す（カバレッジ外・DB障害・repository未接続時。
    encode_empty_road_surface_tileと同じ理由）。"""
    return mapbox_vector_tile.encode(
        [{"name": STOP_POI_LAYER_NAME, "features": []}],
        default_options={"y_coord_down": True, "extents": TILE_EXTENT},
    )
