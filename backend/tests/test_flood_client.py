"""flood_client.py（JMA指定河川洪水予報APIのクライアント）のテスト。

他の外部APIクライアントのテストと同じ観点（正常系のレスポンス
取得・キャッシュヒット・失敗時の挙動）を踏襲するが、このクライアントもjma_warning_client.pyと
同じ理由（モジュールdocstring参照）でtenacity再試行を持たない。「リトライ」観点は
「失敗時に再試行せず1回でNoneを返す」ことの確認に置き換える。
"""

import httpx
import pytest

from app.infrastructure import flood_client as flood_client_module
from app.infrastructure.flood_client import fetch_flood_documents


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeHttpClient:
    def __init__(self, payload):
        self.call_count = 0
        self._payload = payload

    async def get(self, url, params=None, timeout=None):
        self.call_count += 1
        return FakeResponse(self._payload)


class FailingHttpClient:
    async def get(self, url, params=None, timeout=None):
        raise httpx.RequestError("boom")


class HttpStatusErrorResponse:
    status_code = 500

    def raise_for_status(self):
        raise httpx.HTTPStatusError("500 Server Error", request=None, response=self)


class HttpStatusErrorHttpClient:
    def __init__(self):
        self.call_count = 0

    async def get(self, url, params=None, timeout=None):
        self.call_count += 1
        return HttpStatusErrorResponse()


@pytest.fixture(autouse=True)
def clear_flood_cache():
    flood_client_module._flood_cache.clear()
    yield
    flood_client_module._flood_cache.clear()


async def test_fetch_flood_documents_returns_documents_on_success():
    http_client = FakeHttpClient([{"name": "多摩川", "code": "10"}])

    result = await fetch_flood_documents(http_client)

    assert result == [{"name": "多摩川", "code": "10"}]


async def test_fetch_flood_documents_reuses_cache_within_ttl():
    http_client = FakeHttpClient([{"name": "多摩川", "code": "10"}])

    first = await fetch_flood_documents(http_client)
    second = await fetch_flood_documents(http_client)

    assert first == second
    assert http_client.call_count == 1


async def test_fetch_flood_documents_returns_none_on_request_error_without_retry():
    http_client = FailingHttpClient()

    result = await fetch_flood_documents(http_client)

    assert result is None


async def test_fetch_flood_documents_returns_none_on_http_status_error_without_retry():
    http_client = HttpStatusErrorHttpClient()

    result = await fetch_flood_documents(http_client)

    assert result is None
    assert http_client.call_count == 1  # 429前提の再試行は設けない設計（再試行しない）


async def test_fetch_flood_documents_returns_none_when_response_is_not_a_list():
    http_client = FakeHttpClient({"unexpected": "shape"})

    result = await fetch_flood_documents(http_client)

    assert result is None
