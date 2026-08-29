import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_amedas_service
from app.config import settings
from app.domain.jma_amedas import AmedasObservation
from app.infrastructure import rate_limiter
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_rate_limiter():
    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


class FakeAmedasService:
    def __init__(self, observation):
        self._observation = observation

    async def get_nearest_observation(self, point):
        return self._observation


SAMPLE = AmedasObservation(
    station_id="44132",
    station_name="東京",
    latitude=35.69,
    longitude=139.76,
    observed_at="2026-08-29T12:00:00+09:00",
    temperature_c=26.5,
    apparent_temperature_c=27.8,
    wind_speed_ms=3.5,
    wind_direction_deg=180.0,
    wind_direction_label="南",
    precipitation_10min_mm=0.0,
)


def test_get_amedas_returns_observation_on_success():
    app.dependency_overrides[get_amedas_service] = lambda: FakeAmedasService(SAMPLE)
    try:
        response = client.get("/api/weather/amedas", params={"latitude": 35.68, "longitude": 139.76})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["station_name"] == "東京"
    assert body["wind_direction_label"] == "南"


def test_get_amedas_returns_502_when_unavailable():
    app.dependency_overrides[get_amedas_service] = lambda: FakeAmedasService(None)
    try:
        response = client.get("/api/weather/amedas", params={"latitude": 35.68, "longitude": 139.76})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502


def test_get_amedas_is_rate_limited_per_client():
    app.dependency_overrides[get_amedas_service] = lambda: FakeAmedasService(SAMPLE)
    try:
        for _ in range(settings.weather_amedas_rate_limit_per_minute - 1):
            rate_limiter.check_rate_limit("amedas:testclient", settings.weather_amedas_rate_limit_per_minute)
        response = client.get("/api/weather/amedas", params={"latitude": 35.68, "longitude": 139.76})
        assert response.status_code == 200
        response = client.get("/api/weather/amedas", params={"latitude": 35.68, "longitude": 139.76})
        assert response.status_code == 429
    finally:
        app.dependency_overrides.clear()
