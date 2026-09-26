"""地理院の標高タイルを手元へ写して置く場所。

**取得と取込を分ける。**取込のトランザクションの中でHTTPを叩くと、1本の長い
トランザクションが外部の一時的な失敗ひとつで全部やり直しになる。取得を別にすれば、
再実行は欠けた分だけで済む。

本文を解釈せずにgzipで置く——配信元が返すのは数字を並べたテキストで、そのままでは嵩む。
取得側は中身について何も決めなくて済み、どう読むかは取込の側が持つ。

**製品ごとに置く。**配信元は製品ごとに整備範囲が違い、同じタイル座標に複数の製品が値を
持つ。どれを採るかは画素ごとに派生が決めるので、ここでは返ってきたものを全部持つ。

**区域外は製品ごとに印を置く。**その製品が持たないタイルは恒久的に無いので、`.none`を
置いて次からは叩かない。これが無いと、再実行のたびに同じ区域外タイルを取りに行き続ける。
"""

import gzip
from pathlib import Path

TILE_ROOT = Path(__file__).resolve().parents[2] / "data" / "dem"

TILE_URL = "https://cyberjapandata.gsi.go.jp/xyz/{product}/{z}/{x}/{y}.txt"

#: 画素ごとに値を採る順。配信元が「最も計測精度の良い標高タイル」から順に参照すると
#: 定める順（DEM5A→DEM5B→DEM5C→DEM10B）。
#: 出典: https://maps.gsi.go.jp/development/hyokochi.html
PRODUCT_PRIORITY = ("dem5a", "dem5b", "dem5c", "dem")

TILE_SUFFIX = ".txt.gz"
#: その製品が持たないことの印。
ABSENT_SUFFIX = ".none"


def tile_path(root: Path, product: str, zoom: int, x: int, y: int) -> Path:
    return root / product / str(zoom) / str(x) / f"{y}{TILE_SUFFIX}"


def absent_path(root: Path, product: str, zoom: int, x: int, y: int) -> Path:
    return root / "_absent" / product / str(zoom) / str(x) / f"{y}{ABSENT_SUFFIX}"


def is_stored(root: Path, product: str, zoom: int, x: int, y: int) -> bool:
    return tile_path(root, product, zoom, x, y).exists()


def is_absent(root: Path, product: str, zoom: int, x: int, y: int) -> bool:
    return absent_path(root, product, zoom, x, y).exists()


def read_tile(root: Path, product: str, zoom: int, x: int, y: int) -> str:
    return gzip.decompress(tile_path(root, product, zoom, x, y).read_bytes()).decode("utf-8")


def write_tile(root: Path, product: str, zoom: int, x: int, y: int, text: str) -> None:
    """一時ファイルへ書いてから移す。半端なファイルが「取得済み」に見えないように。"""
    path = tile_path(root, product, zoom, x, y)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_bytes(gzip.compress(text.encode("utf-8"), 6))
    temporary.replace(path)


def mark_absent(root: Path, product: str, zoom: int, x: int, y: int) -> None:
    path = absent_path(root, product, zoom, x, y)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
