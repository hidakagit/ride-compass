import mapbox_vector_tile

# PostGIS側生成（road_graph_repository.py: _ROAD_SURFACE_TILE_MVT_SQL）と同じ契約の定数。
# 改善計画T22でOverpassフォールバック撤去に伴いPython側のジオメトリエンコード処理は
# 不要になったが、この2定数はPostGIS側のST_AsMVT呼び出しと空タイル生成の両方で
# 共有し続ける（レイヤー名・extentの手動同期を避けるため）。
TILE_EXTENT = 4096
ROAD_SURFACE_LAYER_NAME = "road_surface"

# 外部静的データソース T50（警察庁事故データ）のMVTレイヤー名。road_surfaceと同じ
# extentを共有する（地域レイヤー共通の契約、accident_repository.py参照）。
ACCIDENT_LAYER_NAME = "accidents"

# 改善計画T54（既取込データの可視化漏れ解消）: 停止要因POI（osm_raw_pois）を表示する
# 新規タイルのレイヤー名。road_surfaceとは別のベクタソース（region_service.get_poi_tile）
# （road_graph_repository.py: _POI_TILE_MVT_SQL参照）。
# 交差点密度（road_nodes次数）レイヤーはT54で同じタイルへ焼き込んでいたが、T96で地図の
# 独立可視化レイヤーとしては撤去（道路網を見れば概ね自明という判断、ルーティング材料の
# intersection_weightとしては引き続き`get_intersection_counts`等を使う）。フロント側の
# 参照が無くなったため、T97でバックエンド配信（このレイヤー・INTERSECTION_LAYER_NAME）も
# 削除した。
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
