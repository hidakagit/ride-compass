import mapbox_vector_tile

# PostGIS側生成（road_graph_repository.py: _ROAD_SURFACE_TILE_MVT_SQL）と同じ契約の定数。
# 改善計画T22でOverpassフォールバック撤去に伴いPython側のジオメトリエンコード処理は
# 不要になったが、この2定数はPostGIS側のST_AsMVT呼び出しと空タイル生成の両方で
# 共有し続ける（レイヤー名・extentの手動同期を避けるため）。
TILE_EXTENT = 4096
ROAD_SURFACE_LAYER_NAME = "road_surface"


def encode_empty_road_surface_tile() -> bytes:
    """道路フィーチャを持たない空のMVTを返す（カバレッジ外・DB障害・repository未接続時）。"""
    return mapbox_vector_tile.encode(
        [{"name": ROAD_SURFACE_LAYER_NAME, "features": []}],
        default_options={"y_coord_down": True, "extents": TILE_EXTENT},
    )
