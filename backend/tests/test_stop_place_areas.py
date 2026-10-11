"""立ち寄り先の辺り（`stop_places.area`）を、e-Stat の小地域の境界の名前から決める。

入口は取込（`ingest_source`。アダプタ`estat_small_area`は本物で、手元の zip を読む）と派生の段（`derive_stop_places.derive`）。
配布の形の小さな見本（e-Stat の Shapefile の zip と、取り込む都道府県を決める ABR の市区町村の代表点の zip）を置き場に書き、
Overture の地点を取り込んで段を流し、表に入った辺りを見る。

ここで見ないもの:
- 地点の検索の候補に辺りを添えること・置いた位置の辺りの口 → `test_place_search_route.py`
- 配布元から手元へ写す取得（`scripts/fetch_estat_small_areas.py`）→ どのテストも通さない
"""

import csv
import io
import zipfile
from dataclasses import replace

import pytest
import shapefile

from app.batch import derive_stop_places
from app.batch.ingest import ingest_source
from app.batch.source_adapters import abr, estat_small_area
from app.batch.source_profile import Target, load_source_profile
from app.infrastructure.source_models import Source
from tests.source_ingest import ingest_records, point_record

pytestmark = pytest.mark.asyncio(loop_scope="module")

#: 取込の範囲（min_lat, min_lon, max_lat, max_lon）。
BBOX = (35.40, 139.20, 36.10, 140.00)
PROFILE = replace(load_source_profile(None), target=Target(bbox=BBOX))

#: 取り込む都道府県を決める ABR の市区町村の代表点: (コード, 経度, 緯度)。
CITY_POSITIONS = [("131041", 139.70, 35.69), ("111104", 139.69, 35.95)]


def _square(west: float, south: float, east: float, north: float) -> list[list[float]]:
    """四角（Shapefile の外周の向き＝時計回り）。"""
    return [[west, south], [west, north], [east, north], [east, south], [west, south]]


#: 境界: (小地域のコード, 市区町村名, 町丁・字等の名前, 区分, 多角形の外周の並び)。名前は配布の書き方（市区町村名は郡を
#: 含まず、政令市は市と区をつなぐ。丁目は漢数字、大字は「大字」から書く）。
BOUNDARIES = [
    # 西新宿二丁目と三丁目は経度 139.693 の辺を分け合う。
    ("13104002402", "新宿区", "西新宿二丁目", 8101, [_square(139.690, 35.687, 139.693, 35.690)]),
    ("13104002403", "新宿区", "西新宿三丁目", 8101, [_square(139.693, 35.687, 139.696, 35.690)]),
    ("11110000100", "さいたま市岩槻区", "本町", 8101, [_square(139.695, 35.945, 139.705, 35.955)]),
    # 2枚に分かれた大字。名前の無い小地域と経度 139.27 の辺を分け合い、名前の無いほうが鍵が小さい。
    ("13305000101", "日の出町", "大字平井", 8101,
     [_square(139.26, 35.74, 139.27, 35.75), _square(139.30, 35.74, 139.31, 35.75)]),
    ("13305000000", "日の出町", "", 8101, [_square(139.27, 35.74, 139.28, 35.75)]),
    # 水面（通常の小地域でない区分）。
    ("13104002600", "新宿区", "西新宿", 8154, [_square(139.75, 35.75, 139.76, 35.76)]),
]


def _write_city_positions() -> None:
    path = abr.archive_path(PROFILE.source(Source.ABR).rows.snapshot, "mt_city_pos_all")
    text = io.StringIO()
    writer = csv.writer(text, lineterminator="\n")
    writer.writerow(["lg_code", "rep_lon", "rep_lat"])
    writer.writerows(CITY_POSITIONS)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(path.name.removesuffix(".zip"), text.getvalue())


def _write_boundaries() -> None:
    survey = PROFILE.source(Source.ESTAT_SMALL_AREA).rows.survey
    for prefecture in ("11", "13"):
        shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
        with shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYGON, encoding="cp932") as writer:
            for name, kind, size in (("KEY_CODE", "C", 11), ("PREF", "C", 2), ("CITY", "C", 3), ("S_AREA", "C", 6),
                                     ("CITY_NAME", "C", 60), ("S_NAME", "C", 96), ("HCODE", "N", 4),
                                     ("AREA_MAX_F", "C", 1)):
                writer.field(name, kind, size=size)
            for key, city, area, hcode, rings in BOUNDARIES:
                if key[:2] != prefecture:
                    continue
                for index, ring in enumerate(rings):
                    writer.poly([ring])
                    writer.record(key, key[:2], key[2:5], key[5:], city, area, hcode, "M" if index == 0 else "")
        path = estat_small_area.boundary_path(survey, prefecture)
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as archive:
            for suffix, data in ((".shp", shp), (".shx", shx), (".dbf", dbf)):
                archive.writestr(f"r2ka{prefecture}{suffix}", data.getvalue())


@pytest.fixture
def boundary_data(monkeypatch, tmp_path):
    """見本の配布を置き場に書く。"""
    monkeypatch.setattr(abr, "DATA_DIR", tmp_path / "abr")
    monkeypatch.setattr(estat_small_area, "DATA_DIR", tmp_path / "estat")
    _write_city_positions()
    _write_boundaries()


async def _areas(conn, places: dict[str, tuple[float, float]]) -> dict[str, str | None]:
    """境界と地点（鍵 → (経度, 緯度)）を取り込み、立ち寄り先の段を流して、地点ごとの辺りを返す。"""
    await ingest_source(conn, PROFILE, Source.ESTAT_SMALL_AREA)
    await ingest_records("overture_place", [
        point_record(key, lon, lat, {"names": {"primary": f"喫茶{key}"}, "confidence": 0.75,
                                     "brand": {"names": {"primary": None}},
                                     "taxonomy": {"hierarchy": ["food_and_drink", "cafe"]}})
        for key, (lon, lat) in places.items()], conn=conn)
    await derive_stop_places.derive(conn)
    return {row["source_key"]: row["area"] for row in await conn.fetch("SELECT source_key, area FROM stop_places")}


@pytest.mark.usefixtures("boundary_data")
async def test_a_place_inside_a_boundary_has_the_city_and_the_name_of_the_boundary(derive_conn):
    """辺りは境界の市区町村名と町丁・字等の名前を配布の書き方のままつないだもの（都道府県・郡は持たず、政令市は市と区を
    つなぐ）。2枚に分かれた境界は、どちらの1枚の中でも同じ辺り。"""
    areas = await _areas(derive_conn, {
        "chome": (139.6912, 35.6881), "ward": (139.701, 35.951), "oaza": (139.265, 35.745),
        "oaza_second_part": (139.305, 35.745)})

    assert areas == {"chome": "新宿区西新宿二丁目", "ward": "さいたま市岩槻区本町", "oaza": "日の出町大字平井",
                     "oaza_second_part": "日の出町大字平井"}


@pytest.mark.usefixtures("boundary_data")
async def test_a_place_on_the_edge_of_two_boundaries_has_the_named_one_of_the_smaller_key(derive_conn):
    """辺の上の点は、名前を持つ境界のうち鍵の小さいほう（名前の無い境界は鍵が小さくても採らない）。"""
    areas = await _areas(derive_conn, {"chome_edge": (139.693, 35.6885), "unnamed_edge": (139.27, 35.745)})

    assert areas == {"chome_edge": "新宿区西新宿二丁目", "unnamed_edge": "日の出町大字平井"}


@pytest.mark.usefixtures("boundary_data")
async def test_a_place_outside_the_named_boundaries_has_no_area(derive_conn):
    """境界の外（海の上等）・名前の無い境界の中・水面の中は、辺りを持たない。"""
    areas = await _areas(derive_conn, {"sea": (139.80, 35.55), "unnamed": (139.275, 35.745),
                                       "water": (139.755, 35.755)})

    assert areas == {"sea": None, "unnamed": None, "water": None}
