import mapbox_vector_tile

# レイヤー名とextentはPostGIS側のST_AsMVT呼び出し（`road_graph_repository.py`・
# `accident_repository.py`のMVT生成SQL）と空タイル生成の両方が共有する。手で揃えると
# 片方だけ変えたときにクライアントがレイヤーを見失う。
TILE_EXTENT = 4096
ROAD_SURFACE_LAYER_NAME = "road_surface"
ACCIDENT_LAYER_NAME = "accidents"
STOP_POI_LAYER_NAME = "stop_poi"


def _encode_empty_tile(layer_name: str) -> bytes:
    return mapbox_vector_tile.encode(
        [{"name": layer_name, "features": []}],
        default_options={"y_coord_down": True, "extents": TILE_EXTENT},
    )


def encode_empty_road_surface_tile() -> bytes:
    """フィーチャを持たない空のMVT（カバレッジ外・DB障害・repository未接続時）。"""
    return _encode_empty_tile(ROAD_SURFACE_LAYER_NAME)


def encode_empty_accident_tile() -> bytes:
    """フィーチャを持たない空のMVT（DB障害・repository未接続時）。"""
    return _encode_empty_tile(ACCIDENT_LAYER_NAME)


def encode_empty_poi_tile() -> bytes:
    """フィーチャを持たない空のMVT（カバレッジ外・DB障害・repository未接続時）。"""
    return _encode_empty_tile(STOP_POI_LAYER_NAME)
