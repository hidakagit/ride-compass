"""`infrastructure/vector_tile.py`——フィーチャを持たないMVTの生成。

ここで見ないもの:
- どの状況で空タイルを返すか（カバレッジ外・DB障害・未接続） → `test_region_service.py`・
  `test_accident_service.py`
- 実データのタイルを組み立てるSQL → `test_road_graph_repository.py`

**母集団はモジュールから導く。** 空タイルの生成関数はレイヤーが増えるたびに増えるため、
名指しで並べると次の1本が検査から漏れる。
"""

import mapbox_vector_tile

from app.infrastructure import vector_tile

ENCODERS = [obj for name, obj in vars(vector_tile).items() if name.startswith("encode_empty_")]


def _single_layer(encoded: bytes) -> tuple[str, dict]:
    decoded = mapbox_vector_tile.decode(encoded)
    assert len(decoded) == 1
    return next(iter(decoded.items()))


def test_an_empty_tile_still_declares_its_layer():
    """レイヤーごと消えたタイルを返すと、クライアントはそのsource-layerを見失い、
    カバレッジ外へ出た時点で「空」ではなく「壊れたタイル」を受け取る。
    """
    assert ENCODERS

    for encode in ENCODERS:
        name, layer = _single_layer(encode())
        assert name
        assert layer["features"] == []


def test_the_empty_tiles_do_not_share_a_layer_name():
    """同じ名前を名乗ると、片方の配信で実データのタイルと空タイルのsource-layerが食い違う。"""
    names = [_single_layer(encode())[0] for encode in ENCODERS]

    assert len(set(names)) == len(names)
