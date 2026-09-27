import mapbox_vector_tile

# レイヤー名とextentはPostGIS側のST_AsMVT呼び出し（`road_graph_repository.py`・
# `accident_repository.py`のMVT生成SQL）と空タイル生成の両方が共有する。手で揃えると
# 片方だけ変えたときにクライアントがレイヤーを見失う。
TILE_EXTENT = 4096
ROAD_SURFACE_LAYER_NAME = "road_surface"
ACCIDENT_LAYER_NAME = "accidents"
STOP_POI_LAYER_NAME = "stop_poi"

# 路面タイルのフィーチャーが材料の外に持つ列（役割→列名）。材料の列の名前は材料の`tile_property`が持つ。
# 画面は生成物`region-tile-config.json`の`road_surface.properties`から引き、列名を持たない。
# - feature_key: フィーチャーの識別子（区間かway丸ごとの鍵）。画面が地物のidへ昇格させ、配信値の鍵にする
# - way_id: 区間インスペクタが道を引き直すosm_way_id
# - name・ref: 道路名・路線番号（表示専用の生値）
ROAD_FEATURE_PROPERTIES: dict[str, str] = {
    "feature_key": "feature_key",
    "way_id": "osm_way_id",
    "name": "name",
    "ref": "ref",
}


def _encode_empty_tile(layer_name: str) -> bytes:
    return mapbox_vector_tile.encode(
        [{"name": layer_name, "features": []}],
        default_options={"y_coord_down": True, "extents": TILE_EXTENT},
    )


def encode_empty_road_surface_tile() -> bytes:
    """フィーチャを持たない空のMVT（カバレッジ外・DB障害時）。"""
    return _encode_empty_tile(ROAD_SURFACE_LAYER_NAME)


def encode_empty_accident_tile() -> bytes:
    """フィーチャを持たない空のMVT（DB障害時）。"""
    return _encode_empty_tile(ACCIDENT_LAYER_NAME)


def encode_empty_poi_tile() -> bytes:
    """フィーチャを持たない空のMVT（カバレッジ外・DB障害時）。"""
    return _encode_empty_tile(STOP_POI_LAYER_NAME)
