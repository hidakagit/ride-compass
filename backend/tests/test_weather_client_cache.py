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
