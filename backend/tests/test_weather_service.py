from datetime import datetime

from app.domain.route import Coordinates
from app.domain.weather import WeatherPeriodOutlook
from app.infrastructure.weather_client import WeatherClient
from app.services.weather_service import WeatherService

POINT = Coordinates(latitude=35.7597, longitude=139.7387)
OTHER_POINT = Coordinates(latitude=35.1, longitude=139.1)

SAMPLE_DATA = {
    "current": {
        "time": "2026-08-13T21:15",
        "temperature_2m": 24.6,
        "wind_speed_10m": 2.5,
        "wind_direction_10m": 69,
        "apparent_temperature": 27.1,
        "wind_gusts_10m": 4.8,
        "precipitation": 0.2,
        "uv_index": 0.0,
        "weather_code": 3,
        "is_day": 0,
    },
    # 改善計画T385フォローアップ:「今日の見通し」の天気の流れ（_period_outlooks、
    # 06:00〜20:00の2時間おき8コマ）を意味のある値で検証するため、時刻範囲を当日06:00まで
    # 拡張し、weather_code/is_dayを追加した（従来の20:00〜23:00の4点は既存テストの期待値と
    # 一致するようそのまま維持）。
    "hourly": {
        "time": [
            "2026-08-13T06:00",
            "2026-08-13T08:00",
            "2026-08-13T10:00",
            "2026-08-13T12:00",
            "2026-08-13T14:00",
            "2026-08-13T16:00",
            "2026-08-13T18:00",
            "2026-08-13T20:00",
            "2026-08-13T21:00",
            "2026-08-13T22:00",
            "2026-08-13T23:00",
        ],
        "temperature_2m": [22.0, 24.0, 26.5, 28.5, 29.0, 27.5, 26.0, 25.0, 24.5, 24.0, 23.8],
        "wind_speed_10m": [2.0, 2.2, 2.5, 2.8, 3.0, 2.9, 2.7, 3.0, 2.8, 2.5, 2.2],
        "wind_direction_10m": [50, 55, 58, 60, 62, 63, 61, 60, 65, 70, 75],
        "precipitation_probability": [10, 15, 20, 30, 40, 45, 50, 50, 60, 70, 80],
        "apparent_temperature": [22.5, 24.5, 27.0, 29.5, 30.0, 28.0, 26.5, 27.5, 27.1, 26.6, 26.0],
        "wind_gusts_10m": [3.0, 3.2, 3.8, 4.5, 5.0, 4.8, 4.5, 5.5, 4.8, 4.2, 3.9],
        "precipitation": [0.0, 0.0, 0.0, 0.1, 0.2, 0.2, 0.3, 0.3, 0.2, 0.1, 0.0],
        "uv_index": [0.5, 2.0, 4.5, 6.5, 7.0, 5.0, 2.5, 1.0, 0.0, 0.0, 0.0],
        "weather_code": [1, 1, 2, 2, 3, 3, 61, 3, 3, 3, 3],
        "is_day": [0, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0],
    },
    # 改善計画T385:「今日の見通し」パネル用（forecast_days=2、index0=今日）。
    "daily": {
        "time": ["2026-08-13", "2026-08-14"],
        "sunset": ["2026-08-13T18:41", "2026-08-14T18:40"],
        "precipitation_probability_max": [80, 60],
        "wind_speed_10m_max": [5.5, 4.0],
        "temperature_2m_max": [29.0, 28.0],
        "temperature_2m_min": [23.0, 22.5],
        "uv_index_max": [7.0, 6.5],
    },
}

# 改善計画T172でパラメータを追加する前のキャッシュ応答を想定した、新フィールドを持たない
# データ（stale cache・Open-Meteo側の一時的な欠落を模す）。graceful Noneフォールバックの検証用。
SAMPLE_DATA_WITHOUT_T172_FIELDS = {
    "current": {
        "time": "2026-08-13T21:15",
        "temperature_2m": 24.6,
        "wind_speed_10m": 2.5,
        "wind_direction_10m": 69,
    },
    "hourly": {
        "time": ["2026-08-13T20:00", "2026-08-13T21:00", "2026-08-13T22:00", "2026-08-13T23:00"],
        "temperature_2m": [25.0, 24.5, 24.0, 23.8],
        "wind_speed_10m": [3.0, 2.8, 2.5, 2.2],
        "wind_direction_10m": [60, 65, 70, 75],
        "precipitation_probability": [50, 60, 70, 80],
    },
}


class FakeWeatherClient:
    def __init__(self, data):
        self._data = data
        self.get_forecast_many_calls: list[list[Coordinates]] = []

    async def get_forecast(self, http_client, point):
        return self._data

    async def get_forecast_many(self, http_client, points):
        self.get_forecast_many_calls.append(points)
        return {WeatherClient.cache_key(point): self._data for point in points}

    cache_key = staticmethod(WeatherClient.cache_key)


async def test_get_conditions_returns_current_when_at_is_none():
    service = WeatherService(FakeWeatherClient(SAMPLE_DATA), http_client=None)

    conditions = await service.get_conditions(POINT)

    assert conditions.observed_at == "2026-08-13T21:15"
    assert conditions.temperature_c == 24.6
    assert conditions.wind_speed_ms == 2.5
    assert conditions.wind_direction_deg == 69
    assert conditions.wind_direction_label == "東"
    # 21:15に最も近いのは21:00（precipitation_probability=60）
    assert conditions.precipitation_probability_percent == 60
    # 改善計画T172: 突風・体感温度・降水量・UV指数はcurrentからそのまま読む
    assert conditions.apparent_temperature_c == 27.1
    assert conditions.wind_gusts_ms == 4.8
    assert conditions.precipitation_mm == 0.2
    assert conditions.uv_index == 0.0
    # 改善計画T385: weather_code/is_dayはcurrentからそのまま読む
    assert conditions.weather_code == 3
    assert conditions.is_day == 0
    # 改善計画T385: 今日の見通し4項目はdailyのindex0（今日）から読む
    assert conditions.sunset == "2026-08-13T18:41"
    assert conditions.precipitation_probability_max_percent == 80
    assert conditions.wind_speed_max_ms == 5.5
    assert conditions.temperature_max_c == 29.0
    assert conditions.temperature_min_c == 23.0
    # 改善計画T385フォローアップ: UV最大値はdailyのindex0（今日）から読む
    assert conditions.uv_index_max == 7.0
    # 改善計画T385フォローアップ: 今日の見通しの天気の流れは06:00〜20:00の2時間おき8コマ
    assert conditions.today_periods == [
        WeatherPeriodOutlook(period="06:00", weather_code=1, temperature_c=22.0, precipitation_probability_percent=10),
        WeatherPeriodOutlook(period="08:00", weather_code=1, temperature_c=24.0, precipitation_probability_percent=15),
        WeatherPeriodOutlook(period="10:00", weather_code=2, temperature_c=26.5, precipitation_probability_percent=20),
        WeatherPeriodOutlook(period="12:00", weather_code=2, temperature_c=28.5, precipitation_probability_percent=30),
        WeatherPeriodOutlook(period="14:00", weather_code=3, temperature_c=29.0, precipitation_probability_percent=40),
        WeatherPeriodOutlook(period="16:00", weather_code=3, temperature_c=27.5, precipitation_probability_percent=45),
        WeatherPeriodOutlook(period="18:00", weather_code=61, temperature_c=26.0, precipitation_probability_percent=50),
        WeatherPeriodOutlook(period="20:00", weather_code=3, temperature_c=25.0, precipitation_probability_percent=50),
    ]


async def test_conditions_from_data_returns_nearest_hourly_for_future_time():
    # get_conditionsはatを取らなくなった（呼び出し元は常にNoneのため引数を削除、
    # 改善計画のデッドコード監査）。未来時刻の近傍hourly選択ロジック自体は
    # get_conditions_manyが使う_conditions_from_dataで健在なため、直接テストする。
    service = WeatherService(FakeWeatherClient(SAMPLE_DATA), http_client=None)

    conditions = service._conditions_from_data(SAMPLE_DATA, at=datetime(2026, 8, 13, 22, 10))

    # 22:10に最も近いのは22:00
    assert conditions.observed_at == "2026-08-13T22:00"
    assert conditions.temperature_c == 24.0
    assert conditions.precipitation_probability_percent == 70
    # 改善計画T172: hourly側は_hourly_index_value経由（同じindex=2を再利用）
    assert conditions.apparent_temperature_c == 26.6
    assert conditions.wind_gusts_ms == 4.2
    assert conditions.precipitation_mm == 0.1
    assert conditions.uv_index == 0.0
    # 改善計画T385: get_conditions_many経路（at指定あり）はweather_code/is_day・dailyの
    # いずれも取得しないため常にNone
    assert conditions.weather_code is None
    assert conditions.is_day is None
    assert conditions.sunset is None
    assert conditions.precipitation_probability_max_percent is None
    assert conditions.wind_speed_max_ms is None
    assert conditions.temperature_max_c is None
    assert conditions.temperature_min_c is None
    # 改善計画T385フォローアップ: get_conditions_many経路は今日の見通し系も取得しない
    assert conditions.uv_index_max is None
    assert conditions.today_periods == []


async def test_conditions_from_data_returns_none_when_at_is_outside_hourly_range():
    service = WeatherService(FakeWeatherClient(SAMPLE_DATA), http_client=None)

    # hourlyは2026-08-13の20:00-23:00のみ。翌日はhourlyの範囲外。
    conditions = service._conditions_from_data(SAMPLE_DATA, at=datetime(2026, 8, 14, 10, 0))

    assert conditions is None


async def test_get_conditions_falls_back_to_none_when_t172_fields_are_missing():
    # 改善計画T172で追加したフィールドが無い応答（デプロイ直後のstale cache等）でも
    # 例外にならず、その4項目だけNoneになり他の既存項目は従来どおり取得できることを確認する。
    service = WeatherService(FakeWeatherClient(SAMPLE_DATA_WITHOUT_T172_FIELDS), http_client=None)

    conditions = await service.get_conditions(POINT)

    assert conditions is not None
    assert conditions.temperature_c == 24.6
    assert conditions.apparent_temperature_c is None
    assert conditions.wind_gusts_ms is None
    assert conditions.precipitation_mm is None
    assert conditions.uv_index is None
    # 改善計画T385: weather_code/is_day・dailyブロック自体が無い応答でも例外にならず、
    # 新規項目がNoneになるだけで既存項目は従来どおり取得できることを確認する。
    assert conditions.weather_code is None
    assert conditions.is_day is None
    assert conditions.sunset is None
    assert conditions.precipitation_probability_max_percent is None
    assert conditions.wind_speed_max_ms is None
    assert conditions.temperature_max_c is None
    assert conditions.temperature_min_c is None
    assert conditions.uv_index_max is None
    # 改善計画T385フォローアップ: dailyが丸ごと無くてもtoday_periodsは8コマ分生成される。
    # hourlyの時刻範囲が20:00〜23:00のみのため、範囲外の06:00〜18:00は全項目None、
    # 範囲内の20:00はweather_code列自体が無いためweather_codeのみNoneへ倒れ、
    # temperature_c/precipitation_probability_percentは通常どおり取得できる
    # （_hourly_index_value・_within_hourly_rangeのフィールド単位graceful degradation）。
    assert conditions.today_periods == [
        WeatherPeriodOutlook(period="06:00", weather_code=None, temperature_c=None, precipitation_probability_percent=None),
        WeatherPeriodOutlook(period="08:00", weather_code=None, temperature_c=None, precipitation_probability_percent=None),
        WeatherPeriodOutlook(period="10:00", weather_code=None, temperature_c=None, precipitation_probability_percent=None),
        WeatherPeriodOutlook(period="12:00", weather_code=None, temperature_c=None, precipitation_probability_percent=None),
        WeatherPeriodOutlook(period="14:00", weather_code=None, temperature_c=None, precipitation_probability_percent=None),
        WeatherPeriodOutlook(period="16:00", weather_code=None, temperature_c=None, precipitation_probability_percent=None),
        WeatherPeriodOutlook(period="18:00", weather_code=None, temperature_c=None, precipitation_probability_percent=None),
        WeatherPeriodOutlook(period="20:00", weather_code=None, temperature_c=25.0, precipitation_probability_percent=50),
    ]


async def test_get_conditions_returns_none_when_forecast_unavailable():
    service = WeatherService(FakeWeatherClient(None), http_client=None)

    conditions = await service.get_conditions(POINT)

    assert conditions is None


async def test_get_conditions_many_returns_conditions_per_point():
    service = WeatherService(FakeWeatherClient(SAMPLE_DATA), http_client=None)

    results = await service.get_conditions_many(
        [POINT, OTHER_POINT],
        [None, datetime(2026, 8, 13, 22, 10)],
    )

    assert len(results) == 2
    assert results[0].observed_at == "2026-08-13T21:15"
    assert results[1].observed_at == "2026-08-13T22:00"


async def test_prefetch_delegates_to_client_get_forecast_many():
    client = FakeWeatherClient(SAMPLE_DATA)
    service = WeatherService(client, http_client=None)

    await service.prefetch([POINT, OTHER_POINT])

    assert client.get_forecast_many_calls == [[POINT, OTHER_POINT]]


async def test_get_conditions_many_returns_none_for_points_without_forecast():
    class MissingSomeForecastsClient(FakeWeatherClient):
        async def get_forecast_many(self, http_client, points):
            return {WeatherClient.cache_key(points[0]): None, WeatherClient.cache_key(points[1]): SAMPLE_DATA}

    service = WeatherService(MissingSomeForecastsClient(SAMPLE_DATA), http_client=None)

    results = await service.get_conditions_many([POINT, OTHER_POINT], [None, None])

    assert results[0] is None
    assert results[1] is not None


async def test_get_wind_grid_returns_hourly_arrays_per_point():
    service = WeatherService(FakeWeatherClient(SAMPLE_DATA), http_client=None)

    times, results = await service.get_wind_grid([POINT, OTHER_POINT])

    assert times == SAMPLE_DATA["hourly"]["time"]
    assert len(results) == 2
    assert results[0].latitude == POINT.latitude
    assert results[0].longitude == POINT.longitude
    assert results[0].wind_speed_ms == SAMPLE_DATA["hourly"]["wind_speed_10m"]
    assert results[0].wind_direction_deg == SAMPLE_DATA["hourly"]["wind_direction_10m"]
    assert results[0].precipitation_mm == SAMPLE_DATA["hourly"]["precipitation"]


async def test_get_wind_grid_returns_none_for_points_without_forecast():
    class MissingSomeForecastsClient(FakeWeatherClient):
        async def get_forecast_many(self, http_client, points):
            return {WeatherClient.cache_key(points[0]): None, WeatherClient.cache_key(points[1]): SAMPLE_DATA}

    service = WeatherService(MissingSomeForecastsClient(SAMPLE_DATA), http_client=None)

    times, results = await service.get_wind_grid([POINT, OTHER_POINT])

    assert results[0] is None
    assert results[1] is not None
    # 最初の地点が失敗しても、成功した2番目の地点のtimesが採用される。
    assert times == SAMPLE_DATA["hourly"]["time"]


async def test_get_wind_grid_returns_none_when_hourly_missing():
    service = WeatherService(FakeWeatherClient({"current": SAMPLE_DATA["current"]}), http_client=None)

    times, results = await service.get_wind_grid([POINT])

    assert results[0] is None
    assert times == []


async def test_get_wind_grid_returns_none_when_wind_fields_missing():
    stale_data = {"hourly": {"time": ["2026-08-13T20:00"], "temperature_2m": [25.0]}}
    service = WeatherService(FakeWeatherClient(stale_data), http_client=None)

    times, results = await service.get_wind_grid([POINT])

    assert results[0] is None
    assert times == []


async def test_get_wind_grid_returns_none_when_precipitation_missing():
    # T183: precipitationは風の2フィールドと同じく必須（3配列とも欠けると格子点全体をNoneにする）。
    data_without_precipitation = {
        "hourly": {
            "time": ["2026-08-13T20:00"],
            "wind_speed_10m": [3.0],
            "wind_direction_10m": [60],
        }
    }
    service = WeatherService(FakeWeatherClient(data_without_precipitation), http_client=None)

    times, results = await service.get_wind_grid([POINT])

    assert results[0] is None
    assert times == []
