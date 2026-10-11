"""住所の区画の表（`address_areas`・`address_search_keys`・`address_blocks`）を、アドレス・ベース・レジストリと
街区レベル位置参照情報の配布の形から作る。

入口は取込（`ingest_source`。アダプタ`abr`・`isj_block`は本物で、手元の zip を読む）と派生の段
（`derive_addresses.derive`）。配布の形の小さな見本（ABR の CSV の zip・位置参照情報の Shift_JIS の CSV の zip）を置き場に
書き、表に入った区画・鍵・街区を見る。範囲は道路の取込の範囲で、見本の道を範囲の宣言つきで取り込んで決める。

ここで見ないもの:
- 配布元から手元へ写す取得（`scripts/fetch_abr.py`・`scripts/fetch_isj_blocks.py`）→ どのテストも通さない
  （網の向こうを読むだけで、範囲に掛かる都道府県の決め方はアダプタと同じ関数を通る）
- 表記の揃え方の1つずつ → `test_address_area.py`
"""

import csv
import io
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from app.batch import derive_addresses
from app.batch.ingest import ingest_source
from app.batch.source_adapters import abr, isj_block
from app.domain.address_area import standardize_address
from app.batch.source_profile import Target, load_source_profile
from app.infrastructure.source_models import Source
from tests.conftest import empty_ingested_tables
from tests.source_ingest import ingest_records, way_record

pytestmark = pytest.mark.asyncio(loop_scope="module")

#: 取込の範囲（min_lat, min_lon, max_lat, max_lon）。
BBOX = (35.40, 139.20, 35.80, 139.80)
PROFILE = replace(load_source_profile(None), target=Target(bbox=BBOX))
SNAPSHOT = PROFILE.source(Source.ABR).rows.snapshot
ISJ_VERSION = PROFILE.source(Source.ISJ_BLOCK).rows.version

# 配布の CSV の見出し（配布のまま）。
PREF_COLUMNS = "lg_code,pref,pref_kana,pref_roma,efct_date,ablt_date,remarks"
POS_COLUMNS = "lg_code,rep_lon,rep_lat,rep_srid,rep_scale,plygn_fname,plygn_kcode,plygn_fmt,plygn_srid,plygn_scale"
CITY_COLUMNS = ("lg_code,pref,pref_kana,pref_roma,county,county_kana,county_roma,city,city_kana,city_roma,"
                "ward,ward_kana,ward_roma,efct_date,ablt_date,remarks")
TOWN_COLUMNS = (
    "lg_code,machiaza_id,machiaza_type,pref,pref_kana,pref_roma,county,county_kana,county_roma,city,city_kana,"
    "city_roma,ward,ward_kana,ward_roma,oaza_cho,oaza_cho_kana,oaza_cho_roma,chome,chome_kana,chome_number,koaza,"
    "koaza_kana,koaza_roma,machiaza_dist,rsdt_addr_flg,rsdt_addr_mtd_code,oaza_cho_aka_flg,koaza_aka_code,"
    "oaza_cho_gsi_uncmn,koaza_gsi_uncmn,status_flg,wake_num_flg,efct_date,ablt_date,src_code,post_code,"
    "oaza_cho_uncmn_reg,oaza_cho_uncmn_mj,oaza_cho_uncmn_type,oaza_cho_uncmn_code,koaza_uncmn_reg,koaza_uncmn_mj,"
    "koaza_uncmn_type,koaza_uncmn_code,alias_oaza,alias_oaza_kana,alias_oaza_roma,alias_koaza,alias_koaza_kana,"
    "alias_koaza_roma,remarks")
TOWN_POS_COLUMNS = ("lg_code,machiaza_id,rsdt_addr_flg,rep_lon,rep_lat,rep_srid,rep_scale,rep_src_code,plygn_fname,"
                    "plygn_kcode,plygn_fmt,plygn_srid,plygn_scale,plygn_src_code,pos_oaza_cho_chome_code,"
                    "pos_data_mnt_year,cns_bnd_s_area_kcode,cns_bnd_year")

BLOCK_COLUMNS = ("lg_code,machiaza_id,blk_id,city,ward,oaza_cho,chome,koaza,machiaza_dist,blk_num,rsdt_addr_flg,"
                 "rsdt_addr_mtd_code,status_flg,efct_date,ablt_date,src_code,remarks")
BLOCK_POS_COLUMNS = ("lg_code,machiaza_id,blk_id,rsdt_addr_flg,rsdt_addr_mtd_code,rep_lon,rep_lat,rep_srid,rep_scale,"
                     "rep_src_code,plygn_fname,plygn_kcode,plygn_fmt,plygn_srid,plygn_scale,plygn_src_code,pos_pref,"
                     "pos_city,pos_oaza_cho_chome,pos_koaza_aka,pos_blk_prc_num,pos_data_mnt_year,rsdt_addr_code_rdbl,"
                     "rsdt_addr_data_mnt_date")
ISJ_COLUMNS = ("都道府県名,市区町村名,大字・丁目名,小字・通称名,街区符号・地番,座標系番号,Ｘ座標,Ｙ座標,緯度,経度,"
               "住居表示フラグ,代表フラグ,更新前履歴フラグ,更新後履歴フラグ")

#: 都道府県: (コード, 名前, 経度, 緯度)。埼玉県の代表点は範囲の外。
PREFECTURES = [("130001", "東京都", 139.69, 35.69), ("140007", "神奈川県", 139.64, 35.45),
               ("110001", "埼玉県", 139.65, 35.86)]
#: 市区町村: (コード, 都道府県, 郡, 市, 区, 経度, 緯度)。川口市の代表点は範囲の外。
CITIES = [
    ("131041", "東京都", "", "新宿区", "", 139.70, 35.69),
    ("133051", "東京都", "西多摩郡", "日の出町", "", 139.26, 35.74),
    ("141003", "神奈川県", "", "横浜市", "", 139.64, 35.44),
    ("141011", "神奈川県", "", "横浜市", "鶴見区", 139.68, 35.51),
    ("112241", "埼玉県", "", "戸田市", "", 139.68, 35.79),
    ("112038", "埼玉県", "", "川口市", "", 139.72, 35.81),
]
CITY_BY_CODE = {city[0]: city for city in CITIES}


def _town(code: str, town_id: str, town_type: str, *, oaza: str = "", chome: str = "", koaza: str = "",
          flag: str = "0", abolished: str = "") -> dict[str, str]:
    _, prefecture, county, city, ward, _, _ = CITY_BY_CODE[code]
    return {"lg_code": code, "machiaza_id": town_id, "machiaza_type": town_type, "pref": prefecture,
            "county": county, "city": city, "ward": ward, "oaza_cho": oaza, "chome": chome,
            "chome_number": standardize_address(chome).rstrip("-"), "koaza": koaza, "rsdt_addr_flg": flag, "status_flg": "1",
            "ablt_date": abolished}


#: 町字のテキストの行（配布の並び: 全国地方公共団体コード・町字ID・住居表示の順）。
TOWNS = [
    _town("112038", "0002000", "1", oaza="大字安行"),
    _town("112038", "0003000", "1", oaza="大字峯"),
    _town("131041", "0000000", "4"),
    _town("131041", "0024000", "1", oaza="西新宿"),
    _town("131041", "0024002", "2", oaza="西新宿", chome="二丁目", flag="0"),
    _town("131041", "0024002", "2", oaza="西新宿", chome="二丁目", flag="1"),
    _town("131041", "0024009", "2", oaza="西新宿", chome="九丁目", abolished="2020-01-01"),
    _town("131041", "0030001", "5", koaza="甲州街道"),
    _town("133051", "0000101", "3", koaza="上の原"),
    _town("133051", "0001000", "1", oaza="大字平井"),
    _town("133051", "0001101", "3", oaza="大字平井", koaza="坊主岳"),
    _town("133051", "0001102", "3", oaza="大字平井", koaza="無点"),
    _town("141011", "0001001", "2", oaza="鶴見中央", chome="１丁目"),
    _town("141011", "0001002", "2", oaza="鶴見中央", chome="２丁目"),
]
#: 町字の代表点: (コード, 町字ID, 住居表示, 経度, 緯度)。「無点」は代表点を持たない。西新宿二丁目は住居表示の実施の行だけが持つ。
TOWN_POSITIONS = [
    ("112038", "0002000", "0", 139.75, 35.79),
    ("112038", "0003000", "0", 139.76, 35.85),
    ("131041", "0000000", "0", 139.70, 35.69),
    ("131041", "0024000", "0", 139.69, 35.69),
    ("131041", "0024002", "1", 139.692, 35.688),
    ("131041", "0024009", "0", 139.693, 35.687),
    ("131041", "0030001", "0", 139.694, 35.686),
    ("133051", "0000101", "0", 139.30, 35.76),
    ("133051", "0001000", "0", 139.26, 35.74),
    ("133051", "0001101", "0", 139.27, 35.745),
    ("141011", "0001001", "0", 139.67, 35.50),
    ("141011", "0001002", "0", 139.69, 35.52),
]

#: 住居表示の街区のテキスト: (コード, 町字ID, 街区ID, 街区符号, 住居表示, 廃止の日)。
BLOCKS = [
    ("131041", "0024002", "001", "8", "1", ""),
    ("131041", "0024002", "002", "9", "1", "2020-01-01"),
    ("131041", "0024002", "003", "10", "1", ""),
    ("131041", "0024002", "004", "11", "1", ""),
    # 区画にしない（廃止の日のある）町字の街区。
    ("131041", "0024009", "001", "1", "1", ""),
]
#: 住居表示の街区の代表点: (コード, 町字ID, 街区ID, 住居表示, 経度, 緯度)。10番は代表点を持たない。8番は住居表示の
#: 実施・未実施の2行を持ち、テキストと同じ実施の行を採る。11番は未実施の行だけを持つ。
BLOCK_POSITIONS = [
    ("131041", "0024002", "001", "0", 139.6900, 35.6880),
    ("131041", "0024002", "001", "1", 139.6915, 35.6890),
    ("131041", "0024002", "004", "0", 139.6925, 35.6885),
    ("131041", "0024009", "001", "1", 139.6930, 35.6870),
]
#: 位置参照情報の行: (都道府県名, 市区町村名, 大字・丁目名, 小字・通称名, 街区符号・地番, 経度, 緯度, 住居表示, 代表,
#: 更新後履歴)。
PARCELS = [
    ("東京都", "西多摩郡日の出町", "大字平井", "", "123", 139.261, 35.741, "0", "1", "0"),
    # 区画にしない小字（代表点の無い「無点」）の地番は大字に寄り、大字の同じ番号と重なる。
    ("東京都", "西多摩郡日の出町", "大字平井", "無点", "123", 139.262, 35.742, "0", "1", "0"),
    ("東京都", "西多摩郡日の出町", "大字平井", "坊主岳", "45", 139.271, 35.746, "0", "1", "0"),
    ("東京都", "西多摩郡日の出町", "大字平井", "", "7", 139.263, 35.743, "0", "0", "0"),
    ("東京都", "西多摩郡日の出町", "大字平井", "", "8", 139.264, 35.744, "0", "1", "3"),
    ("東京都", "西多摩郡日の出町", "大字平井", "", "9", 138.90, 35.744, "0", "1", "0"),
    # 住居表示の区域（ABR の街区を持つ西新宿二丁目）の行は、住居表示の印が無くても入れない。
    ("東京都", "新宿区", "西新宿二丁目", "", "8", 139.6999, 35.6999, "0", "1", "0"),
    ("東京都", "新宿区", "西新宿二丁目", "", "20", 139.6998, 35.6998, "0", "1", "0"),
    ("東京都", "新宿区", "西新宿二丁目", "", "11", 139.6997, 35.6997, "1", "1", "0"),
    ("神奈川県", "横浜市鶴見区", "鶴見中央一丁目", "", "5", 139.671, 35.501, "0", "1", "0"),
    ("神奈川県", "横浜市鶴見区", "無関係", "", "6", 139.672, 35.502, "0", "1", "0"),
]

def _write_csv_zip(path: Path, columns: str, rows: list[dict[str, str]]) -> None:
    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=columns.split(","), restval="", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(path.name.removesuffix(".zip"), text.getvalue())


def _position(code: str, lon: float, lat: float, srid: str) -> dict[str, str]:
    return {"lg_code": code, "rep_lon": str(lon), "rep_lat": str(lat), "rep_srid": srid}


def _write_abr() -> None:
    def path(stem: str) -> Path:
        return abr.archive_path(SNAPSHOT, stem)

    _write_csv_zip(path("mt_pref_all"), PREF_COLUMNS, [{"lg_code": c, "pref": n} for c, n, _, _ in PREFECTURES])
    _write_csv_zip(path("mt_pref_pos_all"), POS_COLUMNS,
                   [_position(c, lon, lat, "EPSG:6668") for c, _, lon, lat in PREFECTURES])
    _write_csv_zip(path("mt_city_all"), CITY_COLUMNS, [
        {"lg_code": c, "pref": p, "county": county, "city": city, "ward": ward}
        for c, p, county, city, ward, _, _ in CITIES])
    _write_csv_zip(path("mt_city_pos_all"), POS_COLUMNS,
                   [_position(c, lon, lat, "EPSG:4612") for c, *_, lon, lat in CITIES])
    _write_csv_zip(path("mt_town_fullset_all"), TOWN_COLUMNS, TOWNS)
    for prefecture in ("11", "13", "14"):
        _write_csv_zip(path(abr.town_position_stem(prefecture)), TOWN_POS_COLUMNS, [
            {"lg_code": c, "machiaza_id": town_id, "rsdt_addr_flg": flag, "rep_lon": str(lon), "rep_lat": str(lat),
             "rep_srid": "EPSG:6668"}
            for c, town_id, flag, lon, lat in TOWN_POSITIONS if c.startswith(prefecture)])
        texts, positions = abr.block_stems(prefecture)
        _write_csv_zip(path(texts), BLOCK_COLUMNS, [
            {"lg_code": c, "machiaza_id": town_id, "blk_id": blk_id, "blk_num": number, "rsdt_addr_flg": flag,
             "ablt_date": abolished}
            for c, town_id, blk_id, number, flag, abolished in BLOCKS if c.startswith(prefecture)])
        _write_csv_zip(path(positions), BLOCK_POS_COLUMNS, [
            {"lg_code": c, "machiaza_id": town_id, "blk_id": blk_id, "rsdt_addr_flg": flag, "rep_lon": str(lon),
             "rep_lat": str(lat), "rep_srid": "EPSG:6668"}
            for c, town_id, blk_id, flag, lon, lat in BLOCK_POSITIONS if c.startswith(prefecture)])


def _write_isj() -> None:
    """都道府県ごとの zip（Shift_JIS の CSV と、説明の HTML）。"""
    names = {"11": "埼玉県", "13": "東京都", "14": "神奈川県"}
    for prefecture, name in names.items():
        text = io.StringIO()
        writer = csv.writer(text, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        writer.writerow(ISJ_COLUMNS.split(","))
        for pref, city, oaza, koaza, number, lon, lat, residential, representative, deleted in PARCELS:
            if pref == name:
                writer.writerow([pref, city, oaza, koaza, number, "9", "0.0", "0.0", str(lat), str(lon), residential,
                                 representative, "0", deleted])
        path = isj_block.archive_path(ISJ_VERSION, prefecture)
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(f"{prefecture}_2025.csv", text.getvalue().encode("cp932"))
            archive.writestr(f"{ISJ_VERSION}.html", "<html></html>")


@pytest.fixture
def address_data(monkeypatch, tmp_path):
    """見本の配布を置き場に書く。"""
    monkeypatch.setattr(abr, "DATA_DIR", tmp_path / "abr")
    monkeypatch.setattr(isj_block, "DATA_DIR", tmp_path / "isj")
    _write_abr()
    _write_isj()


async def _derive(conn) -> None:
    """見本を取り込み、範囲の宣言つきで道を1本取り込んで、住所の段を流す。"""
    await ingest_source(conn, PROFILE, Source.ABR)
    await ingest_source(conn, PROFILE, Source.ISJ_BLOCK)
    await ingest_records("osm_way", [way_record(1, [(139.70, 35.69), (139.701, 35.691)], [1, 2])], conn=conn, bbox=BBOX)
    await derive_addresses.derive(conn)


async def test_区画は範囲の中の町字とその祖先が親でつながる(derive_conn, address_data):
    """町字は代表点が範囲の中のものだけで、祖先（範囲の外の埼玉県・川口市も）は入る。廃止の日のある町字・区画にしない
    町字区分（町字なし・道路名）・代表点の無い小字は入らない。大字自身の行が無い大字（鶴見中央）は子の代表点の重心に置く。"""
    await _derive(derive_conn)

    areas = {row["area_id"]: (row["parent_id"], row["level"], row["name"], row["county_name"])
             for row in await derive_conn.fetch("SELECT * FROM address_areas")}

    assert areas == {
        "130001": (None, "prefecture", "東京都", None),
        "140007": (None, "prefecture", "神奈川県", None),
        "110001": (None, "prefecture", "埼玉県", None),
        "131041": ("130001", "city", "新宿区", None),
        "133051": ("130001", "city", "日の出町", "西多摩郡"),
        "141003": ("140007", "city", "横浜市", None),
        "141011": ("141003", "ward", "鶴見区", None),
        "112241": ("110001", "city", "戸田市", None),
        "112038": ("110001", "city", "川口市", None),
        "1310410024000": ("131041", "oaza", "西新宿", None),
        "1310410024002": ("1310410024000", "aza", "二丁目", None),
        "1330510001000": ("133051", "oaza", "大字平井", None),
        "1330510001101": ("1330510001000", "aza", "坊主岳", None),
        "1330510000101": ("133051", "aza", "上の原", None),
        "1410110001000": ("141011", "oaza", "鶴見中央", None),
        "1410110001001": ("1410110001000", "aza", "一丁目", None),
        "1410110001002": ("1410110001000", "aza", "二丁目", None),
        "1120380002000": ("112038", "oaza", "大字安行", None),
    }
    center = await derive_conn.fetchrow(
        "SELECT ST_X(geom) AS lon, ST_Y(geom) AS lat FROM address_areas WHERE area_id = '1410110001000'")
    assert (center["lon"], center["lat"]) == pytest.approx((139.68, 35.51))


async def test_区画は書き始める段の違う別形の鍵で引ける(derive_conn, address_data):
    """丁目は区切り付きの形、字は「字」を挟む形と挟まない形、郡の町村は都道府県から書いて郡を省いた形も持つ。
    続きに使うのは大字・町の段までの鍵。"""
    await _derive(derive_conn)

    keys: dict[str, set[str]] = {}
    continuable: dict[str, set[bool]] = {}
    for row in await derive_conn.fetch(
            "SELECT k.key, k.area_id, k.continuable, a.level FROM address_search_keys k JOIN address_areas a USING (area_id)"):
        keys.setdefault(row["area_id"], set()).add(row["key"])
        continuable.setdefault(row["level"], set()).add(row["continuable"])

    assert keys["1310410024002"] == {"東京都新宿区西新宿2-", "新宿区西新宿2-", "西新宿2-"}
    assert keys["1330510001101"] == {
        f"{head}{koaza}" for head in ("東京都西多摩郡日ノ出町平井", "西多摩郡日ノ出町平井", "日ノ出町平井", "平井",
                                      "東京都日ノ出町平井")
        for koaza in ("坊主岳", "字坊主岳")}
    assert keys["141011"] == {"神奈川県横浜市鶴見区", "横浜市鶴見区", "鶴見区"}
    assert keys["1330510000101"] == {
        f"{head}{koaza}" for head in ("東京都西多摩郡日ノ出町", "西多摩郡日ノ出町", "日ノ出町", "東京都日ノ出町")
        for koaza in ("上ノ原", "字上ノ原")}
    assert continuable == {"prefecture": {True}, "city": {True}, "ward": {True}, "oaza": {True}, "aza": {False}}


async def test_街区は住居表示の区域でABRの街区を鍵で地番の区域で位置参照情報の地番を名前で区画に結ぶ(derive_conn, address_data):
    """ABR の街区は町字の鍵で結び、廃止の日のある街区・代表点の無い街区・区画にしない町字の街区は入らない。代表点は
    テキストと同じ住居表示の印の行（無ければ別の印の行）。位置参照情報の地番は、市区町村の名前（郡・政令市の区を含む）と
    大字・丁目名＋小字・通称名で区画に結ぶ（区画にしない小字は大字に寄り、同じ番号は小字の無い行を採る）。代表でない点・
    削除の行・範囲の外の点・結べない名前は入らない。ABR の街区を持つ区画（住居表示の区域）には地番を入れない。"""
    await _derive(derive_conn)

    blocks = {(row["area_id"], row["number"]): (row["kind"], row["lon"], row["lat"]) for row in await derive_conn.fetch(
        "SELECT area_id, number, kind, ST_X(geom) AS lon, ST_Y(geom) AS lat FROM address_blocks")}

    assert blocks == {
        ("1310410024002", "8"): ("residential", pytest.approx(139.6915), pytest.approx(35.6890)),
        ("1310410024002", "11"): ("residential", pytest.approx(139.6925), pytest.approx(35.6885)),
        ("1330510001000", "123"): ("parcel", pytest.approx(139.261), pytest.approx(35.741)),
        ("1330510001101", "45"): ("parcel", pytest.approx(139.271), pytest.approx(35.746)),
        ("1410110001001", "5"): ("parcel", pytest.approx(139.671), pytest.approx(35.501)),
    }


async def test_住所の生データが無ければ止まる(derive_conn):
    """区画の無い作り直しは、検索と施設の辺りを黙って空にするので、止める。"""
    await empty_ingested_tables(derive_conn)
    await ingest_records("osm_way", [way_record(1, [(139.70, 35.69), (139.701, 35.691)], [1, 2])], conn=derive_conn)

    with pytest.raises(RuntimeError, match="abr"):
        await derive_addresses.derive(derive_conn)
