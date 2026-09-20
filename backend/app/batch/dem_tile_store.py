"""地理院の標高タイルを手元へ写して置く場所。

**取得と取込を分ける。**取込のトランザクションの中でHTTPを叩くと、関東全域（z15で
約6万枚）では1本の長いトランザクションが外部の一時的な失敗ひとつで全部やり直しになる。
取得を別にすれば、再実行は欠けた分だけで済む。OSMの`.pbf`・土地被覆のGeoTIFFと同じく、
**取込はローカルのファイルを読むだけ**になる。

置き方は配信元のURLをそのまま写す（`{product}/{z}/{x}/{y}.txt.gz`）。本文を解釈せずに
gzipで置く——配信元が返すのは数字を並べたテキストで、そのままでは嵩む。取得側は中身に
ついて何も決めなくて済み、どう読むかは取込の側が持つ。

**区域外は印を置く。**どの製品にも無いタイルは恒久的に無いので、`.none`を置いて
次からは叩かない。これが無いと、再実行のたびに同じ区域外タイルを取りに行き続ける。
"""

import gzip
from pathlib import Path

#: 写したタイルの置き場。他のソースの手元ファイル（`data/pbf`・`data/accidents`等）と
#: 同じ並び。
TILE_ROOT = Path(__file__).resolve().parents[2] / "data" / "dem"

#: 配信元。`{type}`は製品名。
TILE_URL = "https://cyberjapandata.gsi.go.jp/xyz/{product}/{z}/{x}/{y}.txt"

#: 粗い側へ落ちていく順。配信元が細かい製品を全域では持たない。
PRODUCT_PRIORITY = ("dem5a", "dem5b", "dem5c", "dem")

#: 手元に写したタイルの拡張子と、どの製品にも無いことの印。
TILE_SUFFIX = ".txt.gz"
ABSENT_SUFFIX = ".none"


def tile_path(root: Path, product: str, zoom: int, x: int, y: int) -> Path:
    return root / product / str(zoom) / str(x) / f"{y}{TILE_SUFFIX}"


def absent_path(root: Path, zoom: int, x: int, y: int) -> Path:
    """どの製品にも無いことの印。製品を跨ぐ判断なので製品名を含めない。"""
    return root / "_absent" / str(zoom) / str(x) / f"{y}{ABSENT_SUFFIX}"


def stored_product(root: Path, zoom: int, x: int, y: int) -> str | None:
    """手元にあるなら、どの製品で取れたか。無ければNone。"""
    for product in PRODUCT_PRIORITY:
        if tile_path(root, product, zoom, x, y).exists():
            return product
    return None


def is_absent(root: Path, zoom: int, x: int, y: int) -> bool:
    return absent_path(root, zoom, x, y).exists()


def read_tile(root: Path, product: str, zoom: int, x: int, y: int) -> str:
    return gzip.decompress(tile_path(root, product, zoom, x, y).read_bytes()).decode("utf-8")


def write_tile(root: Path, product: str, zoom: int, x: int, y: int, text: str) -> None:
    """一時ファイルへ書いてから移す。半端なファイルが「取得済み」に見えないように。"""
    path = tile_path(root, product, zoom, x, y)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_bytes(gzip.compress(text.encode("utf-8"), 6))
    temporary.replace(path)


def mark_absent(root: Path, zoom: int, x: int, y: int) -> None:
    path = absent_path(root, zoom, x, y)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
