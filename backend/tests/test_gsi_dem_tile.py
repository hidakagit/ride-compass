"""地理院の標高タイルを`source_features`の形へ詰める部分の検証。

配信元の仕様（https://maps.gsi.go.jp/development/demtile.html）:
- 「標高値が存在しない画素には「e」の文字が格納されている。」
- 「標高データは小数点第二位までデータとして入っている（単位はm）。」

入口は`pack_elevations`。見るのは、欠測の印・負の値・int16に収まらない値を含む1枚が画素の順に詰まること。

ここで見ないもの:
- 置き場のタイルを読んで製品×タイル1枚を1行にする取込（`read_gsi_dem_tiles`）と、詰めた値が画素ごとに
  採られること → 本物の取込を通す`test_derive_elevation.py`
"""

import struct

from app.batch.source_adapters.gsi_dem_tile import NODATA, pack_elevations


def _unpack(payload: bytes) -> list[int]:
    return list(struct.unpack(f"<{len(payload) // 4}i", payload))


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

    payload, missing = pack_elevations(text)

    want = [expected(r, c) for r in range(size) for c in range(size)]
    assert _unpack(payload) == [NODATA if v is None else v for v in want]
    assert missing == size + size - 1
