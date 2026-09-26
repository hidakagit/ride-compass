"""`infrastructure/jma_warning_client.py`——JMA警報電文・地域マスタ(area.json)の取得。

ここで見ないもの:
- キャッシュ参照・形の検査・例外をNoneへ倒す骨格 → `test_simple_api_client.py`
- 電文から警報の種類・強さを読み解く処理 → `domain/jma_warning.py`側
"""

import pytest
from cachetools import TTLCache

from app.infrastructure import jma_warning_client
from tests.fake_api_http import FakeHttpClient, HttpStatusErrorHttpClient


@pytest.fixture(autouse=True)
def _clear_module_caches():
    """プロセス内TTLCacheはテスト間で持ち越される。モジュールが持つキャッシュを
    名前で並べずに走査して空にする（キャッシュが増えても取りこぼさない）。"""
    for value in vars(jma_warning_client).values():
        if isinstance(value, TTLCache):
            value.clear()


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
