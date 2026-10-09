"""`api/routers/place_search.py`——地点の検索の経路。

経路から、サービス（`services/place_search_service.py`）と住所の区画の表を引く層（`infrastructure/address_search.py`）・
施設の表を引く層（`infrastructure/stop_place_search.py`）の判断を見る: 住所の候補の段・表示名・位置、書き方の違う入力
（空白・漢数字・長音）、全部に当たる・番地付き・続きの3通りの当たり方とその並び（段の粗いもの → 鍵の短いもの → 中心に近いもの）、
件数の上限、入力の一部にだけ当たった住所を出さないこと、施設の名前を表記の揺れを除いて部分一致で引くこと（並び・地図の
真ん中に近い店から上限まで）、施設に添える辺り、住所と施設を並べる順、対象範囲を読めなければ502、回数制限。
住所の区画の表は、アドレス・ベース・レジストリの行（施設の辺りは小地域の境界も）を取り込んで住所の派生の段を本物のまま
流して作る。対象範囲は道路の取込の記録から、施設は Overture の地点の取込から立ち寄り先の派生の段を本物のまま流して作り、
注入から本物を通す。

ここで見ないもの:
- 対象範囲を読むこと（どの取込の記録の範囲か） → `test_ingested_area.py`
- 住所の区画・鍵の作り方（範囲・祖先・鍵の別形） → `test_address_areas.py`、表記の揃え方の1つずつ → `test_address_area.py`
- 立ち寄り先の群・絞り・まとめ → `test_stop_places.py`
- 施設の辺りの決め方（辺の上・境界の外・結べない境界） → `test_stop_place_areas.py`
- 回数制限の窓 → `test_rate_limiter.py`
- Cache-Control の値と、失敗の応答に付けないこと → `test_cache_policy.py`
- 入力の長さ（`domain/place_search.py: PlaceQuery`の制約で、FastAPIが422で返す）
- 続きを長さごとに数えて引く鍵を切ること（時間を抑えるためのもので、答えは切らずに全部を並べたものと変わらない）
"""

import httpx
import pytest
import pytest_asyncio
import shapely

from app.batch import derive_addresses, derive_stop_places
from app.batch.ingest import SourceRecord
from app.config import settings
from app.domain.place_search import PLACE_PREDICTION_LIMIT
from app.domain.region import BoundingBox
from app.infrastructure import database, rate_limiter
from app.main import app
from tests.conftest import postgis_database_url, raw_connection
from tests.source_ingest import (
    abr_city_record,
    abr_prefecture_record,
    abr_town_record,
    estat_small_area_record,
    ingest_records,
    point_record,
)

pytestmark = [pytest.mark.asyncio(loop_scope="module"), pytest.mark.xdist_group(name="postgis"), pytest.mark.postgis]

#: 対象範囲（関東）。道路の取込が宣言した範囲から読まれる。
AREA = BoundingBox(min_latitude=34.9, min_longitude=138.4, max_latitude=37.2, max_longitude=140.9)
#: `httpx.ASGITransport`が要求の接続元にする番地（回数制限の鍵になる）。
CLIENT_HOST = "127.0.0.1"
#: 対象範囲の中（新宿）と外（大阪）の位置。施設は名前ごとに経度をずらして置く（チェーンでないのでまとまらない）。
#: 画面が見ている所の真ん中は、指定しなければ新宿の位置。
LON, LAT = 139.70, 35.69
OUTSIDE_LON, OUTSIDE_LAT = 135.50, 34.68


@pytest_asyncio.fixture(loop_scope="module")
async def app_db(road_graph_session, monkeypatch):
    """アプリのセッション工場を、表を作ったテストDBへ向ける。工場はプロセスに1つなので、作り直してから始め、閉じて終える。
    テストが入れた行は、抜けるときに`road_graph_session`の片付けが消す。"""
    monkeypatch.setattr(settings, "database_url", postgis_database_url())
    await database.dispose_engines()
    yield
    await database.dispose_engines()


@pytest_asyncio.fixture(loop_scope="module")
async def area(app_db):
    """道路の取込が対象範囲を宣言した状態。"""
    await ingest_records("osm_way", [], bbox=(
        AREA.min_latitude, AREA.min_longitude, AREA.max_latitude, AREA.max_longitude))


async def _search(query: str, near_longitude: float = LON, near_latitude: float = LAT) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, client=(CLIENT_HOST, 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(
            "/api/place-search", params={"q": query, "latitude": near_latitude, "longitude": near_longitude})


def _facility_record(key: int, name: str, longitude: float, latitude: float) -> object:
    """Overture の地点の1件（群「食べる・飲む」に入る分類）。"""
    return point_record(key, longitude, latitude, {
        "names": {"primary": name}, "confidence": 0.75,
        "brand": {"names": {"primary": None}}, "taxonomy": {"hierarchy": ["food_and_drink", "cafe"]}})


async def _ingest_facilities(records: list[object]) -> None:
    """Overture の地点を取り込み、立ち寄り先の表を作る派生の段を流す。"""
    await ingest_records("overture_place", records)
    async with raw_connection() as conn:
        await derive_stop_places.derive(conn)


async def _ingest_addresses(records: list[SourceRecord]) -> None:
    """アドレス・ベース・レジストリの行を取り込み、住所の区画の表を作る派生の段を流す（範囲は`area`の宣言）。"""
    await ingest_records("abr", records)
    async with raw_connection() as conn:
        await derive_addresses.derive(conn)


# --- 住所 ----------------------------------------------------------------------


def _town(city: SourceRecord, town_id: str, town_type: str, lon: float, lat: float, **names: str) -> SourceRecord:
    """`city`（`abr_city_record`）の市区町村に属す町字1件。"""
    attrs = city.attrs
    return abr_town_record(attrs["lg_code"], town_id, town_type, (attrs["pref"], attrs["city"], attrs["ward"]), lon, lat,
                           **names)


TOKYO = abr_prefecture_record("130001", "東京都", 139.69178, 35.68963)
SAITAMA = abr_prefecture_record("110001", "埼玉県", 139.649, 35.85736)
KANAGAWA = abr_prefecture_record("140007", "神奈川県", 139.6424, 35.4478)
SHINJUKU = abr_city_record("131041", "東京都", "新宿区", 139.703463, 35.69389)
SHIBUYA = abr_city_record("131130", "東京都", "渋谷区", 139.697948, 35.663982)
ADACHI = abr_city_record("131211", "東京都", "足立区", 139.804, 35.775)
SAITAMA_CITY = abr_city_record("111007", "埼玉県", "さいたま市", 139.645502, 35.861515)
IWATSUKI = abr_city_record("111104", "埼玉県", "さいたま市", 139.694182, 35.949882, ward="岩槻区")
KAWASAKI = abr_city_record("141305", "神奈川県", "川崎市", 139.703, 35.531)
NAKAHARA = abr_city_record("141330", "神奈川県", "川崎市", 139.657, 35.576, ward="中原区")
NISHI_SHINJUKU = _town(SHINJUKU, "0024000", "1", 139.697501, 35.690383, oaza="西新宿")
NISHI_SHINJUKU_2 = _town(SHINJUKU, "0024002", "2", 139.691774, 35.68945, oaza="西新宿", chome="二丁目")
NISHIARAI = _town(ADACHI, "0050000", "1", 139.786, 35.777, oaza="西新井")
#: 同じ名前の大字が新宿の近く（渋谷区本町）と遠く（さいたま市岩槻区本町）にある。渋谷区本町は十二丁目まで。
SHIBUYA_HONMACHI_TOWN = _town(SHIBUYA, "0030000", "1", 139.683187, 35.680992, oaza="本町")
SHIBUYA_HONMACHI_CHOMES = [
    _town(SHIBUYA, f"00300{number:02d}", "2", 139.68 + number / 1000, 35.68, oaza="本町", chome=chome)
    for number, chome in ((1, "一丁目"), (2, "二丁目"), (12, "十二丁目"))]
IWATSUKI_HONMACHI = _town(IWATSUKI, "0020000", "1", 139.693159, 35.947813, oaza="本町")
KOSUGI = _town(NAKAHARA, "0010000", "1", 139.66, 35.575, oaza="小杉")
ADDRESSES = [TOKYO, SAITAMA, KANAGAWA, SHINJUKU, SHIBUYA, ADACHI, SAITAMA_CITY, IWATSUKI, KAWASAKI, NAKAHARA,
             NISHI_SHINJUKU, NISHI_SHINJUKU_2, NISHIARAI, SHIBUYA_HONMACHI_TOWN, *SHIBUYA_HONMACHI_CHOMES,
             IWATSUKI_HONMACHI, KOSUGI]


def _address(record: SourceRecord, name: str, level: str) -> dict:
    """区画の候補。位置は区画の代表点（取り込んだ行の点）。"""
    point = shapely.from_wkb(record.geom_wkb)
    return {"kind": "address", "level": level, "name": name, "area": None,
            "latitude": point.y, "longitude": point.x}


@pytest.mark.parametrize(("query", "candidates"), [
    pytest.param("東京都 新宿区　西新宿", [_address(NISHI_SHINJUKU, "東京都新宿区西新宿", "oaza")], id="空白を除く"),
    pytest.param("西新", [
        _address(NISHI_SHINJUKU, "東京都新宿区西新宿", "oaza"),
        _address(NISHIARAI, "東京都足立区西新井", "oaza"),
    ], id="打ちかけの続き"),
    # 全部に当たる二丁目（鍵「本町2-」）が、番地付きとして頭に当たる大字の本町より先。
    pytest.param("本町2", [
        _address(SHIBUYA_HONMACHI_CHOMES[1], "東京都渋谷区本町二丁目", "aza"),
        _address(SHIBUYA_HONMACHI_TOWN, "東京都渋谷区本町", "oaza"),
        _address(IWATSUKI_HONMACHI, "埼玉県さいたま市岩槻区本町", "oaza"),
    ], id="丁目の数字まで"),
    pytest.param("西新宿2-8-1", [_address(NISHI_SHINJUKU_2, "東京都新宿区西新宿二丁目", "aza")], id="番地まで"),
    pytest.param("西新宿二丁目八番一号", [_address(NISHI_SHINJUKU_2, "東京都新宿区西新宿二丁目", "aza")],
                 id="番地まで漢数字で"),
    pytest.param("西新宿2ー8ー1", [_address(NISHI_SHINJUKU_2, "東京都新宿区西新宿二丁目", "aza")], id="番地まで長音で"),
    # 十二丁目までの町の「13」は、一丁目（鍵「本町1-」）にも十二丁目にも当てず、大字の本町の番地として読む。
    pytest.param("本町13-5", [
        _address(SHIBUYA_HONMACHI_TOWN, "東京都渋谷区本町", "oaza"),
        _address(IWATSUKI_HONMACHI, "埼玉県さいたま市岩槻区本町", "oaza"),
    ], id="無い丁目の番地は大字まで"),
    # 頭の「小杉」は大字に当たるが、残りの「湯」が番地の形でない。
    pytest.param("小杉湯", [], id="入力の一部にだけ当たる住所は出さない"),
    pytest.param("あ", [], id="何も当たらない"),
    # 揃えると空の文字列で、どの鍵の頭にも当たる。
    pytest.param("大字", [], id="揃えると空になる入力"),
])
@pytest.mark.usefixtures("area")
async def test_addresses_are_the_areas_the_input_reaches(query, candidates):
    await _ingest_addresses(ADDRESSES)

    response = await _search(query)

    assert response.status_code == 200
    assert response.json() == {"candidates": candidates}


@pytest.mark.parametrize(("near", "first", "second"), [
    pytest.param((LON, LAT), (SHIBUYA_HONMACHI_TOWN, "東京都渋谷区本町"),
                 (IWATSUKI_HONMACHI, "埼玉県さいたま市岩槻区本町"), id="新宿で見ている"),
    pytest.param((139.69, 35.95), (IWATSUKI_HONMACHI, "埼玉県さいたま市岩槻区本町"),
                 (SHIBUYA_HONMACHI_TOWN, "東京都渋谷区本町"), id="岩槻で見ている"),
])
@pytest.mark.usefixtures("area")
async def test_areas_of_the_same_name_come_nearest_to_the_center_first(near, first, second):
    await _ingest_addresses(ADDRESSES)

    response = await _search("本町", *near)

    assert response.status_code == 200
    assert response.json() == {"candidates": [_address(*first, "oaza"), _address(*second, "oaza")]}


@pytest.mark.usefixtures("area")
async def test_a_coarser_level_comes_before_shorter_keys():
    """1文字の「柏」で、全部に当たる大字の「柏」が上限を超えてあっても、続きの柏市（鍵「柏市」）が先頭に出る。"""
    chiba = abr_prefecture_record("120006", "千葉県", 140.1233, 35.6047)
    kashiwa = abr_city_record("122173", "千葉県", "柏市", 139.975, 35.8676)
    towns = [abr_city_record(f"1230{i}0", "千葉県", f"町{i}", 140.0 + i / 100, 35.8) for i in range(PLACE_PREDICTION_LIMIT)]
    oazas = [_town(town, "0001000", "1", 140.0 + i / 100, 35.8, oaza="柏") for i, town in enumerate(towns)]
    await _ingest_addresses([chiba, kashiwa, *towns, *oazas])

    response = await _search("柏")

    assert response.status_code == 200
    assert response.json() == {"candidates": [
        _address(kashiwa, "千葉県柏市", "city"),
        *(_address(oaza, f"千葉県町{i}柏", "oaza") for i, oaza in enumerate(oazas[:PLACE_PREDICTION_LIMIT - 1])),
    ]}


@pytest.mark.usefixtures("area")
async def test_continuations_are_the_shortest_ones_up_to_the_limit():
    chiyoda = abr_city_record("131016", "東京都", "千代田区", 139.753595, 35.694003)
    oazas = {
        length: _town(chiyoda, f"00{length:02d}000", "1", 139.76 + length / 1000, 35.69,
                                oaza="西" + "あ" * length)
        for length in range(PLACE_PREDICTION_LIMIT + 1, 0, -1)}
    await _ingest_addresses([TOKYO, chiyoda, *oazas.values()])

    response = await _search("千代田区西")

    assert response.status_code == 200
    assert response.json() == {"candidates": [
        _address(oazas[length], f"東京都千代田区西{'あ' * length}", "oaza")
        for length in range(1, PLACE_PREDICTION_LIMIT + 1)]}


@pytest.mark.usefixtures("app_db")
async def test_the_search_is_a_failure_when_the_area_cannot_be_read():
    """対象範囲が読めない（DB障害・道路を未取込）ときは、候補を範囲で絞れない。"""
    response = await _search("東京都新宿区")

    assert response.status_code == 502
    assert response.json() == {"detail": "対象範囲を読めませんでした"}


@pytest.mark.usefixtures("area")
async def test_the_search_is_rate_limited_per_client():
    limit = settings.place_search_rate_limit_per_minute
    for _ in range(limit - 1):
        rate_limiter.check_rate_limit(f"place-search:{CLIENT_HOST}", limit)

    assert (await _search("本町")).status_code == 200
    assert (await _search("本町")).status_code == 429


# --- 施設 ----------------------------------------------------------------------

def _facility(name: str, longitude: float, latitude: float = LAT, area: str | None = None) -> dict:
    """施設の候補。辺りは住所の区画と境界を取り込んだテスト（施設の辺りの節）だけが持つ。"""
    return {"kind": "facility", "level": "point", "name": name, "area": area, "latitude": latitude,
            "longitude": longitude}


@pytest.mark.parametrize("query", [
    pytest.param("一蘭", id="名前の一部"),
    pytest.param("ｲﾁﾗﾝ", id="半角のかな"),
    pytest.param("らーめん 一蘭", id="空白"),
])
@pytest.mark.usefixtures("area")
async def test_facilities_are_found_by_a_part_of_the_name_within_the_area(query):
    await _ingest_facilities([
        _facility_record(1, "らーめん一蘭 新宿店", LON, LAT),
        _facility_record(2, "イチラン・カフェ", LON + 0.01, LAT),
        _facility_record(3, "一蘭 道頓堀店", OUTSIDE_LON, OUTSIDE_LAT),
        _facility_record(4, "ラーメン一風堂", LON + 0.02, LAT),
    ])

    response = await _search(query)

    assert response.status_code == 200
    expected = {
        "一蘭": [_facility("らーめん一蘭 新宿店", LON)],
        "ｲﾁﾗﾝ": [_facility("イチラン・カフェ", LON + 0.01)],
        "らーめん 一蘭": [_facility("らーめん一蘭 新宿店", LON)],
    }[query]
    assert response.json() == {"candidates": expected}


@pytest.mark.usefixtures("area")
async def test_facilities_are_ordered_by_how_the_name_matches_then_by_the_distance():
    """名前が入力と同じ → 入力で始まる → 入力を含む。同じ中では、画面が見ている所の真ん中に近い順（名前の長さに依らない）。
    近さは測地の距離: 東へ経度0.01度（約0.90km）の店が、北へ緯度0.009度（約1.00km）の店より先（度のままなら逆になる）。"""
    await _ingest_facilities([
        _facility_record(1, "珈琲小杉", LON, LAT),
        _facility_record(2, "小杉コーヒー店", LON + 0.01, LAT),
        _facility_record(3, "小杉亭", LON, LAT + 0.009),
        _facility_record(4, "小杉", LON + 0.03, LAT),
    ])

    response = await _search("小杉", near_longitude=LON)

    assert response.status_code == 200
    assert response.json() == {"candidates": [
        _facility("小杉", LON + 0.03),
        _facility("小杉コーヒー店", LON + 0.01),
        _facility("小杉亭", LON, LAT + 0.009),
        _facility("珈琲小杉", LON),
    ]}


@pytest.mark.usefixtures("area")
async def test_facilities_with_the_same_name_beyond_the_limit_are_the_nearest_ones():
    """同じ名前の店が上限を超えると、画面が見ている所の真ん中に近い店から上限まで。"""
    count = PLACE_PREDICTION_LIMIT + 2
    # チェーンの分からない地点は、名前が同じでも別々の店のまま（立ち寄り先の派生の段）。経度の東端は対象範囲の中。
    await _ingest_facilities([_facility_record(i, "喫茶ことり", LON + i / 10, LAT) for i in range(count)])
    near_longitude = LON + (count - 1) / 10

    response = await _search("喫茶ことり", near_longitude=near_longitude)

    assert response.status_code == 200
    assert [c["longitude"] for c in response.json()["candidates"]] == [
        LON + i / 10 for i in range(count - 1, count - 1 - PLACE_PREDICTION_LIMIT, -1)
    ]


@pytest.mark.usefixtures("area")
async def test_an_input_without_letters_finds_no_facility():
    """表記の揺れを除くと空になる入力（中点・ハイフンだけ）は、どの名前にも含まれるとみなさない。"""
    await _ingest_facilities([_facility_record(1, "小杉湯", LON, LAT)])

    response = await _search("・-")

    assert response.status_code == 200
    assert response.json() == {"candidates": []}


@pytest.mark.usefixtures("area")
async def test_addresses_come_before_facilities():
    """施設は、検索の中心に住所より近くても住所の後に並ぶ。"""
    await _ingest_addresses(ADDRESSES)
    await _ingest_facilities([_facility_record(1, "小杉湯", LON, LAT)])

    response = await _search("小杉")

    assert response.status_code == 200
    assert response.json() == {"candidates": [
        _address(KOSUGI, "神奈川県川崎市中原区小杉", "oaza"),
        _facility("小杉湯", LON),
    ]}


# --- 施設の辺り ------------------------------------------------------------------


@pytest.mark.usefixtures("area")
async def test_facilities_of_the_same_name_show_the_area_each_one_is_in():
    """チェーンの名前で探すと同じ表示名の店が並ぶので、辺り（店の位置を含む小地域の境界に結んだ町字の、市区町村から先の
    名前）で見分ける。"""
    shinjuku, iwatsuki = ("東京都", "新宿区", ""), ("埼玉県", "さいたま市", "岩槻区")
    await ingest_records("abr", [
        abr_prefecture_record("130001", "東京都", 139.69, 35.69),
        abr_prefecture_record("110001", "埼玉県", 139.65, 35.86),
        abr_city_record("131041", "東京都", "新宿区", 139.70, 35.69),
        abr_city_record("111007", "埼玉県", "さいたま市", 139.645, 35.86),
        abr_city_record("111104", "埼玉県", "さいたま市", 139.69, 35.95, ward="岩槻区"),
        abr_town_record("131041", "0024000", "1", shinjuku, LON - 0.01, LAT, oaza="西新宿"),
        abr_town_record("131041", "0024002", "2", shinjuku, LON, LAT, oaza="西新宿", chome="二丁目"),
        abr_town_record("111104", "0001000", "1", iwatsuki, 139.70, 35.95, oaza="本町"),
    ])
    await ingest_records("estat_small_area", [
        estat_small_area_record("13104002402", "西新宿２丁目", [
            (LON - 0.002, LAT - 0.002), (LON - 0.002, LAT + 0.002), (LON + 0.002, LAT + 0.002),
            (LON + 0.002, LAT - 0.002), (LON - 0.002, LAT - 0.002)]),
        estat_small_area_record("11110000100", "本町", [
            (139.69, 35.94), (139.69, 35.96), (139.71, 35.96), (139.71, 35.94), (139.69, 35.94)]),
    ])
    async with raw_connection() as conn:
        await derive_addresses.derive(conn)
    await _ingest_facilities([
        _facility_record(1, "ファミリーマート", LON, LAT),
        _facility_record(2, "ファミリーマート", 139.70, 35.95),
    ])

    response = await _search("ファミリーマート")

    assert response.status_code == 200
    assert response.json() == {"candidates": [
        _facility("ファミリーマート", LON, LAT, "新宿区西新宿二丁目"),
        _facility("ファミリーマート", 139.70, 35.95, "さいたま市岩槻区本町"),
    ]}

