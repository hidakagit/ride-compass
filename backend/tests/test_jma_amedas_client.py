"""jma_amedas_client.py（改善計画T387）のテスト。

test_jma_warning_client.pyと同じ観点（正常系のレスポンス取得・キャッシュヒット・
失敗時の挙動）を踏襲する。fetch_latest_observation_timeはJSON配列ではなくプレーン
テキスト（ISO時刻文字列1個）を返す実際の仕様（2026-08-29、実機curlで検証・修正）を
リグレッションテストで固定する。
"""

import httpx
import pytest

from app.infrastructure import jma_amedas_client
from app.infrastructure.jma_amedas_client import (
    fetch_latest_observation_time,
    fetch_observation_map,
    fetch_station_table,
)


class FakeResponse:
    def __init__(self, *, json_payload=None, text_payload=None):
        self._json_payload = json_payload
        self._text_payload = text_payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._json_payload

    @property
    def text(self):
        return self._text_payload


class FakeHttpClient:
    def __init__(self, response: FakeResponse):
        self.call_count = 0
        self._response = response

    async def get(self, url, timeout=None):
        self.call_count += 1
        return self._response


class FailingHttpClient:
    async def get(self, url, timeout=None):
        raise httpx.RequestError("boom")


@pytest.fixture(autouse=True)
def _clear_caches():
    jma_amedas_client._station_table_cache.clear()
    jma_amedas_client._latest_time_cache.clear()
    yield
    jma_amedas_client._station_table_cache.clear()
    jma_amedas_client._latest_time_cache.clear()


async def test_fetch_station_table_returns_data_and_caches():
    payload = {"44132": {"lat": [35, 41.5], "lon": [139, 45.0], "kjName": "東京"}}
    client = FakeHttpClient(FakeResponse(json_payload=payload))

    result = await fetch_station_table(client)
    result2 = await fetch_station_table(client)

    assert result == payload
    assert result2 == payload
    assert client.call_count == 1  # 2回目はキャッシュヒット


async def test_fetch_station_table_returns_none_on_failure():
    result = await fetch_station_table(FailingHttpClient())
    assert result is None


async def test_fetch_latest_observation_time_parses_plain_text_not_json():
    """実機仕様（プレーンテキスト、JSON配列ではない）のリグレッションテスト。"""
    client = FakeHttpClient(FakeResponse(text_payload="2026-08-29T17:00:00+09:00\n"))

    result = await fetch_latest_observation_time(client)

    assert result == "2026-08-29T17:00:00+09:00"


async def test_fetch_latest_observation_time_returns_none_when_empty():
    client = FakeHttpClient(FakeResponse(text_payload=""))
    assert await fetch_latest_observation_time(client) is None


async def test_fetch_observation_map_returns_data():
    payload = {"44132": {"temp": [26.5, 0], "humidity": [70, 0]}}
    client = FakeHttpClient(FakeResponse(json_payload=payload))

    result = await fetch_observation_map(client, "20260829170000")

    assert result == payload


async def test_fetch_observation_map_returns_none_on_failure():
    result = await fetch_observation_map(FailingHttpClient(), "20260829170000")
    assert result is None
