"""`infrastructure/jma_warning_client.py`——逆ジオコーダ・地域マスタ・警報電文を引く。

ここで見ないもの:
- TTLキャッシュの引き当てと、失敗をNoneへ倒す骨格 → `test_simple_api_client.py`
- area.jsonを辿って市区町村コードから府県予報区コードを出す処理 → `test_jma_area.py`
- 電文から走行に関わる警報を選ぶ判定 → `test_jma_warning_domain.py`
"""

import pytest

from app.infrastructure import jma_warning_client
from tests.fake_api_http import FakeHttpClient, FakeResponse


class PerUrlHttpClient:
    """要求URLごとに違う応答を返す上流。

    共有フェイク（`tests/fake_api_http.py`）は同じペイロードを返し続けるため、
    「要求した府県予報区コードがURLへ載っているか」をこれでしか見られない。登録の
    無いURLを要求されたらKeyErrorで落ちる（どのURLを引いたかが失敗時に出る）。
    """

    def __init__(self, payloads: dict):
        self._payloads = payloads

    async def get(self, url, params=None, timeout=None):
        return FakeResponse(self._payloads[url])


@pytest.fixture(autouse=True)
def _clear_caches():
    for cache in (
        jma_warning_client._muni_code_cache,
        jma_warning_client._area_data_cache,
        jma_warning_client._warning_cache,
    ):
        cache.clear()
    yield
    for cache in (
        jma_warning_client._muni_code_cache,
        jma_warning_client._area_data_cache,
        jma_warning_client._warning_cache,
    ):
        cache.clear()


async def test_municipality_code_comes_from_the_results_object():
    client = FakeHttpClient({"results": {"muniCd": "13101", "lv01Nm": "千代田区"}})

    assert await jma_warning_client.fetch_municipality_code(client, 35.6812, 139.7671) == "13101"


async def test_missing_municipality_code_yields_none():
    """市区町村が定まらない地点（海上等）でも、警報なしとして続けられるようにする。"""
    client = FakeHttpClient({"results": {}})

    assert await jma_warning_client.fetch_municipality_code(client, 35.6812, 139.7671) is None


async def test_unexpected_results_shape_yields_none():
    """上流が形を変えたときに、天候の応答ごと失敗させない。"""
    client = FakeHttpClient({"results": "ERROR"})

    assert await jma_warning_client.fetch_municipality_code(client, 35.6812, 139.7671) is None


async def test_nearby_coordinates_share_one_lookup():
    """丸めが効かないと、数m動くたびに逆ジオコーダを引き直して上流へ負荷をかける。"""
    client = FakeHttpClient({"results": {"muniCd": "13101"}})

    await jma_warning_client.fetch_municipality_code(client, 35.6812, 139.7671)
    await jma_warning_client.fetch_municipality_code(client, 35.68124, 139.76714)
    assert client.call_count == 1

    await jma_warning_client.fetch_municipality_code(client, 35.6822, 139.7671)
    assert client.call_count == 2


async def test_area_data_passes_through_without_reshaping():
    payload = {"offices": {"130000": {"name": "東京都", "children": ["131000"]}}}
    client = FakeHttpClient(payload)

    assert await jma_warning_client.fetch_area_data(client) == payload


async def test_warning_documents_are_fetched_per_office_code():
    """コードがURLとキャッシュキーの両方へ効かないと、別の府県の警報が表示される。"""
    template = jma_warning_client.JMA_WARNING_URL_TEMPLATE
    client = PerUrlHttpClient(
        {
            template.format(office_code="130000"): [{"reportDatetime": "tokyo"}],
            template.format(office_code="140000"): [{"reportDatetime": "kanagawa"}],
        }
    )

    assert await jma_warning_client.fetch_warning_documents(client, "130000") == [{"reportDatetime": "tokyo"}]
    assert await jma_warning_client.fetch_warning_documents(client, "140000") == [{"reportDatetime": "kanagawa"}]


async def test_non_list_warning_response_yields_none():
    """配列でない応答をそのまま通すと、電文を1件ずつ読む呼び出し元が落ちる。"""
    client = FakeHttpClient({"message": "maintenance"})

    assert await jma_warning_client.fetch_warning_documents(client, "130000") is None
