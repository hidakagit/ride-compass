import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_flood_service, get_warning_service, get_wbgt_service, get_weather_service
from app.config import settings
from app.domain.flood_forecast import ActiveFloodForecast
from app.domain.jma_warning import ActiveWarning
from app.domain.weather import WeatherConditions, WeatherPeriodOutlook
from app.infrastructure import rate_limiter
from app.main import app
from app.services.flood_service import FloodForecasts
from app.services.warning_service import WeatherWarnings
from app.services.wbgt_service import WbgtStatus

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_rate_limiter():
    # rate_limiterはプロセス内グローバルの固定窓カウンタのため、テスト間で
    # 消し込まないと前のテストのリクエストが今のテストの上限に食い込む。
    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


class FakeWeatherService:
    def __init__(self, conditions, wind_grid=None, wind_times=None):
        self._conditions = conditions
        self._wind_grid = wind_grid if wind_grid is not None else []
        self._wind_times = wind_times if wind_times is not None else []

    async def get_conditions(self, point, at=None):
        return self._conditions

    async def get_wind_grid(self, points):
        return self._wind_times, self._wind_grid


def test_get_weather_returns_conditions_on_success():
    conditions = WeatherConditions(
        temperature_c=24.6,
        wind_speed_ms=2.5,
        wind_direction_deg=69,
        wind_direction_label="東",
        precipitation_mm=0.5,
        observed_at="2026-08-13T21:15",
        weather_code=2,
        is_day=1,
        sunrise="2026-08-13T05:12",
        sunset="2026-08-13T18:41",
        wind_speed_max_ms=5.5,
        temperature_max_c=29.0,
        precipitation_max_mm=None,
        temperature_min_c=23.0,
        today_periods=[
            WeatherPeriodOutlook(period="12:00", weather_code=2, temperature_c=27.0, precipitation_mm=0.4),
        ],
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


def test_get_weather_is_rate_limited_per_client():
    conditions = WeatherConditions(
        temperature_c=24.6,
        wind_speed_ms=2.5,
        wind_direction_deg=69,
        wind_direction_label="東",
        precipitation_mm=0.5,
        observed_at="2026-08-13T21:15",
        weather_code=2,
        is_day=1,
        sunrise="2026-08-13T05:12",
        sunset="2026-08-13T18:41",
        wind_speed_max_ms=5.5,
        temperature_max_c=29.0,
        precipitation_max_mm=None,
        temperature_min_c=23.0,
        today_periods=[
            WeatherPeriodOutlook(period="12:00", weather_code=2, temperature_c=27.0, precipitation_mm=0.4),
        ],
    )
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(conditions)

    try:
        for _ in range(settings.weather_rate_limit_per_minute - 1):
            rate_limiter.check_rate_limit("weather:testclient", settings.weather_rate_limit_per_minute)
        params = {"latitude": 35.7597, "longitude": 139.7387}
        assert client.get("/api/weather", params=params).status_code == 200
        response = client.get("/api/weather", params={"latitude": 35.7597, "longitude": 139.7387})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429


def test_get_wind_grid_returns_points_on_success():
    from app.domain.wind_grid import WindGridPoint

    grid = [
        WindGridPoint(
            latitude=35.68,
            longitude=139.77,
            wind_speed_ms=[2.5, 3.1],
            wind_direction_deg=[90.0, 95.0],
            precipitation_mm=[0.0, 0.5],
        )
    ]
    times = ["2026-08-20T12:00", "2026-08-20T13:00"]
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(None, wind_grid=grid, wind_times=times)

    try:
        response = client.get("/api/weather/wind-grid")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    # 改善計画T203: 時刻配列はpoints各点からは外れ、応答トップレベルに1本だけ持つ。
    assert body["times"] == times
    assert len(body["points"]) == 1
    assert body["points"][0]["latitude"] == 35.68
    assert body["points"][0]["wind_speed_ms"] == [2.5, 3.1]
    assert body["points"][0]["precipitation_mm"] == [0.0, 0.5]


def test_get_wind_grid_omits_none_points():
    from app.domain.wind_grid import WindGridPoint

    grid = [
        WindGridPoint(
            latitude=35.68,
            longitude=139.77,
            wind_speed_ms=[2.5],
            wind_direction_deg=[90.0],
            precipitation_mm=[0.0],
        ),
        None,
    ]
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(
        None, wind_grid=grid, wind_times=["2026-08-20T12:00"]
    )

    try:
        response = client.get("/api/weather/wind-grid")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(response.json()["points"]) == 1


def test_get_wind_grid_returns_502_when_all_points_fail():
    # 改善計画T200（統合レビュー2026-08-22指摘）: 以前は全地点失敗でも空リスト+200 OKを
    # 返しており、フロントがエラーと判定できなかった。WeatherService.get_wind_gridの
    # 実契約どおり、pointsと同じ長さの全Noneを返すfakeで再現する。
    from app.domain.wind_grid import generate_wind_grid_points

    point_count = len(generate_wind_grid_points())
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(None, wind_grid=[None] * point_count)

    try:
        response = client.get("/api/weather/wind-grid")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    assert response.json()["detail"] == "気象データの取得に失敗しました"


def test_get_wind_grid_is_rate_limited_per_client():
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(None, wind_grid=[])

    try:
        for _ in range(settings.wind_grid_rate_limit_per_minute - 1):
            rate_limiter.check_rate_limit("wind-grid:testclient", settings.wind_grid_rate_limit_per_minute)
        assert client.get("/api/weather/wind-grid").status_code == 200
        response = client.get("/api/weather/wind-grid")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429


# 改善計画T180: 詳細格子（wind-grid-detail、ヒートマップ等の面表現用）。


def test_get_wind_grid_detail_returns_points_on_success():
    from app.domain.wind_grid import WindGridPoint

    grid = [
        WindGridPoint(
            latitude=35.68,
            longitude=139.77,
            wind_speed_ms=[2.5],
            wind_direction_deg=[90.0],
            precipitation_mm=[0.0],
        )
    ]
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(
        None, wind_grid=grid, wind_times=["2026-08-20T12:00"]
    )

    try:
        response = client.get(
            "/api/weather/wind-grid-detail",
            params={"min_lon": 139.70, "min_lat": 35.60, "max_lon": 139.90, "max_lat": 35.80},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert len(body["points"]) == 1
    assert body["points"][0]["latitude"] == 35.68


def test_get_wind_grid_detail_omits_none_points():
    from app.domain.wind_grid import WindGridPoint

    grid = [
        WindGridPoint(
            latitude=35.68,
            longitude=139.77,
            wind_speed_ms=[2.5],
            wind_direction_deg=[90.0],
            precipitation_mm=[0.0],
        ),
        None,
    ]
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(
        None, wind_grid=grid, wind_times=["2026-08-20T12:00"]
    )

    try:
        response = client.get(
            "/api/weather/wind-grid-detail",
            params={"min_lon": 139.70, "min_lat": 35.60, "max_lon": 139.90, "max_lat": 35.80},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(response.json()["points"]) == 1


def test_get_wind_grid_detail_returns_502_when_all_points_fail():
    # 改善計画T200。wind-gridと同じ全滅ガードがwind-grid-detailにも適用されること。
    from app.domain.wind_grid import generate_wind_grid_detail_points

    bbox = (139.70, 35.60, 139.90, 35.80)
    point_count = len(generate_wind_grid_detail_points(bbox))
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(None, wind_grid=[None] * point_count)

    try:
        response = client.get(
            "/api/weather/wind-grid-detail",
            params={"min_lon": bbox[0], "min_lat": bbox[1], "max_lon": bbox[2], "max_lat": bbox[3]},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    assert response.json()["detail"] == "気象データの取得に失敗しました"


def test_get_wind_grid_detail_rejects_inverted_bbox():
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(None, wind_grid=[])

    try:
        response = client.get(
            "/api/weather/wind-grid-detail",
            params={"min_lon": 140.0, "min_lat": 35.80, "max_lon": 139.70, "max_lat": 35.60},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400


def test_get_wind_grid_detail_rejects_bbox_too_large():
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(None, wind_grid=[])

    try:
        # WIND_GRID_BBOX全域を渡すと詳細間隔（0.02度）ではWIND_GRID_DETAIL_MAX_POINTSを
        # 大幅に超える点数になるはず。
        response = client.get(
            "/api/weather/wind-grid-detail",
            params={"min_lon": 138.35, "min_lat": 34.85, "max_lon": 140.95, "max_lat": 37.20},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400


# T185: ズーム依存でspacing_degを細かくする拡張（実機フィードバック「拡大率が大きいと
# gridFillの格子がゴワゴワして気になる」）。


def test_get_wind_grid_detail_spacing_deg_defaults_to_02_when_omitted():
    # spacing_degを省略したとき（既存クライアント・後方互換）と、明示的にWIND_GRID_DETAIL_
    # SPACING_DEG(0.02)を渡したときとで、生成される格子点数が一致することを確認する。
    captured_points = {}

    class RecordingFakeWeatherService(FakeWeatherService):
        async def get_wind_grid(self, points):
            captured_points["count"] = len(points)
            return [], []

    app.dependency_overrides[get_weather_service] = lambda: RecordingFakeWeatherService(None)
    params = {"min_lon": 139.70, "min_lat": 35.70, "max_lon": 139.80, "max_lat": 35.80}

    try:
        omitted = client.get("/api/weather/wind-grid-detail", params=params)
        omitted_count = captured_points["count"]
        explicit = client.get("/api/weather/wind-grid-detail", params={**params, "spacing_deg": 0.02})
        explicit_count = captured_points["count"]
    finally:
        app.dependency_overrides.clear()

    assert omitted.status_code == 200
    assert explicit.status_code == 200
    assert omitted_count == explicit_count
    assert omitted_count > 0


def test_get_wind_grid_detail_accepts_finer_allowed_spacing_deg():
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(None, wind_grid=[])

    try:
        response = client.get(
            "/api/weather/wind-grid-detail",
            params={"min_lon": 139.70, "min_lat": 35.70, "max_lon": 139.72, "max_lat": 35.72, "spacing_deg": 0.005},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200


def test_get_wind_grid_detail_rejects_spacing_deg_outside_allowed_set():
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(None, wind_grid=[])

    try:
        response = client.get(
            "/api/weather/wind-grid-detail",
            params={"min_lon": 139.70, "min_lat": 35.70, "max_lon": 139.72, "max_lat": 35.72, "spacing_deg": 0.03},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400


def test_get_wind_grid_detail_rejects_bbox_too_large_for_finer_spacing_deg_even_when_ok_at_default():
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(None, wind_grid=[])
    # 0.02°間隔なら十分小さい(0.4°四方=21x21=441点)bboxでも、0.0025°間隔だと
    # 161x161=25921点相当になりWIND_GRID_DETAIL_MAX_POINTSを大幅に超える。
    params = {"min_lon": 139.70, "min_lat": 35.70, "max_lon": 140.10, "max_lat": 36.10}

    try:
        ok = client.get("/api/weather/wind-grid-detail", params={**params, "spacing_deg": 0.02})
        too_fine = client.get("/api/weather/wind-grid-detail", params={**params, "spacing_deg": 0.0025})
    finally:
        app.dependency_overrides.clear()

    assert ok.status_code == 200
    assert too_fine.status_code == 400


class FakeWarningService:
    def __init__(self, warnings: WeatherWarnings):
        self._warnings = warnings

    async def get_warnings(self, point):
        return self._warnings


def test_get_weather_warnings_returns_warnings_on_success():
    warnings = WeatherWarnings(
        area_name="東京地方",
        report_datetime="2026-08-22T18:09:00+09:00",
        warnings=[ActiveWarning(code="14", name="雷注意報", level="advisory", additions=["竜巻"])],
    )
    app.dependency_overrides[get_warning_service] = lambda: FakeWarningService(warnings)

    try:
        response = client.get("/api/weather/warnings", params={"latitude": 35.6812, "longitude": 139.7671})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["area_name"] == "東京地方"
    assert body["warnings"][0]["code"] == "14"
    assert body["warnings"][0]["additions"] == ["竜巻"]


def test_get_weather_warnings_returns_empty_without_error_on_failure():
    # 改善計画T205完了条件「取得失敗時は警告なし」。502ではなく空のwarningsで200を返す
    # （wind-grid系の全滅502ガード、T200とは意図的に異なる方針）。
    app.dependency_overrides[get_warning_service] = lambda: FakeWarningService(
        WeatherWarnings(area_name=None, report_datetime=None, warnings=[])
    )

    try:
        response = client.get("/api/weather/warnings", params={"latitude": 35.6812, "longitude": 139.7671})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"area_name": None, "report_datetime": None, "warnings": []}


def test_get_weather_warnings_is_rate_limited_per_client():
    empty = WeatherWarnings(area_name=None, report_datetime=None, warnings=[])
    app.dependency_overrides[get_warning_service] = lambda: FakeWarningService(empty)
    params = {"latitude": 35.6812, "longitude": 139.7671}

    try:
        for _ in range(settings.weather_warnings_rate_limit_per_minute - 1):
            rate_limiter.check_rate_limit(
                "weather-warnings:testclient", settings.weather_warnings_rate_limit_per_minute
            )
        assert client.get("/api/weather/warnings", params=params).status_code == 200
        response = client.get("/api/weather/warnings", params=params)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429


def test_get_wind_grid_detail_is_rate_limited_per_client():
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(None, wind_grid=[])
    params = {"min_lon": 139.70, "min_lat": 35.60, "max_lon": 139.90, "max_lat": 35.80}

    try:
        for _ in range(settings.wind_grid_detail_rate_limit_per_minute - 1):
            rate_limiter.check_rate_limit(
                "wind-grid-detail:testclient", settings.wind_grid_detail_rate_limit_per_minute
            )
        assert client.get("/api/weather/wind-grid-detail", params=params).status_code == 200
        response = client.get("/api/weather/wind-grid-detail", params=params)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429


class FakeWbgtService:
    def __init__(self, status: WbgtStatus):
        self._status = status

    async def get_status(self, point, now=None):
        return self._status


def test_get_wbgt_returns_status_on_success():
    status = WbgtStatus(level="severe_warning", label="厳重警戒", value=30.0, observed_at="2026/08/22 18:00:00")
    app.dependency_overrides[get_wbgt_service] = lambda: FakeWbgtService(status)

    try:
        response = client.get("/api/weather/wbgt", params={"latitude": 35.6812, "longitude": 139.7671})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["level"] == "severe_warning"
    assert body["value"] == 30.0


def test_get_wbgt_returns_empty_without_error_on_failure_or_offseason():
    # 改善計画T174完了条件「取得失敗時は警告なし」「提供期間外は何も出ない」。
    # 502ではなく空のlevel=Noneで200を返す（T205のwarningsエンドポイントと同じfail-open方針）。
    app.dependency_overrides[get_wbgt_service] = lambda: FakeWbgtService(
        WbgtStatus(level=None, label=None, value=None, observed_at=None)
    )

    try:
        response = client.get("/api/weather/wbgt", params={"latitude": 35.6812, "longitude": 139.7671})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"level": None, "label": None, "value": None, "observed_at": None}


def test_get_wbgt_is_rate_limited_per_client():
    empty = WbgtStatus(level=None, label=None, value=None, observed_at=None)
    app.dependency_overrides[get_wbgt_service] = lambda: FakeWbgtService(empty)
    params = {"latitude": 35.6812, "longitude": 139.7671}

    try:
        for _ in range(settings.weather_wbgt_rate_limit_per_minute - 1):
            rate_limiter.check_rate_limit("weather-wbgt:testclient", settings.weather_wbgt_rate_limit_per_minute)
        assert client.get("/api/weather/wbgt", params=params).status_code == 200
        response = client.get("/api/weather/wbgt", params=params)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429


class FakeFloodService:
    def __init__(self, forecasts: FloodForecasts):
        self._forecasts = forecasts

    async def get_forecasts(self, point):
        return self._forecasts


def test_get_flood_forecast_returns_forecasts_on_success():
    forecasts = FloodForecasts(
        forecasts=[
            ActiveFloodForecast(
                river_code="830304004400",
                river_name="神田川",
                level=4,
                badge_level="severe_warning",
                label="神田川氾濫危険警報",
                condition="レベル４氾濫危険警報（発表）",
                report_datetime="2026-08-22T17:50:00+09:00",
            )
        ]
    )
    app.dependency_overrides[get_flood_service] = lambda: FakeFloodService(forecasts)

    try:
        response = client.get("/api/weather/flood-forecast", params={"latitude": 35.6812, "longitude": 139.7671})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["forecasts"][0]["river_name"] == "神田川"
    assert body["forecasts"][0]["badge_level"] == "severe_warning"


def test_get_flood_forecast_returns_empty_without_error_on_failure():
    # 改善計画T212完了条件「取得失敗時は警告なし」。502ではなく空配列で200を返す
    # （T205/T174と同じfail-open方針）。
    app.dependency_overrides[get_flood_service] = lambda: FakeFloodService(FloodForecasts(forecasts=[]))

    try:
        response = client.get("/api/weather/flood-forecast", params={"latitude": 35.6812, "longitude": 139.7671})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"forecasts": []}


def test_get_flood_forecast_is_rate_limited_per_client():
    empty = FloodForecasts(forecasts=[])
    app.dependency_overrides[get_flood_service] = lambda: FakeFloodService(empty)
    params = {"latitude": 35.6812, "longitude": 139.7671}

    try:
        for _ in range(settings.weather_flood_forecast_rate_limit_per_minute - 1):
            rate_limiter.check_rate_limit(
                "weather-flood-forecast:testclient", settings.weather_flood_forecast_rate_limit_per_minute
            )
        assert client.get("/api/weather/flood-forecast", params=params).status_code == 200
        response = client.get("/api/weather/flood-forecast", params=params)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429


def test_get_wind_grid_sets_cache_control():
    # 風グリッドは約48時間ぶんの時刻配列を持ち、上流（Open-Meteo）の更新は1時間ごとの
    # ため、数分の再利用で表示が古くならない。URLに時刻を含まないためimmutableにはしない。
    from app.domain.wind_grid import WindGridPoint

    grid = [
        WindGridPoint(
            latitude=35.68,
            longitude=139.77,
            wind_speed_ms=[2.5],
            wind_direction_deg=[90.0],
            precipitation_mm=[0.0],
        )
    ]
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(
        None, wind_grid=grid, wind_times=["2026-08-20T12:00"]
    )

    try:
        response = client.get("/api/weather/wind-grid")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300"
    assert "immutable" not in response.headers["cache-control"]


def test_get_wind_grid_does_not_cache_total_failure():
    # 全地点失敗（502）はキャッシュさせず次のリクエストで取り直させる。
    from app.domain.wind_grid import generate_wind_grid_points

    point_count = len(generate_wind_grid_points())
    app.dependency_overrides[get_weather_service] = lambda: FakeWeatherService(None, wind_grid=[None] * point_count)

    try:
        response = client.get("/api/weather/wind-grid")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    assert "cache-control" not in response.headers
