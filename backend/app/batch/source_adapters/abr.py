"""アドレス・ベース・レジストリ（ABR、デジタル庁）の都道府県・市区町村・町字のアダプタ。

**外部の形を読んで1件ずつ返すことだけ**を行う。区画の木にする・範囲で選ぶ・検索の鍵を作るのは派生の段
（`batch/derive_addresses.py`）で、ここは代表点の無い行を落とすだけである。

**配信元は叩かない。** 取りに行くのは`scripts/fetch_abr.py`の仕事で、ここは手元の配布の zip（中に CSV が1つ）を読む。

1回の取込に3種の行を入れる。テキストの行と位置参照拡張（代表点）の行を同じ鍵で1つにし、両方の列を全部`attrs`へ入れる
（同じ名前の列はテキストの値）。
- 都道府県（`mt_pref` と `mt_pref_pos`）・市区町村（`mt_city` と `mt_city_pos`。政令市の区を含む）: 鍵は全国地方公共団体コード
- 町字（`mt_town_fullset` と `mt_town_pos`）: 鍵は`<全国地方公共団体コード>:<町字ID>`。町字の位置参照拡張は都道府県ごとの
  ファイルで、取込の範囲（`target.bbox`）に掛かる都道府県（`prefectures_in_range`）のものだけを読む。同じ町字が住居表示の
  実施・未実施で2行ずつある（`rsdt_addr_flg`）ものは1行にする——テキストは先の行、代表点は代表点を持つ行のうち
  `rsdt_addr_flg`の小さいほう（2行のテキストと位置の`rsdt_addr_flg`は揃っていないことがある）

落とすのは代表点の無い行（小字のほとんど。生データの位置が空にできない）。廃止の日のある行・区画にしない町字区分の行は
落とさない（派生の段が選ぶ）。

代表点の座標系は日本測地系2000（EPSG:4612）と2011（EPSG:6668）が混ざり（列`rep_srid`）、どちらも EPSG の変換で 4326 へ移す。
"""

import csv
import io
import zipfile
from collections.abc import AsyncIterator, Generator, Iterable, Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import pyproj
import shapely
from shapely.geometry import Point

from app.batch.ingest import AdapterInputs, SourceRecord, file_origin, register_adapter
from app.batch.source_profile import SourceProfile, SourceSpec

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "abr"

#: 配布の置き場。全国の1ファイルずつのもの（キーはファイルの名前の頭）。
NATIONWIDE_ARCHIVES = ("mt_pref_all", "mt_pref_pos_all", "mt_city_all", "mt_city_pos_all", "mt_town_fullset_all")
#: 配布元の URL の形。全国の1ファイルは`<種類>/<名前>.csv.zip`、町字の位置参照拡張は都道府県ごと。
BASE_URL = "https://data.address-br.digital.go.jp"


@dataclass(frozen=True)
class AbrRows:
    """`abr`の`rows`。"""

    #: 取った日（例: `2026-10-09`）。配布元は版を持たず今の全件だけを置くので、取った日ごとに置き場を分ける。
    snapshot: str


def archive_name(stem: str) -> str:
    return f"{stem}.csv.zip"


def town_position_stem(prefecture: str) -> str:
    """町字の位置参照拡張の都道府県ごとのファイルの名前の頭。`prefecture`は都道府県コード（2桁）。"""
    return f"mt_town_pos_pref{prefecture}"


def archive_url(stem: str) -> str:
    """配布元の URL。全国の1ファイルは`mt_pref/mt_pref_all.csv.zip`の形、都道府県ごとは`mt_town_pos/pref/…`。"""
    if stem.startswith("mt_town_pos_pref"):
        return f"{BASE_URL}/mt_town_pos/pref/{archive_name(stem)}"
    return f"{BASE_URL}/{stem.removesuffix('_all')}/{archive_name(stem)}"


def archive_path(snapshot: str, stem: str) -> Path:
    """取り出したファイルの置き場。取得（`scripts/fetch_abr.py`）と取込で同じ導き方を使う。"""
    return DATA_DIR / snapshot / archive_name(stem)


def read_rows(path: Path) -> Generator[dict[str, str]]:
    """配布の zip の中の CSV（1つ）を、列の名前 → 値の行で流す。"""
    with zipfile.ZipFile(path) as archive:
        [member] = archive.namelist()
        with archive.open(member) as raw:
            yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))


def _has_point(row: dict[str, str]) -> bool:
    return bool(row.get("rep_lon")) and bool(row.get("rep_lat"))


def prefectures_in_range(city_positions: Iterable[dict[str, str]],
                         bbox: tuple[float, float, float, float]) -> list[str]:
    """取込の範囲に掛かる都道府県のコード（2桁）。範囲の中に代表点を持つ市区町村（区を含む）のある都道府県。

    範囲が都道府県の端だけに掛かり、その中に市区町村の代表点が1つも無い都道府県は入らない。
    """
    min_lat, min_lon, max_lat, max_lon = bbox
    return sorted({
        row["lg_code"][:2] for row in city_positions
        if _has_point(row) and min_lat <= float(row["rep_lat"]) <= max_lat
        and min_lon <= float(row["rep_lon"]) <= max_lon})


@cache
def _to_wgs84(srid: str) -> pyproj.Transformer:
    return pyproj.Transformer.from_crs(srid, "EPSG:4326", always_xy=True)


def _point_wkb(row: dict[str, str]) -> bytes:
    lon, lat = _to_wgs84(row["rep_srid"]).transform(float(row["rep_lon"]), float(row["rep_lat"]))
    return shapely.to_wkb(Point(lon, lat))


def _positions(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    """町字の位置参照拡張の、代表点を持つ行（町字ごとに`rsdt_addr_flg`の小さいほう）。"""
    chosen: dict[tuple[str, str], dict[str, str]] = {}
    for row in read_rows(path):
        key = (row["lg_code"], row["machiaza_id"])
        if _has_point(row) and (key not in chosen or row["rsdt_addr_flg"] < chosen[key]["rsdt_addr_flg"]):
            chosen[key] = row
    return chosen


def _require(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"アドレス・ベース・レジストリの配布がありません: {path}（scripts/fetch_abr.py が写す）")
    return path


def _with_positions(texts: Iterable[dict[str, str]], positions: Path) -> Iterator[SourceRecord]:
    """都道府県・市区町村のテキストの行に代表点の行を合わせる。鍵は全国地方公共団体コード。"""
    points = {row["lg_code"]: row for row in read_rows(positions) if _has_point(row)}
    for row in texts:
        position = points.get(row["lg_code"])
        if position is not None:
            yield SourceRecord(natural_key=row["lg_code"], geom_wkb=_point_wkb(position), attrs={**position, **row})


def _archives(rows: AbrRows, profile: SourceProfile) -> tuple[dict[str, Path], dict[str, Path]]:
    """読む配布: 全国の1ファイル（名前の頭 → 場所）と、範囲に掛かる都道府県の町字の位置参照拡張（コード → 場所）。"""
    paths = {stem: _require(archive_path(rows.snapshot, stem)) for stem in NATIONWIDE_ARCHIVES}
    prefectures = prefectures_in_range(read_rows(paths["mt_city_pos_all"]), profile.target.bbox)
    return paths, {code: _require(archive_path(rows.snapshot, town_position_stem(code))) for code in prefectures}


def abr_inputs(spec: SourceSpec, profile: SourceProfile) -> AdapterInputs:
    paths, town_positions = _archives(spec.rows, profile)
    return AdapterInputs(files=(*paths.values(), *town_positions.values()))


@register_adapter("abr", rows=AbrRows, inputs=abr_inputs)
async def read_abr(spec: SourceSpec, profile: SourceProfile, origin: dict[str, Any]) -> AsyncIterator[SourceRecord]:
    rows: AbrRows = spec.rows
    paths, town_positions = _archives(rows, profile)
    prefectures = list(town_positions)
    origin.update({"snapshot": rows.snapshot, "prefectures": prefectures,
                   "files": [file_origin(path) for path in [*paths.values(), *town_positions.values()]]})

    for record in _with_positions(read_rows(paths["mt_pref_all"]), paths["mt_pref_pos_all"]):
        yield record
    for record in _with_positions(read_rows(paths["mt_city_all"]), paths["mt_city_pos_all"]):
        yield record

    # 町字のテキストは全国の1ファイル。位置は都道府県ごとに読み、都道府県が変わるたびに読み替える（配布は
    # 全国地方公共団体コードの順に並ぶので、各都道府県を1回ずつ読む）。
    loaded: tuple[str, dict[tuple[str, str], dict[str, str]]] = ("", {})
    seen: set[tuple[str, str]] = set()
    for row in read_rows(paths["mt_town_fullset_all"]):
        prefecture = row["lg_code"][:2]
        if prefecture not in town_positions:
            continue
        if loaded[0] != prefecture:
            loaded = (prefecture, _positions(town_positions[prefecture]))
        key = (row["lg_code"], row["machiaza_id"])
        position = loaded[1].get(key)
        if position is None or key in seen:
            continue
        seen.add(key)
        yield SourceRecord(natural_key=f"{row['lg_code']}:{row['machiaza_id']}", geom_wkb=_point_wkb(position),
                           attrs={**position, **row})
