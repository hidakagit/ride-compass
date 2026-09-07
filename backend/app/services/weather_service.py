from datetime import datetime, timedelta

import httpx
import numpy as np

from app.domain.geo import compass_label
from app.domain.msm import wind_speed_and_direction
from app.domain.route import Coordinates
from app.domain.weather import WeatherConditions, WeatherPeriodOutlook
from app.domain.wind import WindForecastSeries
from app.domain.wind_grid import WindGridPoint
from app.infrastructure import msm_client
from app.infrastructure.msm_client import MsmUnavailableError
from app.infrastructure.weather_client import WeatherClient


class WeatherService:
    """地点の天候を取得する。

    予報系のうち風・降水（`get_wind_grid`・`get_wind_forecast_series`）は気象庁MSMの
    ローカルファイル（`infrastructure/msm_client.py`）から読む。`get_conditions`は
    常に現在の気象を返す（呼び出し元は天気APIエンドポイント・RoadGraphEngineの起点判定
    のみで、いずれも過去/未来時刻を渡さない）。
    """

    def __init__(self, client: WeatherClient, http_client: httpx.AsyncClient):
        self._client = client
        self._http_client = http_client

    async def get_conditions(self, point: Coordinates) -> WeatherConditions | None:
        data = await self._client.get_forecast(self._http_client, point)
        if data is None:
            return None
        return self._conditions_from_data(data)

    async def get_wind_forecast_series(self, point: Coordinates) -> WindForecastSeries | None:
        """地点の時別風向・風速の予報系列（1時間刻み、JSTのローカル時刻）を返す。
        MSMのローカルファイルから読むため外部APIリクエストは発生しない。読めない場合は
        None（呼び出し元は出発時点のスナップショットへ倒す）。"""
        try:
            times, values = await msm_client.read_series(
                np.array([point.latitude], dtype=float), np.array([point.longitude], dtype=float)
            )
        except (MsmUnavailableError, OSError, ValueError, KeyError):
            return None
        if not times:
            return None
        speed, direction = wind_speed_and_direction(
            values["wind_u_component_10m"][0], values["wind_v_component_10m"][0]
        )
        return WindForecastSeries(
            times=[datetime.fromisoformat(t) for t in times],
            speed_ms=speed,
            direction_deg=direction,
        )

    async def get_wind_grid(self, points: list[Coordinates]) -> tuple[list[str], list[WindGridPoint | None]]:
        """複数地点の時間別風向・風速・降水量（+60分以降の延長予報）をまとめて取得する。
        特定時刻1点へ収束させず、予報期間ぶんの時系列をそのまま返す
        （domain/wind_grid.py: WindGridPointのdocstring参照）。

        時刻配列は全地点で共通のため、戻り値の先頭要素として1本だけ返す（応答サイズ削減）。
        MSMを読めない場合は時刻列を空、全地点をNoneとして返す（呼び出し元が502へ倒す）。"""
        if not points:
            return [], []
        latitudes = np.array([point.latitude for point in points], dtype=float)
        longitudes = np.array([point.longitude for point in points], dtype=float)
        try:
            times, values = await msm_client.read_series(latitudes, longitudes)
        except (MsmUnavailableError, OSError, ValueError, KeyError):
            return [], [None] * len(points)
        if not times:
            return [], [None] * len(points)

        speed, direction = wind_speed_and_direction(
            values["wind_u_component_10m"], values["wind_v_component_10m"]
        )
        # 数万要素をPythonのループで丸めると地点数に比例して重くなるため、配列のまま
        # まとめて丸めてからリストへ変換する。
        speeds = np.round(speed, 2).tolist()
        directions = np.round(direction, 1).tolist()
        precipitations = np.round(values["precipitation"], 2).tolist()
        results: list[WindGridPoint | None] = [
            WindGridPoint(
                latitude=point.latitude,
                longitude=point.longitude,
                wind_speed_ms=speeds[index],
                wind_direction_deg=directions[index],
                precipitation_mm=precipitations[index],
            )
            for index, point in enumerate(points)
        ]
        return times, results

    def _conditions_from_data(self, data: dict) -> WeatherConditions | None:
        hourly = data.get("hourly")
        if not hourly or not hourly.get("time"):
            return None

        current = data.get("current")
        if not current:
            return None

        # Open-Meteoが200を返してもJSON形状が期待と食い違う（一時的なAPI障害・スキーマ変更等）
        # 場合、直下の添字アクセスがKeyError/IndexErrorを送出しうる。ここで捕捉せず伝播させると
        # 「取得失敗は握りつぶしてnull」という他の外部API（標高・路面）と同じ方針から外れ、
        # 1件の異常レスポンスでルート生成全体が500になってしまう（`RoadGraphEngine.prepare`が
        # 探索前に1回だけ取得し、Noneなら風・夜間評価なしで続行する設計のため）。
        try:
            observed_at = current["time"]
            temperature = current["temperature_2m"]
            wind_speed = current["wind_speed_10m"]
            wind_direction = current["wind_direction_10m"]
            # 突風・体感温度・UV指数・降水量は「current」自体に含めて取得済み
            # （weather_client.py参照）のため、precipitation_probabilityと違いhourlyへの
            # 近傍探索は不要。current側に無い場合（プロパティ欠落）はNoneへ倒す。
            apparent_temperature = current.get("apparent_temperature")
            wind_gusts = current.get("wind_gusts_10m")
            precipitation = current.get("precipitation")
            uv_index = current.get("uv_index")
            weather_code = current.get("weather_code")
            is_day = current.get("is_day")
            precipitation_probability = self._hourly_value_near(hourly, observed_at, "precipitation_probability")
            # 「今日の見通し」（daily、forecast_days=2のindex0=今日）。
            daily = data.get("daily") or {}
            sunrise = self._daily_index_value(daily, "sunrise", 0)
            sunset = self._daily_index_value(daily, "sunset", 0)
            precipitation_probability_max = self._daily_index_value(daily, "precipitation_probability_max", 0)
            wind_speed_max = self._daily_index_value(daily, "wind_speed_10m_max", 0)
            temperature_max = self._daily_index_value(daily, "temperature_2m_max", 0)
            temperature_min = self._daily_index_value(daily, "temperature_2m_min", 0)
            uv_index_max = self._daily_index_value(daily, "uv_index_max", 0)
            # dailyの日次集約値だけでは「日中いつ頃崩れるか」が分からないため、
            # hourlyから2時間おき8コマの代表時刻を抜き出す（_period_outlooks参照）。
            today_periods = self._period_outlooks(hourly, observed_at)
        except (KeyError, IndexError, TypeError):
            return None

        return WeatherConditions(
            temperature_c=temperature,
            apparent_temperature_c=apparent_temperature,
            wind_speed_ms=wind_speed,
            wind_direction_deg=wind_direction,
            wind_direction_label=compass_label(wind_direction),
            wind_gusts_ms=wind_gusts,
            precipitation_probability_percent=precipitation_probability,
            precipitation_mm=precipitation,
            uv_index=uv_index,
            observed_at=observed_at,
            weather_code=weather_code,
            is_day=is_day,
            sunrise=sunrise,
            sunset=sunset,
            precipitation_probability_max_percent=precipitation_probability_max,
            wind_speed_max_ms=wind_speed_max,
            temperature_max_c=temperature_max,
            temperature_min_c=temperature_min,
            uv_index_max=uv_index_max,
            today_periods=today_periods,
        )

    @staticmethod
    def _within_hourly_range(times: list[str], target: str) -> bool:
        if not times:
            return False
        target_dt = datetime.fromisoformat(target)
        parsed = [datetime.fromisoformat(t) for t in times]
        return min(parsed) <= target_dt <= max(parsed)

    @staticmethod
    def _nearest_hourly_index(times: list[str], target: str) -> int | None:
        if not times:
            return None
        target_dt = datetime.fromisoformat(target)
        diffs = [abs((datetime.fromisoformat(t) - target_dt).total_seconds()) for t in times]
        return diffs.index(min(diffs))

    @classmethod
    def _hourly_value_near(cls, hourly: dict, target_time: str, field: str):
        index = cls._nearest_hourly_index(hourly.get("time", []), target_time)
        values = hourly.get(field)
        if index is None or not values or index >= len(values):
            return None
        return values[index]

    @staticmethod
    def _hourly_index_value(hourly: dict, field: str, index: int):
        """hourly配列から既知のindexで値を引く（_period_outlooksが使う）。
        対象時刻のindexが呼び出し元で既に確定しているため、_hourly_value_nearのように
        改めて最近傍時刻を探し直す必要がない。フィールド自体が存在しない/配列が短い場合は
        Noneへ倒す（新規追加パラメータのため既存キャッシュ済みレスポンスに含まれない
        ケースを想定）。"""
        values = hourly.get(field)
        if not values or index >= len(values):
            return None
        return values[index]

    @staticmethod
    def _daily_index_value(daily: dict, field: str, index: int):
        """daily配列から既知のindexで値を引く（_hourly_index_valueのdaily版）。
        forecast_days=2・timezone=Asia/Tokyoのindex 0が「今日」に対応する。"""
        values = daily.get(field)
        if not values or index >= len(values):
            return None
        return values[index]

    # 「今日の見通し」パネルの時間帯別コマ。現在時刻を2時間グリッド（0/2/4...時）へ
    # 切り下げた時刻を起点に2時間おき8コマ、各コマの代表時刻をそのまま採用する。
    # severity（重大度）で「その区間で最も荒れた時刻」を選ぶ判定はせず代表1時刻を
    # そのまま使う。重大度ランキングはweather_code→アイコン判定と同種の「意味づけ」
    # であり、frontend/weatherCode.tsへ集約する既存方針（backendは生の値を素通しする
    # だけ）に合わせるため。既存の_nearest_hourly_index/_hourly_index_valueをそのまま
    # 再利用できる利点もある。
    _PERIOD_SLOT_COUNT = 8
    _PERIOD_INTERVAL_HOURS = 2

    @classmethod
    def _period_outlooks(cls, hourly: dict, observed_at: str) -> list[WeatherPeriodOutlook]:
        now = datetime.fromisoformat(observed_at)
        start_hour = now.hour - (now.hour % cls._PERIOD_INTERVAL_HOURS)
        start = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        times = hourly.get("time") or []
        results = []
        for i in range(cls._PERIOD_SLOT_COUNT):
            slot_time = start + timedelta(hours=cls._PERIOD_INTERVAL_HOURS * i)
            target = slot_time.strftime("%Y-%m-%dT%H:%M")
            index = cls._nearest_hourly_index(times, target) if cls._within_hourly_range(times, target) else None
            weather_code = None if index is None else cls._hourly_index_value(hourly, "weather_code", index)
            temperature = None if index is None else cls._hourly_index_value(hourly, "temperature_2m", index)
            precipitation_probability = (
                None if index is None else cls._hourly_index_value(hourly, "precipitation_probability", index)
            )
            results.append(
                WeatherPeriodOutlook(
                    period=slot_time.strftime("%H:%M"),
                    weather_code=weather_code,
                    temperature_c=temperature,
                    precipitation_probability_percent=precipitation_probability,
                )
            )
        return results
