"""`api/routers/place_search.py`——地点の検索の経路。

経路から、サービス（`services/place_search_service.py`）と住所の辞書を引く層（`infrastructure/address_dictionary.py`）の
判断を見る: 候補の種類・段・表示名・位置、入力の空白を除くこと、何も当たらない入力は空、旧い市の名前を今の住所で出すこと、
対象範囲の外の候補を落とすこと、打ちかけの入力の続きを足すこと（並び・最短の長さ・件数の上限・位置を持たない節）、
辞書が無ければ503、対象範囲を読めなければ502、回数制限。
辞書はテストの足場が数件の節で書いたもの（`tests/address_dictionary_fixture.py`）を本物の検索で引き、対象範囲は
地域サービスのフェイクで与える。

ここで見ないもの:
- 対象範囲を読むこと → `test_ingested_area.py`
- 回数制限の窓 → `test_rate_limiter.py`
- Cache-Control の値と、失敗の応答に付けないこと → `test_cache_policy.py`
- 入力の長さ（`domain/place_search.py: PlaceQuery`の制約で、FastAPIが422で返す）
- 続きを引くときに見る節の数の上限（時間を抑えるためのもので、答えは当たる節が上限より少ない辞書と変わらない）
"""

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from jageocoder.address import AddressLevel

from app.api.dependencies import get_place_search_service
from app.config import settings
from app.domain.place_search import PLACE_PREDICTION_LIMIT
from app.domain.region import BoundingBox
from app.infrastructure import rate_limiter
from app.main import app
from app.services.place_search_service import PlaceSearchService
from tests.address_dictionary_fixture import (
    IWATSUKI_HONMACHI,
    PLACES,
    NISHI_SHINJUKU,
    SHIBUYA_HONMACHI,
    SHINJUKU_8,
    Place,
    write_dictionary,
)

client = TestClient(app)

#: 対象範囲（関東）。本物はDBの取込の記録から読む（`RegionService.get_ingested_area`）ので、ここではテストが与える。
AREA = BoundingBox(min_latitude=34.9, min_longitude=138.4, max_latitude=37.2, max_longitude=140.9)


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    """テストが足した依存の差し替えを、抜けるときに片付ける。"""
    yield
    app.dependency_overrides.clear()


class FakeRegionService:
    def __init__(self, area: BoundingBox | None):
        self._area = area

    async def get_ingested_area(self):
        return self._area


def _serve_area(area: BoundingBox | None) -> None:
    @asynccontextmanager
    async def open_region_service():
        yield FakeRegionService(area)

    app.dependency_overrides[get_place_search_service] = lambda: PlaceSearchService(open_region_service)


@pytest.fixture
def dictionary(address_dictionary_dir):
    write_dictionary(address_dictionary_dir)


#: 足場の東京都新宿区。
NEW_SHINJUKU_WARD = PLACES[0].children[0]


def _address(place: Place, name: str, level: str) -> dict:
    return {"kind": "address", "level": level, "name": name, "latitude": place.latitude, "longitude": place.longitude}


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
    pytest.param("西", [], id="1文字には続きを足さない"),
])
def test_returns_the_candidates_within_the_area(dictionary, query, candidates):
    _serve_area(AREA)

    response = client.get("/api/place-search", params={"q": query})

    assert response.status_code == 200
    assert response.json() == {"candidates": candidates}


def test_continuations_are_the_shortest_ones_up_to_the_limit(address_dictionary_dir):
    oazas = tuple(
        Place("西" + "あ" * length, AddressLevel.OAZA, 139.76 + length / 1000, 35.69)
        for length in range(PLACE_PREDICTION_LIMIT + 1, 0, -1)
    )
    ward = Place("千代田区", AddressLevel.CITY, 139.753595, 35.694003, oazas)
    write_dictionary(address_dictionary_dir, (Place("東京都", AddressLevel.PREF, 139.69178, 35.68963, (ward,)),))
    _serve_area(AREA)

    response = client.get("/api/place-search", params={"q": "千代田区西"})

    assert response.status_code == 200
    shortest = sorted(oazas, key=lambda place: len(place.name))[:PLACE_PREDICTION_LIMIT]
    assert response.json() == {"candidates": [
        *(_address(place, f"東京都千代田区{place.name}", "oaza") for place in shortest),
        _address(ward, "東京都千代田区", "city"),
    ]}


def test_continuations_borrow_the_position_of_a_child_or_are_left_out(address_dictionary_dir):
    """配布の辞書の索引は、位置を持たない節（位置の値が範囲の外の999.9）も指す。"""
    unknown = 999.9
    child = Place("一丁目", AddressLevel.AZA, 139.764, 35.681)
    ward = Place("千代田区", AddressLevel.CITY, 139.753595, 35.694003, (
        Place("丸の内", AddressLevel.OAZA, unknown, unknown, (child,)),
    ))
    tokyo = Place("東京都", AddressLevel.PREF, 139.69178, 35.68963, (
        ward, Place("千代田区", AddressLevel.CITY, unknown, unknown),
    ))
    write_dictionary(address_dictionary_dir, (tokyo,))
    _serve_area(AREA)

    response = client.get("/api/place-search", params={"q": "千代田"})

    assert response.status_code == 200
    assert response.json() == {"candidates": [
        _address(ward, "東京都千代田区", "city"),
        _address(child, "東京都千代田区丸の内", "oaza"),
    ]}


def test_the_search_is_unavailable_without_the_dictionary(address_dictionary_dir):
    """辞書が無いのは「何も当たらない」と別の事実。空で返すと、画面は住所が見つからないと見せる。"""
    _serve_area(AREA)

    response = client.get("/api/place-search", params={"q": "東京都新宿区"})

    assert response.status_code == 503
    assert response.json() == {"detail": "住所の検索は今は使えません"}


def test_the_search_is_a_failure_when_the_area_cannot_be_read(dictionary):
    """対象範囲が読めない（DB障害・道路を未取込）ときは、候補を範囲で絞れない。"""
    _serve_area(None)

    response = client.get("/api/place-search", params={"q": "東京都新宿区"})

    assert response.status_code == 502
    assert response.json() == {"detail": "対象範囲を読めませんでした"}


def test_the_search_is_rate_limited_per_client(dictionary):
    _serve_area(AREA)
    limit = settings.place_search_rate_limit_per_minute
    for _ in range(limit - 1):
        rate_limiter.check_rate_limit("place-search:testclient", limit)

    assert client.get("/api/place-search", params={"q": "本町"}).status_code == 200
    assert client.get("/api/place-search", params={"q": "本町"}).status_code == 429
