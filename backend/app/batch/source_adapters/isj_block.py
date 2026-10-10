"""国土交通省の街区レベル位置参照情報（街区符号・地番ごとの代表点）のアダプタ。

**外部の形を読んで1件ずつ返すことだけ**を行う。地番を住所の区画へ結ぶ・住居表示の区域の行をアドレス・ベース・レジストリに
譲るのは派生の段（`batch/derive_addresses.py`）である。

**配信元は叩かない。** 取りに行くのは`scripts/fetch_isj_blocks.py`の仕事で、ここは手元の配布の zip（都道府県ごと。中に
Shift_JIS の CSV が1つと説明の HTML・XML）を読む。読む都道府県は、住所の生データと同じく取込の範囲に掛かる都道府県
（`source_adapters/estat_small_area.py: range_prefectures`。ABR の市区町村の代表点から決める）。

列は配布のまま（都道府県名・市区町村名・大字・丁目名・小字・通称名・街区符号・地番・緯度・経度・住居表示フラグ・
代表フラグ・更新前履歴フラグ・更新後履歴フラグ等）を全部`attrs`へ入れる。意味は配布の zip の中の説明（`<版>.html`）が持つ。
落とすのは次の行で、鍵は都道府県名から街区符号・地番までの名前をつないだもの。
- 代表フラグが 1 でない行（1つの街区符号・地番が複数の点を持つときの、代表でない点）
- 更新後履歴フラグが 3（削除）の行
- 点が取込の範囲（`target.bbox`）の外の行（都道府県の全部を入れると、範囲の外の地番で生データが膨らむ）

緯度・経度は日本測地系2011（EPSG:6668）で、ABR と同じく EPSG の変換で 4326 へ移す。
"""

import csv
import io
import zipfile
from collections.abc import AsyncIterator, Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import shapely
from shapely.geometry import Point

from app.batch.ingest import AdapterInputs, SourceRecord, file_origin, register_adapter
from app.batch.source_adapters.abr import wgs84_transformer
from app.batch.source_adapters.estat_small_area import range_inputs, range_prefectures
from app.batch.source_profile import SourceProfile, SourceSpec

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "isj"

#: 配布元の取得の口（位置参照情報ダウンロードサービス。都道府県コード2桁に`000`をつないだ名前）。
DOWNLOAD_URL = "https://nlftp.mlit.go.jp/isj/dls/data/{version}/{prefecture}000-{version}.zip"
_SOURCE_SRID = "EPSG:6668"
_ENCODING = "cp932"
#: 鍵にする列（都道府県名から街区符号・地番まで）。
_KEY_COLUMNS = ("都道府県名", "市区町村名", "大字・丁目名", "小字・通称名", "街区符号・地番")
#: 更新後履歴フラグの「削除」。
_DELETED = "3"


@dataclass(frozen=True)
class IsjBlockRows:
    """`isj_block`の`rows`。"""

    #: 配布の版（例: `24.0a`）。配布元の置き場の名前に使われる。
    version: str


def archive_path(version: str, prefecture: str) -> Path:
    """取り出した都道府県の配布の置き場。取得（`scripts/fetch_isj_blocks.py`）と取込で同じ導き方を使う。"""
    return DATA_DIR / version / f"{prefecture}000-{version}.zip"


def read_rows(path: Path) -> Generator[dict[str, str]]:
    """配布の zip の中の CSV（1つ）を、列の名前 → 値の行で流す。"""
    with zipfile.ZipFile(path) as archive:
        [member] = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        with archive.open(member) as raw:
            yield from csv.DictReader(io.TextIOWrapper(raw, encoding=_ENCODING, newline=""))


def _paths(rows: IsjBlockRows, prefectures: list[str]) -> list[Path]:
    paths = [archive_path(rows.version, code) for code in prefectures]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"街区レベル位置参照情報がありません: {missing}（scripts/fetch_isj_blocks.py が写す）")
    return paths


def isj_block_inputs(spec: SourceSpec, profile: SourceProfile) -> AdapterInputs:
    return range_inputs(profile, _paths(spec.rows, range_prefectures(profile)))


@register_adapter("isj_block", rows=IsjBlockRows, inputs=isj_block_inputs)
async def read_isj_blocks(spec: SourceSpec, profile: SourceProfile,
                          origin: dict[str, Any]) -> AsyncIterator[SourceRecord]:
    rows: IsjBlockRows = spec.rows
    prefectures = range_prefectures(profile)
    paths = _paths(rows, prefectures)
    origin.update({"version": rows.version, "prefectures": prefectures, "files": [file_origin(path) for path in paths]})
    transformer = wgs84_transformer(_SOURCE_SRID)
    seen: set[str] = set()
    for path in paths:
        for row in read_rows(path):
            if row["代表フラグ"] != "1" or row["更新後履歴フラグ"] == _DELETED:
                continue
            lon, lat = transformer.transform(float(row["経度"]), float(row["緯度"]))
            key = "|".join(row[column] for column in _KEY_COLUMNS)
            if not profile.target.contains(lat, lon) or key in seen:
                continue
            seen.add(key)
            yield SourceRecord(natural_key=key, geom_wkb=shapely.to_wkb(Point(lon, lat)), attrs=row)
