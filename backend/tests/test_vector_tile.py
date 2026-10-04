"""`infrastructure/vector_tile.py`——フィーチャを持たないMVTの生成。

ここで見ないもの:
- どの状況で空タイルを返すか（カバレッジ外・DB障害・未接続） → `test_region_service.py`
- 実データのタイルを組み立てるSQL → `test_road_graph_repository.py`・`test_point_tiles.py`
- レイヤー名どうしが重ならないこと → `test_point_tile_layers.py`
"""

import mapbox_vector_tile

from app.infrastructure.vector_tile import encode_empty_tile


def test_an_empty_tile_still_declares_its_layer():
    """レイヤーごと消えたタイルを返すと、クライアントはそのsource-layerを見失い、
    カバレッジ外へ出た時点で「空」ではなく「壊れたタイル」を受け取る。
    """
    decoded = mapbox_vector_tile.decode(encode_empty_tile("some_layer"))

    assert list(decoded) == ["some_layer"]
    assert decoded["some_layer"]["features"] == []
