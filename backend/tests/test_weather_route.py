from fastapi.testclient import TestClient

from app.api.routes import get_weather_service
from app.domain.weather import WeatherConditions
from app.main import app

client = TestClient(app)


class FakeWeatherService:
    def __init__(self, conditions):
        self._conditions = conditions

    async def get_conditions(self, point, at=None):
        return self._conditions


def test_get_weather_returns_conditions_on_success():
    conditions = WeatherConditions(
        temperature_c=24.6,
        wind_speed_ms=2.5,
        wind_direction_deg=69,
        wind_direction_label="東",
        precipitation_probability_percent=60,
        observed_at="2026-08-13T21:15",
    )
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(conditions)

    try:
        response = client.get("/api/weather", params={"latitude": 35.7597, "longitude": 139.7387})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["temperature_c"] == 24.6
    assert body["wind_direction_label"] == "東"


def test_get_weather_returns_502_when_unavailable():
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(None)

    try:
        response = client.get("/api/weather", params={"latitude": 35.7597, "longitude": 139.7387})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
