"""jma_warning_client.py（JMA警報・注意報API、area.json、国土地理院逆ジオコーダの
クライアント）のテスト。

weather_client.pyのテスト（test_weather_client_cache.py）と同じ観点（正常系のレスポンス
取得・キャッシュヒット・失敗時の挙動）を踏襲するが、このクライアントもwbgt_client.pyと
同じ理由（モジュールdocstring参照: 更新頻度がOpen-Meteoほど高くない）でtenacity再試行を
持たない。「リトライ」観点は「失敗時に再試行せず1回でNoneを返す」ことの確認に置き換える。
"""

import httpx
import pytest

from app.infrastructure import jma_warning_client as jma_warning_client_module
from app.infrastructure.jma_warning_client import (
    fetch_area_data,
    fetch_municipality_code,
    fetch_warning_documents,
)


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
        self.last_params = None

    async def get(self, url, params=None, timeout=None):
        self.call_count += 1
        self.last_params = params
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
def clear_jma_warning_caches():
    jma_warning_client_module._muni_code_cache.clear()
    jma_warning_client_module._area_data_cache.clear()
    jma_warning_client_module._warning_cache.clear()
    yield
    jma_warning_client_module._muni_code_cache.clear()
    jma_warning_client_module._area_data_cache.clear()
    jma_warning_client_module._warning_cache.clear()


# --- fetch_municipality_code ---


async def test_fetch_municipality_code_returns_code_on_success():
    http_client = FakeHttpClient({"results": {"muniCd": "13101", "lv01Nm": "千代田区"}})

    result = await fetch_municipality_code(http_client, 35.6938, 139.7532)

    assert result == "13101"


async def test_fetch_municipality_code_reuses_cache_within_ttl():
    http_client = FakeHttpClient({"results": {"muniCd": "13101"}})

    first = await fetch_municipality_code(http_client, 35.6938, 139.7532)
    second = await fetch_municipality_code(http_client, 35.6938, 139.7532)

    assert first == second
    assert http_client.call_count == 1


async def test_fetch_municipality_code_returns_none_on_request_error_without_retry():
    http_client = FailingHttpClient()

    result = await fetch_municipality_code(http_client, 35.0, 139.0)

    assert result is None


async def test_fetch_municipality_code_returns_none_on_missing_results():
    http_client = FakeHttpClient({"unexpected": "shape"})

    result = await fetch_municipality_code(http_client, 35.0, 139.0)

    assert result is None


# --- fetch_area_data ---


async def test_fetch_area_data_returns_payload_on_success():
    payload = {"centers": {}, "offices": {}}
    http_client = FakeHttpClient(payload)

    result = await fetch_area_data(http_client)

    assert result == payload


async def test_fetch_area_data_reuses_cache_within_ttl():
    http_client = FakeHttpClient({"centers": {}})

    first = await fetch_area_data(http_client)
    second = await fetch_area_data(http_client)

    assert first == second
    assert http_client.call_count == 1


async def test_fetch_area_data_returns_none_on_http_status_error_without_retry():
    http_client = HttpStatusErrorHttpClient()

    result = await fetch_area_data(http_client)

    assert result is None
    assert http_client.call_count == 1  # 429前提の再試行は設けない設計（再試行しない）


# --- fetch_warning_documents ---


async def test_fetch_warning_documents_returns_documents_on_success():
    http_client = FakeHttpClient([{"headlineText": "大雨注意報"}])

    result = await fetch_warning_documents(http_client, "130000")

    assert result == [{"headlineText": "大雨注意報"}]


async def test_fetch_warning_documents_reuses_cache_within_ttl():
    http_client = FakeHttpClient([{"headlineText": "大雨注意報"}])

    first = await fetch_warning_documents(http_client, "130000")
    second = await fetch_warning_documents(http_client, "130000")

    assert first == second
    assert http_client.call_count == 1


async def test_fetch_warning_documents_returns_none_on_request_error_without_retry():
    http_client = FailingHttpClient()

    result = await fetch_warning_documents(http_client, "130000")

    assert result is None


async def test_fetch_warning_documents_returns_none_when_response_is_not_a_list():
    http_client = FakeHttpClient({"unexpected": "shape"})

    result = await fetch_warning_documents(http_client, "130000")

    assert result is None
