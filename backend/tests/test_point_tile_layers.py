"""`infrastructure/point_tile_layers.py`——点のレイヤーの宣言と、そこから組み立てるもの。

ここで見ないもの:
- 焼き込むSQLが出す点 → `test_point_tiles.py`
- 配信（キャッシュ・空タイル・未知のレイヤーの404） → `test_region_service.py`・`test_region_routes.py`
- 世代の文字列の組み立て → `test_derived_data_revision_service.py`
"""

import dataclasses

from sqlalchemy import text

from app.domain.material_catalog import PRIMARY_ATTRIBUTES
from app.infrastructure.point_tile_layers import POINT_TILE_LAYERS
from app.infrastructure.vector_tile import ROAD_SURFACE_LAYER_NAME
from app.services.tile_version_service import TILE_SHAPES


def test_every_point_attribute_on_the_map_is_served_by_a_declared_layer():
    """地図に点として出す一次属性が指す系統が宣言に無いと、画面はその点のタイルを要求できない。"""
    kinds = {attr.tile_kind for attr in PRIMARY_ATTRIBUTES if attr.geometry == "point" and attr.tile_kind is not None}

    assert kinds
    assert kinds <= set(POINT_TILE_LAYERS)


def test_each_layers_generation_follows_only_its_own_sql_and_source_layer():
    """世代はレイヤーごとに独立している。1つのSQLを変えて作り直すとき、他のレイヤーのキャッシュを捨てない。
    source-layer名を変えたタイルを古い鍵で配ると、画面が新しい名前のレイヤーを見つけられない。"""
    assert len(POINT_TILE_LAYERS) >= 2
    for name, layer in POINT_TILE_LAYERS.items():
        assert TILE_SHAPES[name] == layer.shape
        assert dataclasses.replace(layer, sql=text(f"{layer.sql.text} -- changed")).shape != layer.shape
        assert dataclasses.replace(layer, source_layer=f"{layer.source_layer}_renamed").shape != layer.shape


def test_layers_do_not_share_a_source_layer_name():
    """同じ名前を名乗ると、画面がタイルの中のレイヤーを取り違える。"""
    names = [ROAD_SURFACE_LAYER_NAME, *(layer.source_layer for layer in POINT_TILE_LAYERS.values())]

    assert len(set(names)) == len(names)
