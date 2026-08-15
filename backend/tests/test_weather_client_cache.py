import httpx
import pytest

from app.domain.route import Coordinates
from app.infrastructure import weather_client as weather_client_module
from app.infrastructure.weather_client import WeatherClient


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

    async def get(self, url, params=None):
        self.call_count += 1
        return FakeResponse(self._payload)


class FailingHttpClient:
    async def get(self, url, params=None):
        raise httpx.RequestError("boom")


class TooManyRequestsResponse:
    status_code = 429
    headers: dict = {}

    def raise_for_status(self):
        raise httpx.HTTPStatusError("429 Too Many Requests", request=None, response=self)

    def json(self):
        raise AssertionError("json() should not be called when raise_for_status() raises")


class RetryThenSucceedHttpClient:
    """1回目・2回目は429、3回目(最終試行)で成功する上流を模する。"""

    def __init__(self, payload):
        self.call_count = 0
        self._payload = payload

    async def get(self, url, params=None):
        self.call_count += 1
        if self.call_count < 3:
            return TooManyRequestsResponse()
        return FakeResponse(self._payload)


class AlwaysTooManyRequestsHttpClient:
    def __init__(self):
        self.call_count = 0

    async def get(self, url, params=None):
        self.call_count += 1
        return TooManyRequestsResponse()


@pytest.fixture(autouse=True)
def clear_weather_cache():
    weather_client_module._forecast_cache.clear()
    yield
    weather_client_module._forecast_cache.clear()


async def test_get_forecast_reuses_cache_within_ttl():
    client = WeatherClient()
    http_client = FakeHttpClient({"current": {}, "hourly": {}})
    point = Coordinates(latitude=35.11, longitude=139.22)

    first = await client.get_forecast(http_client, point)
    second = await client.get_forecast(http_client, point)

    assert first == second
    assert http_client.call_count == 1


async def test_get_forecast_refetches_after_ttl_expires():
    client = WeatherClient()
    http_client = FakeHttpClient({"current": {}, "hourly": {}})
    point = Coordinates(latitude=35.33, longitude=139.44)

    await client.get_forecast(http_client, point)

    # キャッシュの取得時刻を強制的に過去にしてTTL失効をシミュレートする
    key = (
        round(point.latitude, weather_client_module.CACHE_PRECISION),
        round(point.longitude, weather_client_module.CACHE_PRECISION),
    )
    fetched_at, data = weather_client_module._forecast_cache[key]
    weather_client_module._forecast_cache[key] = (
        fetched_at - weather_client_module.CACHE_TTL_SECONDS - 1,
        data,
    )

    await client.get_forecast(http_client, point)

    assert http_client.call_count == 2


async def test_get_forecast_returns_none_on_request_error():
    client = WeatherClient()
    point = Coordinates(latitude=35.55, longitude=139.66)

    result = await client.get_forecast(FailingHttpClient(), point)

    assert result is None


async def test_get_forecast_retries_on_429_and_recovers():
    client = WeatherClient()
    http_client = RetryThenSucceedHttpClient({"current": {}, "hourly": {}})
    point = Coordinates(latitude=35.77, longitude=139.88)

    result = await client.get_forecast(http_client, point)

    assert result == {"current": {}, "hourly": {}}
    assert http_client.call_count == 3


async def test_get_forecast_returns_none_after_exhausting_429_retries():
    client = WeatherClient()
    http_client = AlwaysTooManyRequestsHttpClient()
    point = Coordinates(latitude=35.88, longitude=139.99)

    result = await client.get_forecast(http_client, point)

    assert result is None
    # 初回 + MAX_RETRIES回の再試行 = 呼び出し合計
    assert http_client.call_count == weather_client_module.MAX_RETRIES + 1
