from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

from app.domain.geo import compass_label
from app.domain.msm import wind_speed_and_direction
from app.domain.route import Coordinates
from app.domain.twilight import is_night, sunrise_sunset_jst
from app.domain.weather import WeatherConditions, WeatherPeriodOutlook, derive_weather_code
from app.domain.wind import WindForecastSeries
from app.domain.wind_grid import WindGridPoint
from app.infrastructure import msm_client
from app.infrastructure.msm_client import MsmUnavailableError

JST = ZoneInfo("Asia/Tokyo")


class WeatherService:
    """地点の天候・予報を気象庁MSM（`infrastructure/msm_client.py`）から読む。

    `get_conditions`は現在（時系列の先頭＝現在時刻の正時）の気象と「今日の見通し」を返す
    （呼び出し元は天気APIエンドポイントとRoadGraphEngineの起点判定のみで、いずれも
    過去/未来時刻を渡さない）。日の出・日没は外部に問い合わせず`domain/twilight.py`で
    計算する。
    """

    async def _read_point(self, point: Coordinates) -> tuple[list[str], dict[str, np.ndarray]] | None:
        try:
            return await msm_client.read_series(
                np.array([point.latitude], dtype=float), np.array([point.longitude], dtype=float)
            )
        except (MsmUnavailableError, OSError, ValueError, KeyError):
            return None

    async def get_conditions(self, point: Coordinates) -> WeatherConditions | None:
        result = await self._read_point(point)
        if result is None or not result[0]:
            return None
        return self._conditions_from_series(point, *result)

    async def get_wind_forecast_series(self, point: Coordinates) -> WindForecastSeries | None:
        """地点の時別風向・風速の予報系列（1時間刻み、JSTのローカル時刻）を返す。
        MSMのローカルファイルから読むため外部APIリクエストは発生しない。読めない場合は
        None（呼び出し元は出発時点のスナップショットへ倒す）。"""
        result = await self._read_point(point)
        if result is None or not result[0]:
            return None
        times, values = result
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

    def _conditions_from_series(
        self, point: Coordinates, times: list[str], values: dict[str, np.ndarray]
    ) -> WeatherConditions:
        """MSMの時系列（1地点ぶん）から「今日の見通し」パネル向けの値を組み立てる。

        時系列の先頭（現在時刻の正時）を現在値として扱い、日次の集計は同じJST暦日の
        残り時間ぶんを対象にする（MSMは過去の時刻を返さないため、朝から見た「今日の最高
        気温」と夕方から見た値は一致しない——これから走る人向けの見通しとして扱う）。
        """
        speed, direction = wind_speed_and_direction(
            values["wind_u_component_10m"][0], values["wind_v_component_10m"][0]
        )
        temperature = values["temperature_2m"][0]
        precipitation = values["precipitation"][0]
        cloud_cover = values["cloud_cover"][0]

        now = datetime.fromisoformat(times[0])
        today = [index for index, t in enumerate(times) if datetime.fromisoformat(t).date() == now.date()]
        sunrise, sunset = sunrise_sunset_jst(point, now.date())

        return WeatherConditions(
            temperature_c=round(float(temperature[0]), 1),
            wind_speed_ms=round(float(speed[0]), 1),
            wind_direction_deg=round(float(direction[0]), 1),
            wind_direction_label=compass_label(float(direction[0])),
            precipitation_mm=round(float(precipitation[0]), 2),
            observed_at=times[0],
            weather_code=derive_weather_code(
                float(precipitation[0]), float(cloud_cover[0]), float(temperature[0])
            ),
            is_day=0 if is_night(point, now.replace(tzinfo=JST)) else 1,
            sunrise=sunrise,
            sunset=sunset,
            precipitation_max_mm=self._daily_max(precipitation, today),
            wind_speed_max_ms=self._daily_max(speed, today),
            temperature_max_c=self._daily_max(temperature, today),
            temperature_min_c=self._daily_min(temperature, today),
            today_periods=self._period_outlooks(times, values),
        )

    @staticmethod
    def _daily_max(series: np.ndarray, indices: list[int]) -> float | None:
        return None if not indices else round(float(np.max(series[indices])), 1)

    @staticmethod
    def _daily_min(series: np.ndarray, indices: list[int]) -> float | None:
        return None if not indices else round(float(np.min(series[indices])), 1)

    _PERIOD_SLOT_COUNT = 8
    _PERIOD_INTERVAL_HOURS = 2

    @classmethod
    def _period_outlooks(cls, times: list[str], values: dict[str, np.ndarray]) -> list[WeatherPeriodOutlook]:
        """現在時刻の正時を起点に2時間おきのコマを最大8つ返す。予報の終端に達したら
        そこで打ち切る（コマ数はMSMのrunによって変動しうる）。"""
        results = []
        for slot in range(cls._PERIOD_SLOT_COUNT):
            index = slot * cls._PERIOD_INTERVAL_HOURS
            if index >= len(times):
                break
            precipitation = float(values["precipitation"][0][index])
            temperature = float(values["temperature_2m"][0][index])
            results.append(
                WeatherPeriodOutlook(
                    period=datetime.fromisoformat(times[index]).strftime("%H:%M"),
                    weather_code=derive_weather_code(
                        precipitation, float(values["cloud_cover"][0][index]), temperature
                    ),
                    temperature_c=round(temperature, 1),
                    precipitation_mm=round(precipitation, 2),
                )
            )
        return results
