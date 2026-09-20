"""地理院の標高タイルを`source_features`の形へ詰める部分の検証。

配信元の仕様（https://maps.gsi.go.jp/development/demtile.html）:
- 「標高値が存在しない画素には「e」の文字が格納されている。」
- 「標高データは小数点第二位までデータとして入っている（単位はm）。」
"""

import struct

from app.batch.source_adapters.gsi_dem_tile import NODATA, SCALE, _pack


def _unpack(payload: bytes) -> list[int]:
    return list(struct.unpack(f"<{len(payload) // 4}i", payload))


def test_小数第二位を落とさない():
    payload, missing = _pack("1.23,45.67")
    assert missing == 0
    assert [v / SCALE for v in _unpack(payload)] == [1.23, 45.67]


def test_富士山の高さを切り詰めない():
    """関東のbboxに富士山（3,776m）が入る。int16では3,276.7mで頭打ちになる。"""
    payload, _ = _pack("3774.81")
    assert _unpack(payload) == [377481]
    assert _unpack(payload)[0] / SCALE == 3774.81


def test_欠測はNODATAで表し件数を返す():
    payload, missing = _pack("1.00,e,e")
    assert missing == 2
    assert _unpack(payload) == [100, NODATA, NODATA]


def test_負の標高を扱える():
    payload, missing = _pack("-4.50")
    assert missing == 0
    assert _unpack(payload)[0] / SCALE == -4.5


def test_行をまたいで並ぶ():
    payload, _ = _pack("1.00,2.00\n3.00,4.00")
    assert [v / SCALE for v in _unpack(payload)] == [1.0, 2.0, 3.0, 4.0]
