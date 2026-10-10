"""地理院の標高タイルを手元へ写して置く場所。

**取得と取込を分ける。**取込のトランザクションの中でHTTPを叩くと、1本の長い
トランザクションが外部の一時的な失敗ひとつで全部やり直しになる。取得を別にすれば、
再実行は欠けた分だけで済む。

本文を解釈せずにそのまま置く。取得側は中身について何も決めなくて済み、どう読むかは取込の側が持つ。

**PNG形式を取る。**配信元のテキスト形式は更新が止まっており（https://maps.gsi.go.jp/development/ichiran.html
の備考）、新しい測量はPNG形式にだけ入る。置き場と区域外の印は配信元の名前（`dem5a_png`等）のディレクトリに
置く——形式ごとに配る範囲が違い、別の形式で置いたタイルや印を読み違えないように。

**タイルのファイルの更新時刻は、配信元での最終更新（`Last-Modified`）にする。**取込がそれを読んで記録する。
置き場を別の場所へ写すときは更新時刻を保つ——保たないと、写した時刻が配信元の時刻として記録される。

**製品ごとに置く。**配信元は製品ごとに整備範囲が違い、同じタイル座標に複数の製品が値を
持つ。どれを採るかは画素ごとに派生が決めるので、ここでは返ってきたものを全部持つ。

**区域外は製品ごとに印を置く。**その製品が持たないタイルは恒久的に無いので、`.none`を
置いて次からは叩かない。これが無いと、再実行のたびに同じ区域外タイルを取りに行き続ける。
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from app.batch.common import FETCH_PART_SUFFIX

TILE_ROOT = Path(__file__).resolve().parents[2] / "data" / "dem"

TILE_URL = "https://cyberjapandata.gsi.go.jp/xyz/{product}_png/{z}/{x}/{y}.png"

#: 画素ごとに値を採る順。配信元が「最も計測精度の良い標高タイル」から順に参照すると
#: 定める順（DEM5A→DEM5B→DEM5C→DEM10B）。
#: 出典: https://maps.gsi.go.jp/development/hyokochi.html
PRODUCT_PRIORITY = ("dem5a", "dem5b", "dem5c", "dem")

TILE_SUFFIX = ".png"
#: その製品が持たないことの印。
ABSENT_SUFFIX = ".none"


def _directory(product: str) -> str:
    return f"{product}_png"


def tile_path(root: Path, product: str, zoom: int, x: int, y: int) -> Path:
    return root / _directory(product) / str(zoom) / str(x) / f"{y}{TILE_SUFFIX}"


def absent_path(root: Path, product: str, zoom: int, x: int, y: int) -> Path:
    return root / "_absent" / _directory(product) / str(zoom) / str(x) / f"{y}{ABSENT_SUFFIX}"


def is_stored(root: Path, product: str, zoom: int, x: int, y: int) -> bool:
    return tile_path(root, product, zoom, x, y).exists()


def is_absent(root: Path, product: str, zoom: int, x: int, y: int) -> bool:
    return absent_path(root, product, zoom, x, y).exists()


def read_tile(root: Path, product: str, zoom: int, x: int, y: int) -> bytes:
    return tile_path(root, product, zoom, x, y).read_bytes()


def tile_modified(root: Path, product: str, zoom: int, x: int, y: int) -> datetime:
    """そのタイルの配信元での最終更新。"""
    mtime = tile_path(root, product, zoom, x, y).stat().st_mtime
    return datetime.fromtimestamp(mtime, timezone.utc)


def write_tile(root: Path, product: str, zoom: int, x: int, y: int, content: bytes,
               modified: datetime) -> None:
    """一時ファイルへ書いてから移す。半端なファイルが「取得済み」に見えないように。"""
    path = tile_path(root, product, zoom, x, y)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + FETCH_PART_SUFFIX)
    temporary.write_bytes(content)
    stamp = modified.timestamp()
    os.utime(temporary, (stamp, stamp))
    temporary.replace(path)


def mark_absent(root: Path, product: str, zoom: int, x: int, y: int) -> None:
    path = absent_path(root, product, zoom, x, y)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
