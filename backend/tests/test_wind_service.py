import asyncio
from datetime import datetime

import pytest

from app.domain.route import Coordinates
from app.domain.weather import WeatherConditions
from app.infrastructure import weather_client as weather_client_module
from app.infrastructure import wind_forecast_cache
from app.infrastructure.weather_client import WeatherClient
from app.services.weather_service import WeatherService
from app.services.wind_service import WindService

START_TIME = datetime(2026, 8, 13, 12, 0)


class _FakeRedis:
    """wind_forecast_cache.pyが使うコマンド（mget/pipeline.set）だけを実装したフェイク
    （test_road_graph_tile_cache.pyと同じパターン）。"""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def mget(self, keys):
        return [self.store.get(key) for key in keys]

    def pipeline(self, transaction=False):
        return _FakePipeline(self)


class _FakePipeline:
    def __init__(self, redis: "_FakeRedis"):
        self._redis = redis
        self._ops = []

    def set(self, key, value, ex=None):
        self._ops.append((key, value))
        return self

    async def execute(self):
        for key, value in self._ops:
            self._redis.store[key] = value


@pytest.fixture(autouse=True)
def use_fake_wind_forecast_redis(monkeypatch):
    # get_forecast_manyがwind_forecast_cache（Redis、L2、改善計画T398）へ書き込むように
    # なったため、実Redisへ繋がずテストごとに使い捨てのフェイクへ差し替える
    # （test_weather_client_cache.pyと同じ既存パターン）。
    monkeypatch.setattr(wind_forecast_cache, "get_redis_client", lambda: _FakeRedis())


def northbound_points() -> list[Coordinates]:
    # 真北に向かう3点の直線
    return [
        Coordinates(latitude=35.0, longitude=139.0),
        Coordinates(latitude=35.05, longitude=139.0),
        Coordinates(latitude=35.1, longitude=139.0),
    ]


def headwind_conditions(speed_ms: float = 5.0) -> WeatherConditions:
    # 北から吹く風＝北向き走行にとっての正面からの向かい風
    return WeatherConditions(
        temperature_c=20.0,
        apparent_temperature_c=None,
        wind_speed_ms=speed_ms,
        wind_direction_deg=0.0,
        wind_direction_label="北",
        wind_gusts_ms=None,
        precipitation_probability_percent=0.0,
        precipitation_mm=None,
        uv_index=None,
        observed_at="2026-08-13T12:00",
        weather_code=None,
        is_day=None,
        sunrise=None,
        sunset=None,
        precipitation_probability_max_percent=None,
        wind_speed_max_ms=None,
        temperature_max_c=None,
        temperature_min_c=None,
        uv_index_max=None,
        today_periods=[],
    )


class FakeWeatherService:
    def __init__(self, conditions_by_call: list):
        self._conditions = conditions_by_call
        self.calls: list[tuple[Coordinates, datetime | None]] = []
        self.prefetch_calls: list[list[Coordinates]] = []

    async def get_conditions_many(
        self, points: list[Coordinates], times: list[datetime | None]
    ) -> list[WeatherConditions | None]:
        self.calls.extend(zip(points, times))
        return self._conditions

    async def prefetch(self, points: list[Coordinates]) -> None:
        self.prefetch_calls.append(points)


async def test_constant_headwind_yields_that_wind_speed_as_score():
    weather = FakeWeatherService([headwind_conditions(5.0), headwind_conditions(5.0)])
    service = WindService(weather)

    profile = await service.get_wind_profile(northbound_points(), START_TIME)

    assert profile["wind_score"] == 5.0


async def test_returns_none_score_when_all_weather_lookups_fail():
    weather = FakeWeatherService([None, None])
    service = WindService(weather)

    profile = await service.get_wind_profile(northbound_points(), START_TIME)

    assert profile["wind_score"] is None
    assert [s["wind_penalty"] for s in profile["segments"]] == [None, None]


async def test_ignores_segments_with_missing_weather_when_scoring():
    weather = FakeWeatherService([None, headwind_conditions(4.0)])
    service = WindService(weather)

    profile = await service.get_wind_profile(northbound_points(), START_TIME)

    assert profile["wind_score"] == 4.0


async def test_first_segment_is_queried_at_start_time():
    weather = FakeWeatherService([headwind_conditions(), headwind_conditions()])
    service = WindService(weather)

    await service.get_wind_profile(northbound_points(), START_TIME)

    first_point, first_at = weather.calls[0]
    assert first_at == START_TIME


async def test_prefetch_merges_points_across_candidates_into_one_call():
    weather = FakeWeatherService([])
    service = WindService(weather)
    candidate_a = northbound_points()
    candidate_b = [Coordinates(latitude=35.0, longitude=139.5)]

    await service.prefetch([candidate_a, candidate_b])

    assert len(weather.prefetch_calls) == 1
    assert weather.prefetch_calls[0] == candidate_a + candidate_b


async def test_prefetch_skips_call_when_no_points():
    weather = FakeWeatherService([])
    service = WindService(weather)

    await service.prefetch([[], []])

    assert weather.prefetch_calls == []


class CountingHttpClient:
    """実際のOpen-Meteoリクエスト数を数える、engine想定の並列呼び出しを再現するためのfake。

    Open-Meteoは地点数が2件以上だと地点ごとの予報配列を返す（1件のみだとobject）ため、
    リクエストされた地点数ぶんpayloadを複製して返す（そうしないとget_forecast_manyの
    `zip(to_fetch, entries)`で一部の地点だけ結果が欠け、キャッシュが埋まらず後続呼び出しが
    余計なHTTPを発生させてしまい、このfake自体が実際のOpen-Meteoと違う挙動になる）。
    """

    def __init__(self, payload):
        self.call_count = 0
        self._payload = payload

    async def get(self, url, params=None, timeout=None):
        self.call_count += 1
        location_count = len(str(params["latitude"]).split(","))
        body = self._payload if location_count == 1 else [self._payload] * location_count
        return _FakeResponse(body)

    async def post(self, url, data=None, timeout=None):
        # get_forecast_many（改善計画T178フォローアップでPOSTへ変更）用。getと同じロジック。
        self.call_count += 1
        location_count = len(str(data["latitude"]).split(","))
        body = self._payload if location_count == 1 else [self._payload] * location_count
        return _FakeResponse(body)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def clear_weather_cache():
    weather_client_module._forecast_cache.clear()
    yield
    weather_client_module._forecast_cache.clear()


async def test_prefetch_collapses_concurrent_candidate_lookups_into_one_http_call():
    """openrouteservice_engine.pyが行う「候補ごとにget_wind_profileをasyncio.gather」を再現し、
    事前にprefetchしておけば候補数ぶん（本テストでは3）同時発火していたOpen-Meteoリクエストが
    実質1本に減ることを検証する（本番429常態化への対策の本丸）。"""
    payload = {
        "current": {"time": "2026-08-13T12:00", "temperature_2m": 20.0, "wind_speed_10m": 5.0, "wind_direction_10m": 0.0},
        "hourly": {
            "time": ["2026-08-13T12:00"],
            "temperature_2m": [20.0],
            "wind_speed_10m": [5.0],
            "wind_direction_10m": [0.0],
            "precipitation_probability": [0],
        },
    }
    http_client = CountingHttpClient(payload)
    weather_service = WeatherService(WeatherClient(), http_client)
    wind_service = WindService(weather_service)
    points_per_candidate = [
        northbound_points(),
        [Coordinates(latitude=35.0, longitude=139.1), Coordinates(latitude=35.05, longitude=139.1)],
        [Coordinates(latitude=35.0, longitude=139.2), Coordinates(latitude=35.05, longitude=139.2)],
    ]

    await wind_service.prefetch(points_per_candidate)
    profiles = await asyncio.gather(
        *(wind_service.get_wind_profile(points, START_TIME) for points in points_per_candidate)
    )

    assert http_client.call_count == 1
    assert all(profile["wind_score"] is not None for profile in profiles)


async def test_segments_include_per_segment_wind_penalty_and_distance():
    weather = FakeWeatherService([headwind_conditions(5.0), headwind_conditions(5.0)])
    service = WindService(weather)

    profile = await service.get_wind_profile(northbound_points(), START_TIME)

    assert len(profile["segments"]) == 2
    for segment in profile["segments"]:
        assert segment["wind_penalty"] == 5.0
        assert segment["distance_km"] > 0
        assert segment["arrival_time"] is not None
