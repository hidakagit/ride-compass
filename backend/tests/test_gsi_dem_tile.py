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


def test_欠測を含む1枚を画素の順に詰める():
    """配信元と同じ形（256行×256列、末尾に改行）の1枚。先頭の行と対角線が欠測。"""
    size = 256

    def expected(r: int, c: int) -> int | None:
        if r == 0 or r == c:
            return None
        return (r * size + c) * 7 - 50_000  # 0.01m単位。負の値と富士山を超える値を含む

    def cell(r: int, c: int) -> str:
        v = expected(r, c)
        if v is None:
            return "e"
        sign = "-" if v < 0 else ""
        return f"{sign}{abs(v) // 100}.{abs(v) % 100:02d}"

    text = "".join(",".join(cell(r, c) for c in range(size)) + "\n" for r in range(size))

    payload, missing = _pack(text)

    want = [expected(r, c) for r in range(size) for c in range(size)]
    assert _unpack(payload) == [NODATA if v is None else v for v in want]
    assert missing == size + size - 1
