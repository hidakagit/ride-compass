"""wbgt_client.py（環境省 熱中症予防情報サイトのクライアント）のテスト。

他の外部APIクライアントのテストと同じ観点（正常系のレスポンス
取得・キャッシュヒット・失敗時の挙動）を踏襲するが、このクライアントは
異なりtenacity再試行を持たない（wbgt_client.pyモジュールdocstring参照: サイト側の利用上の
注意で高頻度アクセスを控えるよう明記されているため、429前提の再試行は設けずTTLキャッシュ
のみで呼び出し頻度を抑える設計）。そのため「リトライ」観点は「失敗時に再試行せず1回で
Noneを返す（呼び出し元へ丸投げしない）」ことの確認に置き換える。
"""

import httpx
import pytest

from app.infrastructure import wbgt_client as wbgt_client_module
from app.infrastructure.wbgt_client import fetch_forecast, fetch_point_master


class FakeResponse:
    def __init__(self, *, text=None, payload=None):
        self._text = text
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload

    @property
    def text(self):
        return self._text


class FakeHttpClient:
    def __init__(self, *, text=None, payload=None):
        self.call_count = 0
        self._text = text
        self._payload = payload
        self.last_params = None

    async def get(self, url, params=None, timeout=None):
        self.call_count += 1
        self.last_params = params
        return FakeResponse(text=self._text, payload=self._payload)


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


# 情報提供地点マスタCSVの1行サンプル。_parse_point_masterが読む列位置
# (2:no, 3:name, 7/8:緯度度/分, 9/10:経度度/分, 12:end_date)に合わせる。
POINT_MASTER_HEADER = ",".join(str(i) for i in range(13))
POINT_MASTER_ROW = ",".join(
    [
        "0",
        "1",
        "11001",
        "テスト地点",
        "4",
        "5",
        "6",
        "35",
        "30",
        "139",
        "40",
        "11",
        "9999-99-99",
    ]
)
POINT_MASTER_RETIRED_ROW = ",".join(
    [
        "0",
        "1",
        "11002",
        "廃止地点",
        "4",
        "5",
        "6",
        "36",
        "0",
        "140",
        "0",
        "11",
        "2020-03-31",
    ]
)
POINT_MASTER_CSV = "\n".join([POINT_MASTER_HEADER, POINT_MASTER_ROW, POINT_MASTER_RETIRED_ROW])


@pytest.fixture(autouse=True)
def clear_wbgt_caches():
    wbgt_client_module._point_master_cache.clear()
    wbgt_client_module._forecast_cache.clear()
    yield
    wbgt_client_module._point_master_cache.clear()
    wbgt_client_module._forecast_cache.clear()


async def test_fetch_point_master_parses_active_points_only():
    http_client = FakeHttpClient(text=POINT_MASTER_CSV)

    points = await fetch_point_master(http_client)

    assert points is not None
    assert len(points) == 1  # 運用終了済み地点(POINT_MASTER_RETIRED_ROW)は除外される
    assert points[0].no == "11001"
    assert points[0].name == "テスト地点"
    assert points[0].latitude == pytest.approx(35 + 30 / 60.0)
    assert points[0].longitude == pytest.approx(139 + 40 / 60.0)


async def test_fetch_point_master_reuses_cache_within_ttl():
    http_client = FakeHttpClient(text=POINT_MASTER_CSV)

    first = await fetch_point_master(http_client)
    second = await fetch_point_master(http_client)

    assert first == second
    assert http_client.call_count == 1


async def test_fetch_point_master_returns_none_on_request_error():
    result = await fetch_point_master(FailingHttpClient())

    assert result is None


async def test_fetch_point_master_returns_none_on_http_status_error_without_retry():
    http_client = HttpStatusErrorHttpClient()

    result = await fetch_point_master(http_client)

    assert result is None
    assert http_client.call_count == 1  # 429前提の再試行は設けない設計（再試行しない）


async def test_fetch_forecast_returns_data_on_success():
    http_client = FakeHttpClient(payload={"status": "success", "data": [{"forecast_val": "280"}]})

    result = await fetch_forecast(http_client, "11001", "20260822000000", "20260824000000")

    assert result == [{"forecast_val": "280"}]
    assert http_client.last_params["wbgt_nos"] == "11001"


async def test_fetch_forecast_reuses_cache_within_ttl():
    http_client = FakeHttpClient(payload={"status": "success", "data": [{"forecast_val": "280"}]})

    first = await fetch_forecast(http_client, "11001", "20260822000000", "20260824000000")
    second = await fetch_forecast(http_client, "11001", "20260822000000", "20260824000000")

    assert first == second
    assert http_client.call_count == 1


async def test_fetch_forecast_returns_none_on_request_error_without_retry():
    http_client = FailingHttpClient()

    result = await fetch_forecast(http_client, "11001", "20260822000000", "20260824000000")

    assert result is None


async def test_fetch_forecast_returns_none_on_unexpected_status():
    http_client = FakeHttpClient(payload={"status": "error", "data": []})

    result = await fetch_forecast(http_client, "11001", "20260822000000", "20260824000000")

    assert result is None


async def test_fetch_forecast_returns_none_when_data_is_not_a_list():
    http_client = FakeHttpClient(payload={"status": "success", "data": "not-a-list"})

    result = await fetch_forecast(http_client, "11001", "20260822000000", "20260824000000")

    assert result is None
