"""地理院の標高タイル（PNG形式）を`source_features`の形へ詰める部分の検証。

入口は`pack_elevations`。見るのは、欠測・負の値・int16に収まらない値を含む1枚が、0.01m単位の値のまま画素の順に詰まること。
入力のPNGは配信元の仕様から作る（`tests/source_ingest.py: gsi_dem_png`）。

ここで見ないもの:
- 置き場のタイルを読んで製品×タイル1枚を1行にする取込（`read_gsi_dem_tiles`）と、詰めた値が画素ごとに
  採られること → 本物の取込を通す`test_derive_elevation.py`
"""

import struct

from app.batch.source_adapters.gsi_dem_tile import NODATA, pack_elevations
from tests.source_ingest import gsi_dem_png


def _unpack(payload: bytes) -> list[int]:
    return list(struct.unpack(f"<{len(payload) // 4}i", payload))


def test_欠測を含む1枚を画素の順に詰める():
    """配信元と同じ大きさ（256×256）の1枚。先頭の行と対角線が欠測。"""
    size = 256

    def expected(r: int, c: int) -> int | None:
        if r == 0 or r == c:
            return None
        return (r * size + c) * 7 - 50_000  # 0.01m単位。負の値と富士山を超える値を含む

    png = gsi_dem_png([[None if (v := expected(r, c)) is None else v / 100 for c in range(size)]
                       for r in range(size)])

    payload, missing = pack_elevations(png)

    want = [expected(r, c) for r in range(size) for c in range(size)]
    assert _unpack(payload) == [NODATA if v is None else v for v in want]
    assert missing == size + size - 1
