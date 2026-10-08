"""`api/routers/place_search.py`——地点の検索の経路。

経路から、サービス（`services/place_search_service.py`）と住所の辞書を引く層（`infrastructure/address_dictionary.py`）・
施設の表を引く層（`infrastructure/stop_place_search.py`）の判断を見る: 候補の種類・段・表示名・位置、入力の空白を除くこと、
何も当たらない入力は空、旧い市の名前を今の住所で出すこと（大字の無い区域はその市区町村で）、今は無い区画を落とすこと、
対象範囲の外の候補を落とすこと、打ちかけの入力の続きを足すこと（並び・1文字から・件数の上限・位置を持たない節）、
施設の名前を表記の揺れを除いて部分一致で引くこと（並び・件数の上限）、施設に添える辺り（立ち寄り先の派生の段が住所の辞書を
逆引きして入れる。市区町村から字・丁目まで、旧い住所の節を除く、大字の無い区域は市区町村まで）、住所と施設を混ぜる並び、
辞書が無ければ503、対象範囲を読めなければ502、回数制限。
辞書はテストの足場が数件の節で書いたもの（`tests/address_dictionary_fixture.py`）を本物の検索で引く。対象範囲は道路の
取込の記録から、施設は Overture の地点の取込から立ち寄り先の派生の段を本物のまま流して作り、注入から本物を通す。

ここで見ないもの:
- 対象範囲を読むこと（どの取込の記録の範囲か） → `test_ingested_area.py`
- 立ち寄り先の群・絞り・まとめ → `test_stop_places.py`
- 回数制限の窓 → `test_rate_limiter.py`
- Cache-Control の値と、失敗の応答に付けないこと → `test_cache_policy.py`
- 入力の長さ（`domain/place_search.py: PlaceQuery`の制約で、FastAPIが422で返す）
- 続きを引くときに見る節の数の上限（時間を抑えるためのもので、答えは当たる節が上限より少ない辞書と変わらない）
"""

import httpx
import pytest
import pytest_asyncio
from jageocoder.address import AddressLevel

from app.batch import derive_stop_places
from app.config import settings
from app.domain.place_search import PLACE_PREDICTION_LIMIT
from app.domain.region import BoundingBox
from app.infrastructure import database, rate_limiter
from app.main import app
from tests.address_dictionary_fixture import (
    IWATSUKI_HONMACHI,
    PLACES,
    NISHI_SHINJUKU,
    SHIBUYA_HONMACHI,
    SHINJUKU_8,
    Place,
    write_dictionary,
)
from tests.conftest import postgis_database_url, raw_connection
from tests.source_ingest import ingest_records, point_record

pytestmark = [pytest.mark.asyncio(loop_scope="module"), pytest.mark.xdist_group(name="postgis"), pytest.mark.postgis]

#: 対象範囲（関東）。道路の取込が宣言した範囲から読まれる。
AREA = BoundingBox(min_latitude=34.9, min_longitude=138.4, max_latitude=37.2, max_longitude=140.9)
#: `httpx.ASGITransport`が要求の接続元にする番地（回数制限の鍵になる）。
CLIENT_HOST = "127.0.0.1"


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


async def _search(query: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, client=(CLIENT_HOST, 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/api/place-search", params={"q": query})


def _facility_record(key: int, name: str, longitude: float, latitude: float, confidence: float = 0.75) -> object:
    """Overture の地点の1件（群「食べる・飲む」に入る分類）。"""
    return point_record(key, longitude, latitude, {
        "names": {"primary": name}, "confidence": confidence,
        "brand": {"names": {"primary": None}}, "taxonomy": {"hierarchy": ["food_and_drink", "cafe"]}})


async def _ingest_facilities(records: list[object]) -> None:
    """Overture の地点を取り込み、立ち寄り先の表を作る派生の段を流す。"""
    await ingest_records("overture_place", records)
    async with raw_connection() as conn:
        await derive_stop_places.derive(conn)


#: 足場の東京都新宿区。
NEW_SHINJUKU_WARD = PLACES[0].children[0]


def _address(place: Place, name: str, level: str) -> dict:
    return {"kind": "address", "level": level, "name": name, "area": None,
            "latitude": place.latitude, "longitude": place.longitude}


@pytest.mark.parametrize(("query", "candidates"), [
    pytest.param("東京都新宿区西新宿２－８－１", [_address(SHINJUKU_8, "東京都新宿区西新宿二丁目8番", "block")], id="街区まで"),
    pytest.param("東京都 新宿区　西新宿", [_address(NISHI_SHINJUKU, "東京都新宿区西新宿", "oaza")], id="空白を除く"),
    pytest.param("岩槻市本町", [_address(IWATSUKI_HONMACHI, "埼玉県さいたま市岩槻区本町", "oaza")], id="旧い市の名前は今の住所で"),
    # 関東の外（大阪市中央区本町）を落とし、旧い市の本町は今の住所と重ねて1件にする。
    pytest.param("本町", [
        _address(IWATSUKI_HONMACHI, "埼玉県さいたま市岩槻区本町", "oaza"),
        _address(SHIBUYA_HONMACHI, "東京都渋谷区本町", "oaza"),
    ], id="対象範囲の外を落とし、同じ住所は1件"),
    pytest.param("あ", [], id="何も当たらない"),
    # 入力の全部に当たった大字はまだ無く、続きの大字が、入力の一部に当たった区より先に並ぶ。
    pytest.param("新宿区西新", [
        _address(NISHI_SHINJUKU, "東京都新宿区西新宿", "oaza"),
        _address(NEW_SHINJUKU_WARD, "東京都新宿区", "city"),
    ], id="打ちかけの続き"),
    pytest.param("西", [_address(NISHI_SHINJUKU, "東京都新宿区西新宿", "oaza")], id="1文字にも続きを足す"),
])
@pytest.mark.usefixtures("area", "placed_address_dictionary")
async def test_returns_the_candidates_within_the_area(query, candidates):
    response = await _search(query)

    assert response.status_code == 200
    assert response.json() == {"candidates": candidates}


@pytest.mark.usefixtures("area")
async def test_continuations_are_the_shortest_ones_up_to_the_limit(address_dictionary_dir):
    oazas = tuple(
        Place("西" + "あ" * length, AddressLevel.OAZA, 139.76 + length / 1000, 35.69)
        for length in range(PLACE_PREDICTION_LIMIT + 1, 0, -1)
    )
    ward = Place("千代田区", AddressLevel.CITY, 139.753595, 35.694003, oazas)
    write_dictionary(address_dictionary_dir, (Place("東京都", AddressLevel.PREF, 139.69178, 35.68963, (ward,)),))
    response = await _search("千代田区西")

    assert response.status_code == 200
    shortest = sorted(oazas, key=lambda place: len(place.name))[:PLACE_PREDICTION_LIMIT]
    assert response.json() == {"candidates": [
        *(_address(place, f"東京都千代田区{place.name}", "oaza") for place in shortest),
        _address(ward, "東京都千代田区", "city"),
    ]}


@pytest.mark.usefixtures("area")
async def test_continuations_of_the_same_length_put_the_coarser_level_first(address_dictionary_dir):
    """同じ長さの表記（「柏下」と「柏市」）は、市区町村が大字より先（打ちかけの「柏」で柏市が上限から漏れない）。"""
    oaza = Place("柏下", AddressLevel.OAZA, 139.96, 35.87)
    city = Place("柏市", AddressLevel.CITY, 139.975, 35.8676, (oaza,))
    write_dictionary(address_dictionary_dir, (Place("千葉県", AddressLevel.PREF, 140.1233, 35.6047, (city,)),))
    response = await _search("柏")

    assert response.status_code == 200
    assert response.json() == {"candidates": [
        _address(city, "千葉県柏市", "city"),
        _address(oaza, "千葉県柏市柏下", "oaza"),
    ]}


@pytest.mark.usefixtures("area")
async def test_continuations_borrow_the_position_of_a_child_or_are_left_out(address_dictionary_dir):
    """配布の辞書の索引は、位置を持たない節（位置の値が範囲の外の999.9）も指す。"""
    unknown = 999.9
    child = Place("一丁目", AddressLevel.AZA, 139.764, 35.681)
    ward = Place("千代田区", AddressLevel.CITY, 139.753595, 35.694003, (
        Place("丸の内", AddressLevel.OAZA, unknown, unknown, (child,)),
    ))
    tokyo = Place("東京都", AddressLevel.PREF, 139.69178, 35.68963, (
        # 今の区画（郵便番号を持つ）にして、今は無い区画として落ちるのではなく、位置で落ちることを見る。
        ward, Place("千代田区", AddressLevel.CITY, unknown, unknown, note="postcode:1000000"),
    ))
    write_dictionary(address_dictionary_dir, (tokyo,))
    response = await _search("千代田")

    assert response.status_code == 200
    assert response.json() == {"candidates": [
        _address(ward, "東京都千代田区", "city"),
        _address(child, "東京都千代田区丸の内", "oaza"),
    ]}


@pytest.mark.usefixtures("area")
async def test_divisions_that_no_longer_exist_are_left_out(address_dictionary_dir):
    """配布の辞書は、市区町村の段までを今は無い名前でも持ち、`ref:`を付けずに今の区画と並べる（東京府渋谷区等）。
    今の区画は郵便番号か、今の住所のデータの子を持つ（政令市・郡・都道府県は子の区・市区町村が郵便番号を持つ）。"""
    shibuya = Place("渋谷区", AddressLevel.CITY, 139.697948, 35.663982, (SHIBUYA_HONMACHI,), "postcode:1500000")
    former_shibuya = Place("渋谷区", AddressLevel.CITY, 139.697948, 35.663982)
    write_dictionary(address_dictionary_dir, (
        Place("東京府", AddressLevel.PREF, 139.69178, 35.68963, (
            Place("東京市", AddressLevel.CITY, 139.69178, 35.68963, (former_shibuya,)),
            former_shibuya,
        )),
        Place("東京都", AddressLevel.PREF, 139.69178, 35.68963, (
            Place("東京市", AddressLevel.CITY, 139.69178, 35.68963, (former_shibuya,)),
            shibuya,
        )),
    ))
    response = await _search("渋谷区")

    assert response.status_code == 200
    assert response.json() == {"candidates": [
        _address(shibuya, "東京都渋谷区", "city"),
        _address(SHIBUYA_HONMACHI, "東京都渋谷区本町", "oaza"),
    ]}


@pytest.mark.usefixtures("area")
async def test_a_former_address_in_the_area_without_oaza_is_the_city(address_dictionary_dir):
    """旧い字の今の住所が、大字の無い区域（名前の無い大字の節。`ref:`では`<市区町村>.`）のときは、その市区町村を出す。"""
    city = Place("龍ケ崎市", AddressLevel.CITY, 140.182265, 35.911594, (
        Place(".", AddressLevel.OAZA, 140.178339, 35.92477),
        Place("柏ケ作", AddressLevel.OAZA, 140.178339, 35.92477, note="ref:茨城県龍ケ崎市."),
    ), "postcode:3010000")
    write_dictionary(address_dictionary_dir, (Place("茨城県", AddressLevel.PREF, 140.446793, 36.341813, (city,)),))
    response = await _search("柏ケ作")

    assert response.status_code == 200
    assert response.json() == {"candidates": [_address(city, "茨城県龍ケ崎市", "city")]}


@pytest.mark.usefixtures("area")
async def test_the_search_is_unavailable_without_the_dictionary(address_dictionary_dir):
    """辞書が無いのは「何も当たらない」と別の事実。空で返すと、画面は住所が見つからないと見せる。"""
    response = await _search("東京都新宿区")

    assert response.status_code == 503
    assert response.json() == {"detail": "住所の検索は今は使えません"}


@pytest.mark.usefixtures("app_db", "placed_address_dictionary")
async def test_the_search_is_a_failure_when_the_area_cannot_be_read():
    """対象範囲が読めない（DB障害・道路を未取込）ときは、候補を範囲で絞れない。"""
    response = await _search("東京都新宿区")

    assert response.status_code == 502
    assert response.json() == {"detail": "対象範囲を読めませんでした"}


@pytest.mark.usefixtures("area", "placed_address_dictionary")
async def test_the_search_is_rate_limited_per_client():
    limit = settings.place_search_rate_limit_per_minute
    for _ in range(limit - 1):
        rate_limiter.check_rate_limit(f"place-search:{CLIENT_HOST}", limit)

    assert (await _search("本町")).status_code == 200
    assert (await _search("本町")).status_code == 429


# --- 施設 ----------------------------------------------------------------------

#: 対象範囲の中（新宿）と外（大阪）の位置。施設は名前ごとに経度をずらして置く（チェーンでないのでまとまらない）。
LON, LAT = 139.70, 35.69
OUTSIDE_LON, OUTSIDE_LAT = 135.50, 34.68


#: 足場の辞書で、新宿の位置（`LON`・`LAT`）の辺り。
SHINJUKU_AREA = "新宿区西新宿二丁目"


def _facility(name: str, longitude: float, latitude: float = LAT, area: str = SHINJUKU_AREA) -> dict:
    return {"kind": "facility", "level": "point", "name": name, "area": area, "latitude": latitude,
            "longitude": longitude}


@pytest.mark.parametrize("query", [
    pytest.param("一蘭", id="名前の一部"),
    pytest.param("ｲﾁﾗﾝ", id="半角のかな"),
    pytest.param("らーめん 一蘭", id="空白"),
])
@pytest.mark.usefixtures("area", "placed_address_dictionary")
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


@pytest.mark.usefixtures("area", "placed_address_dictionary")
async def test_facilities_are_ordered_by_how_the_name_matches_then_by_length_then_by_confidence():
    """名前が入力と同じ → 入力で始まる → 入力を含む。同じ中では名前の短い順、同じ長さなら確からしさの高い順。"""
    await _ingest_facilities([
        _facility_record(1, "珈琲小杉", LON, LAT, confidence=0.9),
        _facility_record(2, "小杉コーヒー店", LON + 0.01, LAT, confidence=0.9),
        _facility_record(3, "小杉湯", LON + 0.02, LAT, confidence=0.6),
        _facility_record(4, "小杉亭", LON + 0.03, LAT, confidence=0.9),
        _facility_record(5, "小杉", LON + 0.04, LAT, confidence=0.5),
    ])

    response = await _search("小杉")

    assert response.status_code == 200
    assert response.json() == {"candidates": [
        _facility("小杉", LON + 0.04),
        _facility("小杉亭", LON + 0.03),
        _facility("小杉湯", LON + 0.02),
        _facility("小杉コーヒー店", LON + 0.01),
        _facility("珈琲小杉", LON),
    ]}


@pytest.mark.usefixtures("area", "placed_address_dictionary")
async def test_facilities_are_the_best_ones_up_to_the_limit():
    names = ["喫茶" + "あ" * length for length in range(PLACE_PREDICTION_LIMIT + 1, 0, -1)]
    await _ingest_facilities([_facility_record(i, name, LON + i / 100, LAT) for i, name in enumerate(names)])

    response = await _search("喫茶")

    assert response.status_code == 200
    assert [c["name"] for c in response.json()["candidates"]] == sorted(names, key=len)[:PLACE_PREDICTION_LIMIT]


@pytest.mark.usefixtures("area", "placed_address_dictionary")
async def test_an_input_without_letters_finds_no_facility():
    """表記の揺れを除くと空になる入力（中点・ハイフンだけ）は、どの名前にも含まれるとみなさない。"""
    await _ingest_facilities([_facility_record(1, "小杉湯", LON, LAT)])

    response = await _search("・-")

    assert response.status_code == 200
    assert response.json() == {"candidates": []}


@pytest.mark.usefixtures("area")
async def test_facilities_come_between_addresses_matching_the_whole_input_and_those_matching_a_part(
        address_dictionary_dir):
    """「小杉湯」で、入力の全部に当たる住所（続きの「小杉湯町」）→ 施設の小杉湯 → 入力の一部「小杉」に当たった住所。"""
    kosugi = Place("小杉", AddressLevel.OAZA, 139.66, 35.575)
    kosugiyu_town = Place("小杉湯町", AddressLevel.OAZA, 139.67, 35.58)
    city = Place("川崎市", AddressLevel.CITY, 139.70, 35.53, (kosugi, kosugiyu_town), "postcode:2100000")
    write_dictionary(address_dictionary_dir, (Place("神奈川県", AddressLevel.PREF, 139.64, 35.45, (city,)),))
    await _ingest_facilities([_facility_record(1, "小杉湯", LON, LAT)])

    response = await _search("小杉湯")

    assert response.status_code == 200
    assert response.json() == {"candidates": [
        _address(kosugiyu_town, "神奈川県川崎市小杉湯町", "oaza"),
        _facility("小杉湯", LON, area="川崎市小杉湯町"),
        _address(kosugi, "神奈川県川崎市小杉", "oaza"),
    ]}


# --- 施設の辺り ------------------------------------------------------------------


@pytest.mark.usefixtures("area", "placed_address_dictionary")
async def test_facilities_of_the_same_name_show_the_area_each_one_is_in():
    """チェーンの名前で探すと同じ表示名の店が並ぶので、辺り（市区町村から字・丁目まで）で見分ける。"""
    await _ingest_facilities([
        _facility_record(1, "ファミリーマート", SHINJUKU_8.longitude, SHINJUKU_8.latitude),
        _facility_record(2, "ファミリーマート", SHIBUYA_HONMACHI.longitude, SHIBUYA_HONMACHI.latitude),
    ])

    response = await _search("ファミリーマート")

    assert response.status_code == 200
    assert response.json() == {"candidates": [
        _facility("ファミリーマート", SHINJUKU_8.longitude, SHINJUKU_8.latitude, "新宿区西新宿二丁目"),
        _facility("ファミリーマート", SHIBUYA_HONMACHI.longitude, SHIBUYA_HONMACHI.latitude, "渋谷区本町"),
    ]}


@pytest.mark.parametrize(("places", "expected_area"), [
    # 旧い市の節は、今の住所の節と並んで当たる（今の住所の節より近いこともある）。
    pytest.param((Place("埼玉県", AddressLevel.PREF, 139.649, 35.85736, (
        Place("さいたま市", AddressLevel.CITY, 139.645502, 35.861515, (
            Place("岩槻区", AddressLevel.WARD, 139.694182, 35.949882, (
                Place("本町", AddressLevel.OAZA, LON + 0.002, LAT),
            ), "postcode:3390000"),
        )),
        Place("岩槻市", AddressLevel.CITY, 139.694182, 35.949882, (
            Place("本町", AddressLevel.OAZA, LON + 0.001, LAT, note="ref:埼玉県さいたま市岩槻区本町"),
        )),
    )),), "さいたま市岩槻区本町", id="旧い住所の節を除き、市から区へつなぐ"),
    pytest.param((Place("茨城県", AddressLevel.PREF, 140.446793, 36.341813, (
        Place("龍ケ崎市", AddressLevel.CITY, 140.182265, 35.911594, (
            Place(".", AddressLevel.OAZA, LON, LAT, (Place("3710番地", AddressLevel.BLOCK, LON, LAT),)),
        ), "postcode:3010000"),
    )),), "龍ケ崎市", id="大字の無い区域は市区町村まで"),
])
@pytest.mark.usefixtures("area")
async def test_the_area_is_the_nearest_current_address_from_the_city(address_dictionary_dir, places, expected_area):
    write_dictionary(address_dictionary_dir, places)
    await _ingest_facilities([_facility_record(1, "小杉湯", LON, LAT)])

    response = await _search("小杉湯")

    assert response.status_code == 200
    assert response.json() == {"candidates": [_facility("小杉湯", LON, area=expected_area)]}
