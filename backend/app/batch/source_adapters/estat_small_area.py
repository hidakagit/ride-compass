"""e-Stat の小地域（国勢調査の町丁・字等）の境界のアダプタ。

**外部の形を読んで1件ずつ返すことだけ**を行う。境界を住所の区画へ結ぶのは派生の段（`batch/derive_addresses.py`）である。

**配信元は叩かない。** 取りに行くのは`scripts/fetch_estat_small_areas.py`の仕事で、ここは手元の配布の zip（都道府県ごとの
Shapefile。座標は日本測地系2011（EPSG:6668）の経緯度、dbf は CP932）を読む。読む都道府県は、住所の生データと同じく
取込の範囲に掛かる都道府県（`source_adapters/abr.py: prefectures_in_range`。ABR の市区町村の代表点から決める）。

1つの小地域が離れた島・飛び地で何枚かの多角形に分かれて入っているので、小地域のコード（都道府県2桁＋市区町村3桁＋
町丁・字等6桁）ごとに1つの多角形にまとめ、それを鍵にする（配布の`KEY_CODE`は名前の無い小地域で桁が欠ける）。属性は
最も広い1枚（`AREA_MAX_F`の印）の dbf の列を全部`attrs`へ入れる。落とすのは通常の小地域（`HCODE` 8101）でない行
（水面の 8154 等）。
"""

import io
import zipfile
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pyproj
import shapefile
import shapely
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from app.batch.ingest import SourceRecord, file_origin, register_adapter
from app.batch.source_adapters.abr import archive_path, prefectures_in_range, read_rows
from app.batch.source_profile import SourceProfile, SourceSpec

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "estat"

#: 通常の小地域の境界の区分（`HCODE`）。
NORMAL_AREA_HCODE = 8101
#: 配布元の取得の口（統計地理情報システムの境界データ。Shapefile・経緯度・日本測地系2011）。
DOWNLOAD_URL = ("https://www.e-stat.go.jp/gis/statmap-search/data?dlserveyId={survey}&code={prefecture}"
                "&coordSys=1&format=shape&downloadType=5&datum=2011")
_SOURCE_SRID = "EPSG:6668"
_ENCODING = "cp932"
#: 最も広い1枚に付く印（`AREA_MAX_F`）。
_LARGEST_PART = "M"


@dataclass(frozen=True)
class EstatSmallAreaRows:
    """`estat_small_area`の`rows`。"""

    #: 統計調査の識別子（e-Stat の`dlserveyId`。例: 令和2年国勢調査の小地域の境界は`A002005212020`）。
    survey: str


def boundary_path(survey: str, prefecture: str) -> Path:
    """取り出した都道府県の境界の置き場。取得（`scripts/fetch_estat_small_areas.py`）と取込で同じ導き方を使う。"""
    return DATA_DIR / survey / f"{prefecture}.zip"


def open_shapefile(archive: zipfile.ZipFile) -> shapefile.Reader:
    """配布の zip の中の Shapefile（`.shp`・`.shx`・`.dbf`）を開く。"""
    members = {Path(name).suffix.lower(): name for name in archive.namelist()}
    return shapefile.Reader(shp=io.BytesIO(archive.read(members[".shp"])),
                            shx=io.BytesIO(archive.read(members[".shx"])),
                            dbf=io.BytesIO(archive.read(members[".dbf"])), encoding=_ENCODING)


def abr_snapshot(profile: SourceProfile) -> str:
    """範囲に掛かる都道府県を決めるのに読む、ABR の取った日（プロファイルの`abr`の`rows.snapshot`）。"""
    snapshots = {spec.rows.snapshot for spec in profile.sources if spec.adapter == "abr"}
    if len(snapshots) != 1:
        raise ValueError(f"プロファイルの ABR の取った日が1つに決まらない: {sorted(snapshots)}")
    return snapshots.pop()


def range_prefectures(profile: SourceProfile) -> list[str]:
    """取込の範囲に掛かる都道府県（ABR の市区町村の代表点から決める）。"""
    path = archive_path(abr_snapshot(profile), "mt_city_pos_all")
    if not path.exists():
        raise FileNotFoundError(f"範囲に掛かる都道府県を決める ABR の市区町村の代表点がありません: {path}"
                                "（scripts/fetch_abr.py が写す）")
    return prefectures_in_range(read_rows(path), profile.target.bbox)


def _to_wgs84(geometry: BaseGeometry, transformer: pyproj.Transformer) -> BaseGeometry:
    def move(coordinates: np.ndarray) -> np.ndarray:
        lon, lat = transformer.transform(coordinates[:, 0], coordinates[:, 1])
        return np.column_stack([lon, lat])

    return shapely.transform(geometry, move)


def _read_prefecture(path: Path, transformer: pyproj.Transformer) -> list[SourceRecord]:
    parts: dict[str, list[BaseGeometry]] = defaultdict(list)
    attrs: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(path) as archive:
        reader = open_shapefile(archive)
        for item in reader.iterShapeRecords():
            record = item.record.as_dict()
            if record["HCODE"] != NORMAL_AREA_HCODE:
                continue
            key = f"{record['PREF']}{record['CITY']}{record['S_AREA']}"
            parts[key].append(shape(item.shape.__geo_interface__))
            if key not in attrs or record["AREA_MAX_F"] == _LARGEST_PART:
                attrs[key] = record
    records = []
    for key, polygons in parts.items():
        merged = polygons[0] if len(polygons) == 1 else shapely.union_all(polygons)
        records.append(SourceRecord(natural_key=key, geom_wkb=shapely.to_wkb(_to_wgs84(merged, transformer)),
                                    attrs=attrs[key]))
    return records


@register_adapter("estat_small_area", rows=EstatSmallAreaRows)
async def read_estat_small_areas(spec: SourceSpec, profile: SourceProfile,
                                 origin: dict[str, Any]) -> AsyncIterator[SourceRecord]:
    rows: EstatSmallAreaRows = spec.rows
    prefectures = range_prefectures(profile)
    paths = [boundary_path(rows.survey, code) for code in prefectures]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"e-Stat の小地域の境界がありません: {missing}（scripts/fetch_estat_small_areas.py が写す）")
    origin.update({"survey": rows.survey, "prefectures": prefectures, "files": [file_origin(path) for path in paths]})
    transformer = pyproj.Transformer.from_crs(_SOURCE_SRID, "EPSG:4326", always_xy=True)
    for path in paths:
        for record in _read_prefecture(path, transformer):
            yield record
