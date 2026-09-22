"""`infrastructure/jma_warning_client.py`——JMA警報電文・地域マスタ(area.json)・
国土地理院逆ジオコーダの取得。

ここで見ないもの:
- キャッシュ参照・形の検査・例外をNoneへ倒す骨格 → `test_simple_api_client.py`
- 電文から警報の種類・強さを読み解く処理 → `domain/jma_warning.py`側
"""

import pytest
from cachetools import TTLCache

from app.infrastructure import jma_warning_client
from tests.fake_api_http import FailingHttpClient, FakeHttpClient, HttpStatusErrorHttpClient


@pytest.fixture(autouse=True)
def _clear_module_caches():
    """プロセス内TTLCacheはテスト間で持ち越される。モジュールが持つキャッシュを
    名前で並べずに走査して空にする（キャッシュが増えても取りこぼさない）。"""
    for value in vars(jma_warning_client).values():
        if isinstance(value, TTLCache):
            value.clear()


async def test_municipality_code_reads_muni_cd():
    client = FakeHttpClient({"results": {"muniCd": "13101"}})

    assert await jma_warning_client.fetch_municipality_code(client, 35.6812, 139.7671) == "13101"
    assert client.last_params == {"lat": 35.6812, "lon": 139.7671}


async def test_municipality_code_without_results_returns_none():
    client = FakeHttpClient({})

    assert await jma_warning_client.fetch_municipality_code(client, 35.6812, 139.7671) is None


async def test_municipality_code_from_non_mapping_payload_returns_none():
    """逆ジオコーダが`results`の形を変えても、天候の応答ごと落とさない。"""
    client = FakeHttpClient([{"muniCd": "13101"}])

    assert await jma_warning_client.fetch_municipality_code(client, 35.6812, 139.7671) is None


async def test_municipality_code_connection_failure_returns_none():
    assert await jma_warning_client.fetch_municipality_code(FailingHttpClient(), 35.6812, 139.7671) is None


async def test_municipality_code_cache_key_rounds_to_three_decimals():
    client = FakeHttpClient({"results": {"muniCd": "13101"}})

    await jma_warning_client.fetch_municipality_code(client, 35.68123, 139.76712)
    await jma_warning_client.fetch_municipality_code(client, 35.68149, 139.76748)
    assert client.call_count == 1

    await jma_warning_client.fetch_municipality_code(client, 35.68250, 139.76712)
    assert client.call_count == 2


async def test_area_data_is_cached_across_calls():
    payload = {"offices": {"130000": {"name": "東京都"}}}
    client = FakeHttpClient(payload)

    assert await jma_warning_client.fetch_area_data(client) == payload
    assert await jma_warning_client.fetch_area_data(client) == payload
    assert client.call_count == 1


async def test_area_data_http_error_returns_none():
    assert await jma_warning_client.fetch_area_data(HttpStatusErrorHttpClient()) is None


async def test_warning_documents_requests_the_office_code_url():
    client = FakeHttpClient([{"headlineText": ""}])

    assert await jma_warning_client.fetch_warning_documents(client, "130000") == [{"headlineText": ""}]
    assert client.requested_urls[0].endswith("/130000.json")


async def test_warning_documents_reject_non_list_payload():
    """1地点でも複数電文の配列で返る。単独の電文（dict）は読めないためNoneへ倒す。"""
    client = FakeHttpClient({"headlineText": ""})

    assert await jma_warning_client.fetch_warning_documents(client, "130000") is None


async def test_warning_documents_are_cached_per_office_code():
    client = FakeHttpClient([])

    await jma_warning_client.fetch_warning_documents(client, "130000")
    await jma_warning_client.fetch_warning_documents(client, "130000")
    assert client.call_count == 1

    await jma_warning_client.fetch_warning_documents(client, "140000")
    assert client.call_count == 2
