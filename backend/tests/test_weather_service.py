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
    # 改善計画T385フォローアップ:「今日の見通し」の天気の流れ（_period_outlooks）を意味の
    # ある値で検証するため、時刻範囲を当日06:00〜翌日10:00まで拡張し、weather_code/is_dayを
    # 追加した（従来の20:00〜23:00の4点は既存テストの期待値と一致するようそのまま維持）。
    # currentの観測時刻21:15は2時間グリッドで20:00始まりのため、_period_outlooksが生成する
    # 8コマ（20:00,22:00,00:00,02:00,04:00,06:00,08:00,10:00）は翌日にまたがる
    # （後続フォローアップ「現在時刻を含む時間帯から2時間毎」の日またぎ検証を兼ねる）。
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
            "2026-08-14T00:00",
            "2026-08-14T02:00",
            "2026-08-14T04:00",
            "2026-08-14T06:00",
            "2026-08-14T08:00",
            "2026-08-14T10:00",
        ],
        "temperature_2m": [22.0, 24.0, 26.5, 28.5, 29.0, 27.5, 26.0, 25.0, 24.5, 24.0, 23.8, 23.0, 22.0, 21.5, 22.5, 24.5, 27.0],
        "wind_speed_10m": [2.0, 2.2, 2.5, 2.8, 3.0, 2.9, 2.7, 3.0, 2.8, 2.5, 2.2, 2.0, 1.8, 1.5, 1.8, 2.0, 2.3],
        "wind_direction_10m": [50, 55, 58, 60, 62, 63, 61, 60, 65, 70, 75, 80, 85, 88, 90, 92, 95],
        "precipitation_probability": [10, 15, 20, 30, 40, 45, 50, 50, 60, 70, 80, 75, 70, 60, 40, 20, 15],
        "apparent_temperature": [22.5, 24.5, 27.0, 29.5, 30.0, 28.0, 26.5, 27.5, 27.1, 26.6, 26.0, 25.5, 24.0, 23.0, 24.0, 26.0, 28.5],
        "wind_gusts_10m": [3.0, 3.2, 3.8, 4.5, 5.0, 4.8, 4.5, 5.5, 4.8, 4.2, 3.9, 3.5, 3.0, 2.5, 2.8, 3.2, 3.6],
        "precipitation": [0.0, 0.0, 0.0, 0.1, 0.2, 0.2, 0.3, 0.3, 0.2, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "uv_index": [0.5, 2.0, 4.5, 6.5, 7.0, 5.0, 2.5, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.3, 1.5, 3.5],
        "weather_code": [1, 1, 2, 2, 3, 3, 61, 3, 3, 3, 3, 3, 3, 2, 1, 1, 1],
        "is_day": [0, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1],
    },
    # 改善計画T385:「今日の見通し」パネル用（forecast_days=2、index0=今日）。
    # sunrise（改善計画T385フォローアップ2、夜明け前/日没前の切り替え表示用）。
    "daily": {
        "time": ["2026-08-13", "2026-08-14"],
        "sunrise": ["2026-08-13T05:12", "2026-08-14T05:11"],
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
    # 改善計画T385フォローアップ2: sunriseもdailyのindex0（今日）から読む
    assert conditions.sunrise == "2026-08-13T05:12"
    assert conditions.sunset == "2026-08-13T18:41"
    assert conditions.precipitation_probability_max_percent == 80
    assert conditions.wind_speed_max_ms == 5.5
    assert conditions.temperature_max_c == 29.0
    assert conditions.temperature_min_c == 23.0
    # 改善計画T385フォローアップ: UV最大値はdailyのindex0（今日）から読む
    assert conditions.uv_index_max == 7.0
    # 改善計画T385フォローアップ2: 今日の見通しの天気の流れは「現在時刻を含む時間帯から
    # 2時間毎」。observed_at=21:15は2時間グリッドで20:00始まりのため8コマは
    # 20:00,22:00,00:00,02:00,04:00,06:00,08:00,10:00（翌日にまたがる）
    assert conditions.today_periods == [
        WeatherPeriodOutlook(period="20:00", weather_code=3, temperature_c=25.0, precipitation_probability_percent=50),
        WeatherPeriodOutlook(period="22:00", weather_code=3, temperature_c=24.0, precipitation_probability_percent=70),
        WeatherPeriodOutlook(period="00:00", weather_code=3, temperature_c=23.0, precipitation_probability_percent=75),
        WeatherPeriodOutlook(period="02:00", weather_code=3, temperature_c=22.0, precipitation_probability_percent=70),
        WeatherPeriodOutlook(period="04:00", weather_code=2, temperature_c=21.5, precipitation_probability_percent=60),
        WeatherPeriodOutlook(period="06:00", weather_code=1, temperature_c=22.5, precipitation_probability_percent=40),
        WeatherPeriodOutlook(period="08:00", weather_code=1, temperature_c=24.5, precipitation_probability_percent=20),
        WeatherPeriodOutlook(period="10:00", weather_code=1, temperature_c=27.0, precipitation_probability_percent=15),
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
    assert conditions.sunrise is None
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

    # hourlyは2026-08-13T06:00〜2026-08-14T10:00のみ（改善計画T385フォローアップ2で
    # 天気の流れの日またぎ検証用に拡張）。それより先は範囲外。
    conditions = service._conditions_from_data(SAMPLE_DATA, at=datetime(2026, 8, 15, 10, 0))

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
    assert conditions.sunrise is None
    assert conditions.sunset is None
    assert conditions.precipitation_probability_max_percent is None
    assert conditions.wind_speed_max_ms is None
    assert conditions.temperature_max_c is None
    assert conditions.temperature_min_c is None
    assert conditions.uv_index_max is None
    # 改善計画T385フォローアップ2: dailyが丸ごと無くてもtoday_periodsは8コマ分生成される。
    # observed_at=21:15は2時間グリッドで20:00始まりのため8コマは20:00,22:00,00:00,02:00,
    # 04:00,06:00,08:00,10:00（翌日にまたがる）。hourlyの時刻範囲が20:00〜23:00（当日のみ）
    # のため、範囲内の20:00・22:00はweather_code列自体が無いためweather_codeのみNoneへ倒れ
    # temperature_c/precipitation_probability_percentは通常どおり取得でき、翌日にまたがる
    # 残り6コマは範囲外のため全項目Noneになる
    # （_hourly_index_value・_within_hourly_rangeのフィールド単位graceful degradation）。
    assert conditions.today_periods == [
        WeatherPeriodOutlook(period="20:00", weather_code=None, temperature_c=25.0, precipitation_probability_percent=50),
        WeatherPeriodOutlook(period="22:00", weather_code=None, temperature_c=24.0, precipitation_probability_percent=70),
        WeatherPeriodOutlook(period="00:00", weather_code=None, temperature_c=None, precipitation_probability_percent=None),
        WeatherPeriodOutlook(period="02:00", weather_code=None, temperature_c=None, precipitation_probability_percent=None),
        WeatherPeriodOutlook(period="04:00", weather_code=None, temperature_c=None, precipitation_probability_percent=None),
        WeatherPeriodOutlook(period="06:00", weather_code=None, temperature_c=None, precipitation_probability_percent=None),
        WeatherPeriodOutlook(period="08:00", weather_code=None, temperature_c=None, precipitation_probability_percent=None),
        WeatherPeriodOutlook(period="10:00", weather_code=None, temperature_c=None, precipitation_probability_percent=None),
    ]


def test_period_outlooks_starts_from_the_two_hour_slot_containing_now():
    # ユーザー要望「現在時刻を含む時間帯（例：今7時なら6時の天気）から2時間毎」の直接検証。
    # 7時は2時間グリッド（0/2/4...時）で6時始まりの区間に含まれるため、先頭コマは06:00になる。
    hourly = {
        "time": ["2026-08-13T06:00", "2026-08-13T08:00", "2026-08-13T10:00"],
        "weather_code": [1, 2, 3],
        "temperature_2m": [20.0, 21.0, 22.0],
        "precipitation_probability": [10, 20, 30],
    }

    periods = WeatherService._period_outlooks(hourly, "2026-08-13T07:10")

    assert [p.period for p in periods] == [
        "06:00", "08:00", "10:00", "12:00", "14:00", "16:00", "18:00", "20:00",
    ]
    assert periods[0].weather_code == 1
    assert periods[0].temperature_c == 20.0
    assert periods[0].precipitation_probability_percent == 10
    assert periods[1].weather_code == 2
    assert periods[2].weather_code == 3
    # 10:00より先（12:00〜）はhourlyの範囲外のため全項目None
    assert periods[3] == WeatherPeriodOutlook(
        period="12:00", weather_code=None, temperature_c=None, precipitation_probability_percent=None
    )


def test_period_outlooks_rounds_down_even_hour_unchanged():
    # 現在時刻がちょうど2時間グリッドの境界（例: 8時）なら、その時刻自体が先頭コマになる
    # （切り下げの境界条件）。
    hourly = {"time": ["2026-08-13T08:00"], "weather_code": [5], "temperature_2m": [18.0], "precipitation_probability": [5]}

    periods = WeatherService._period_outlooks(hourly, "2026-08-13T08:00")

    assert periods[0].period == "08:00"
    assert periods[0].weather_code == 5


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
