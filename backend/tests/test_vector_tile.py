"""`infrastructure/vector_tile.py`——空タイル（`encode_empty_tile`）。

カバレッジ外・DB障害のときに配る空タイルが、何も描かずに、要求されたレイヤーを名乗ること。

ここで見ないもの:
- 共有定数（`TILE_EXTENT`・レイヤー名・路面タイルの列の名前）を焼き込んだタイル → 路面タイルは
  `test_material_values.py`・`test_road_graph_repository_contracts.py`、点のタイルは `test_point_tiles.py`
- 空タイルをいつ配るか → `test_region_service.py`
"""

import mapbox_vector_tile

from app.infrastructure.vector_tile import TILE_EXTENT, encode_empty_tile


def test_an_empty_tile_names_the_requested_layer_and_draws_nothing():
    """空タイルが何かを描くと、取込範囲の外やDB障害のときに、地図へ無いものが出る。"""
    decoded = mapbox_vector_tile.decode(encode_empty_tile("stop_poi"))

    assert list(decoded) == ["stop_poi"]
    assert decoded["stop_poi"]["features"] == []
    assert decoded["stop_poi"]["extent"] == TILE_EXTENT
