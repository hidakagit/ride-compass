"""`api/routers/weather.py`——天気・警報・暑さ指数・洪水予報・アメダスと、風の格子の経路。

経路ごとに受け渡し（サービスの答えが応答に出ること・回数制限）を1本ずつ通し、ルーターが自分で持つ判断
（取れなかったら502・格子が読めなければ502・対象範囲が読めなければ502・表示範囲・間隔・点の数で断る）を見る。
サービスと対象範囲（`get_ingested_area`）は依存の差し替えで与える。

ここで見ないもの:
- 予報・警報・暑さ指数・洪水予報・アメダスを取って組み立てること、格子が読めないことを None にすること
  → 各サービスのテスト（`test_weather_service.py`・`test_warning_service.py`・`test_wbgt_service.py`・
  `test_flood_service.py`・`test_jma_amedas_service.py`）
- 格子点の位置と数え方 → `test_wind_grid.py`
- 対象範囲を読むこと → `test_ingested_area.py`
- 回数制限の窓 → `test_rate_limiter.py`
- Cache-Control の値と、失敗の応答に付けないこと → `test_cache_policy.py`
- 範囲外の緯度経度・有限でない間隔を断ること（`domain/geo.py: Latitude`・`Longitude` と `Query` の制約で、FastAPI が422で返す）
- 点の数で断るときに格子の風を読みに行かないこと——読む先は手元に同期した予報のファイル（`infrastructure/msm_client.py`）で、
  回数・課金の約束が無い読むだけの呼び出し。作る前に断る理由（点を作る処理がイベントループを止める）は実装のコメントが持つ
"""

import math
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_amedas_service,
    get_flood_service,
    get_ingested_area,
    get_warning_service,
    get_wbgt_service,
    get_weather_service,
)
from app.config import settings
from app.domain.flood_forecast import ActiveFloodForecast
from app.domain.jma_amedas import AmedasObservation, WindDirection
from app.domain.jma_warning import ActiveWarning
from app.domain.region import BoundingBox
from app.domain.time_zone import JST
from app.domain.twilight import Twilight
from app.domain.weather import TemperatureRange, WeatherConditions, WeatherPeriodOutlook
from app.domain.wind_grid import (
    WIND_GRID_DETAIL_MAX_POINTS,
    WIND_GRID_DETAIL_MIN_SPACING_DEG,
    WindGridPoint,
    WindGridResponse,
    generate_wind_grid_detail_points,
    generate_wind_grid_points,
)
from app.infrastructure import rate_limiter
from app.main import app
from app.services.flood_service import FloodForecasts
from app.services.warning_service import WeatherWarnings
from app.services.wbgt_service import WbgtReading, WbgtStatus

client = TestClient(app)

#: 格子を敷く対象範囲。本物はDBの取込の記録から読む（`get_ingested_area`）ので、ここではテストが与える。
AREA = BoundingBox(min_latitude=34.9, min_longitude=138.4, max_latitude=37.2, max_longitude=140.9)
#: 対象範囲の内側の表示範囲。
VIEW = {"min_lon": 139.70, "min_lat": 35.60, "max_lon": 139.90, "max_lat": 35.80}
POINT = {"latitude": 35.6812, "longitude": 139.7671}
TIMES = ["2026-08-20T12:00", "2026-08-20T13:00"]
GRID_POINT = WindGridPoint(
    latitude=35.68, longitude=139.77, wind_speed_ms=[2.5, 3.1], wind_direction_deg=[90.0, 95.0],
    precipitation_mm=[0.0, 0.5],
)

CONDITIONS = WeatherConditions(
    precipitation_mm=0.5,
    twilight=Twilight(sunrise="2026-08-13T05:12", sunset="2026-08-13T18:41"),
    wind_speed_max_ms=5.5,
    precipitation_max_mm=None,
    temperature_range=TemperatureRange(min_c=23.0, max_c=29.0),
    today_period_interval_hours=2,
    today_periods=[WeatherPeriodOutlook(period="12:00", temperature_c=27.0, precipitation_mm=0.4)],
)
WARNINGS = WeatherWarnings(
    warnings=[ActiveWarning(code="14", name="雷注意報", level="advisory", additions=["竜巻"])],
)
WBGT = WbgtStatus(
    reading=WbgtReading(level="severe_warning", label="厳重警戒", value=30.0)
)
FLOODS = FloodForecasts(
    forecasts=[
        ActiveFloodForecast(
            river_code="830304004400",
            badge_level="severe_warning",
            label="神田川氾濫危険警報",
            condition="レベル４氾濫危険警報（発表）",
        )
    ]
)
AMEDAS = AmedasObservation(
    station_name="東京",
    observed_at=datetime(2026, 8, 29, 12, 0, tzinfo=JST),
    temperature_c=26.5,
    apparent_temperature_c=27.8,
    wind_speed_ms=3.5,
    wind_direction=WindDirection(deg=180.0, label="南"),
    precipitation_10min_mm=0.0,
    twilight=Twilight(sunrise="2026-08-29T05:12:00+09:00", sunset="2026-08-29T18:41:00+09:00"),
    weather_code=0,
)

#: 地点を問う経路と、そのサービスの依存・取れたときの答え。
POINT_ROUTES = [
    ("/api/weather", get_weather_service, CONDITIONS),
    ("/api/weather/warnings", get_warning_service, WARNINGS),
    ("/api/weather/wbgt", get_wbgt_service, WBGT),
    ("/api/weather/flood-forecast", get_flood_service, FLOODS),
    ("/api/weather/amedas", get_amedas_service, AMEDAS),
]


def _box(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> BoundingBox:
    return BoundingBox(min_latitude=min_lat, min_longitude=min_lon, max_latitude=max_lat, max_longitude=max_lon)


class FakeService:
    """天気の各サービスの代役。地点を問う口は与えた答えを返す。格子の口は受け取った点を残し、
    `grid_point` 1点の格子を返す（`grid_point` が None なら読めなかった格子）。"""

    def __init__(self, answer=None, grid_point=None):
        self._answer = answer
        self._grid_point = grid_point
        self.received = []

    async def get_conditions(self, point, at=None):
        return self._answer

    async def get_warnings(self, point):
        return self._answer

    async def get_status(self, point, now):
        return self._answer

    async def get_forecasts(self, point):
        return self._answer

    async def get_nearest_observation(self, point):
        return self._answer

    async def get_wind_grid(self, points):
        self.received.append(points)
        return None if self._grid_point is None else WindGridResponse(
            times=[datetime.fromisoformat(t) for t in TIMES], points=[self._grid_point]
        )


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    """テストが足した依存の差し替えを、抜けるときに片付ける。"""
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def ingested_area():
    """風の格子を敷く対象範囲（`AREA`）。"""
    app.dependency_overrides[get_ingested_area] = lambda: AREA


def _serve_weather(service: FakeService) -> FakeService:
    app.dependency_overrides[get_weather_service] = lambda: service
    return service


@pytest.mark.parametrize(("path", "dependency", "answer"), POINT_ROUTES)
def test_a_point_route_returns_what_its_source_answered(path, dependency, answer):
    app.dependency_overrides[dependency] = lambda: FakeService(answer)

    response = client.get(path, params=POINT)

    assert response.status_code == 200
    assert response.json() == answer.model_dump(mode="json")


@pytest.mark.parametrize(("path", "dependency", "detail"), [
    ("/api/weather", get_weather_service, "天候情報の取得に失敗しました"),
    ("/api/weather/warnings", get_warning_service, "取得できませんでした。"),
    ("/api/weather/wbgt", get_wbgt_service, "取得できませんでした。"),
    ("/api/weather/flood-forecast", get_flood_service, "取得できませんでした。"),
    ("/api/weather/amedas", get_amedas_service, "アメダス観測値の取得に失敗しました"),
])
def test_a_source_that_could_not_be_obtained_is_a_failure_not_an_empty_answer(path, dependency, detail):
    """空の応答は「出ていない」を表す。取れなかったことを同じ空で返すと、画面は出ていないと見せる。"""
    app.dependency_overrides[dependency] = lambda: FakeService(None)

    response = client.get(path, params=POINT)

    assert response.status_code == 502
    assert response.json() == {"detail": detail}


@pytest.mark.parametrize(("path", "params", "dependency", "answer", "key", "limit"), [
    ("/api/weather", POINT, get_weather_service, CONDITIONS, "weather", settings.weather_rate_limit_per_minute),
    (
        "/api/weather/warnings", POINT, get_warning_service, WARNINGS,
        "weather-warnings", settings.weather_warnings_rate_limit_per_minute,
    ),
    ("/api/weather/wbgt", POINT, get_wbgt_service, WBGT, "weather-wbgt", settings.weather_wbgt_rate_limit_per_minute),
    (
        "/api/weather/flood-forecast", POINT, get_flood_service, FLOODS,
        "weather-flood-forecast", settings.weather_flood_forecast_rate_limit_per_minute,
    ),
    ("/api/weather/amedas", POINT, get_amedas_service, AMEDAS, "amedas", settings.weather_amedas_rate_limit_per_minute),
    ("/api/weather/wind-grid", {}, get_weather_service, None, "wind-grid", settings.wind_grid_rate_limit_per_minute),
    (
        "/api/weather/wind-grid-detail", VIEW, get_weather_service, None,
        "wind-grid-detail", settings.wind_grid_detail_rate_limit_per_minute,
    ),
])
def test_each_route_is_rate_limited_per_client(ingested_area, path, params, dependency, answer, key, limit):
    app.dependency_overrides[dependency] = lambda: FakeService(answer, grid_point=GRID_POINT)
    for _ in range(limit - 1):
        rate_limiter.check_rate_limit(f"{key}:testclient", limit)

    assert client.get(path, params=params).status_code == 200
    assert client.get(path, params=params).status_code == 429


def test_the_wind_grid_covers_the_area_and_returns_what_was_read(ingested_area):
    service = _serve_weather(FakeService(grid_point=GRID_POINT))

    response = client.get("/api/weather/wind-grid")

    assert response.status_code == 200
    assert service.received == [generate_wind_grid_points(AREA)]
    assert response.json() == {"times": TIMES, "points": [GRID_POINT.model_dump(mode="json")]}


def test_the_detail_grid_covers_the_view_at_the_spacing_and_returns_what_was_read(ingested_area):
    view = {"min_lon": 139.70, "min_lat": 35.70, "max_lon": 139.72, "max_lat": 35.72}
    service = _serve_weather(FakeService(grid_point=GRID_POINT))

    response = client.get("/api/weather/wind-grid-detail", params={**view, "spacing_deg": 0.003})

    assert response.status_code == 200
    assert service.received == [generate_wind_grid_detail_points(AREA, _box(*view.values()), 0.003)]
    assert response.json() == {"times": TIMES, "points": [GRID_POINT.model_dump(mode="json")]}


@pytest.mark.parametrize(("path", "params"), [("/api/weather/wind-grid", {}), ("/api/weather/wind-grid-detail", VIEW)])
def test_a_grid_that_could_not_be_read_is_a_failure(ingested_area, path, params):
    """格子が読めない（数値予報の同期が済んでいない等）のを空の格子で返すと、画面は風が無いのと区別できない。"""
    _serve_weather(FakeService(grid_point=None))

    response = client.get(path, params=params)

    assert response.status_code == 502
    assert response.json()["detail"] == "気象データの取得に失敗しました"


@pytest.mark.parametrize(("path", "params"), [("/api/weather/wind-grid", {}), ("/api/weather/wind-grid-detail", VIEW)])
def test_the_grid_is_a_failure_when_the_area_cannot_be_read(path, params):
    """対象範囲が読めない（DB障害・道路を未取込）ときは格子を組めない。空の格子で返すと、画面は風が無いのと区別できない。"""
    _serve_weather(FakeService(grid_point=GRID_POINT))
    app.dependency_overrides[get_ingested_area] = lambda: None

    response = client.get(path, params=params)

    assert response.status_code == 502
    assert response.json()["detail"] == "対象範囲を読めませんでした"


def test_the_detail_grid_rejects_an_inverted_view(ingested_area):
    _serve_weather(FakeService(grid_point=GRID_POINT))

    response = client.get(
        "/api/weather/wind-grid-detail", params={"min_lon": 140.0, "min_lat": 35.80, "max_lon": 139.70, "max_lat": 35.60}
    )

    assert response.status_code == 400


def test_the_detail_grid_rejects_a_spacing_below_the_lower_bound(ingested_area):
    _serve_weather(FakeService(grid_point=GRID_POINT))

    response = client.get(
        "/api/weather/wind-grid-detail",
        params={**VIEW, "spacing_deg": math.nextafter(WIND_GRID_DETAIL_MIN_SPACING_DEG, 0)},
    )

    assert response.status_code == 400


@pytest.mark.parametrize(("extra_columns", "expected_status"), [(0, 200), (1, 400)])
def test_the_detail_grid_accepts_exactly_the_max_points_and_rejects_one_more(ingested_area, extra_columns, expected_status):
    # 1行×上限ちょうどの列の範囲。端を格子点の中間に置き、浮動小数の誤差で列数が揺れないようにする。
    # 数え始めは対象範囲の内側の格子線（格子は緯度・経度0度から数える）。
    spacing = WIND_GRID_DETAIL_MIN_SPACING_DEG
    _serve_weather(FakeService(grid_point=GRID_POINT))

    response = client.get(
        "/api/weather/wind-grid-detail",
        params={
            "min_lon": AREA.min_longitude + 0.5 * spacing,
            "min_lat": AREA.min_latitude + 100.2 * spacing,
            "max_lon": AREA.min_longitude + (WIND_GRID_DETAIL_MAX_POINTS - 1 + extra_columns + 0.5) * spacing,
            "max_lat": AREA.min_latitude + 100.8 * spacing,
            "spacing_deg": spacing,
        },
    )

    assert response.status_code == expected_status
