from datetime import datetime

import numpy as np

from app.domain.geo import compass_label
from app.domain.msm import wind_speed_and_direction
from app.domain.route import Coordinates
from app.domain.twilight import sunrise_sunset_jst
from app.domain.weather import WeatherConditions, daily_max, daily_range, period_outlooks, today_indices
from app.domain.region import BoundingBox
from app.domain.wind import WIND_FORECAST_LAT_STEP_DEG, WIND_FORECAST_LON_STEP_DEG, WindForecastSeries, WindLattice
from app.domain.wind_grid import WindGridPoint
from app.infrastructure import msm_client
from app.infrastructure.msm_client import MsmSeries, MsmUnavailableError


class WeatherService:
    """地点の天候・予報を気象庁MSMから読む。

    現在値として扱うのは常に時系列の先頭（現在時刻の正時）で、任意の時刻は指定できない。
    日の出・日没は外部に問い合わせず`domain/twilight.py`で計算する。
    """

    async def _read_point(self, point: Coordinates) -> MsmSeries | None:
        try:
            return await msm_client.read_series(
                np.array([point.latitude], dtype=float), np.array([point.longitude], dtype=float)
            )
        except (MsmUnavailableError, OSError, ValueError, KeyError):
            return None

    async def get_conditions(self, point: Coordinates) -> WeatherConditions | None:
        series = await self._read_point(point)
        if series is None or not series.times:
            return None
        return self._conditions_from_series(point, series)

    async def get_wind_forecast_lattice(self, bbox: BoundingBox) -> WindForecastSeries | None:
        """`bbox`を覆う格子点ごとの時別風向・風速の予報系列（1時間刻み、JSTのローカル時刻）。
        読めなければNone。ルートの探索範囲にも、ルートを出す前の地図のタイルにも使う。

        MSMのローカルファイルから読むため外部APIリクエストは発生しない。
        """
        lattice = WindLattice.covering(
            bbox.min_latitude, bbox.min_longitude, bbox.max_latitude, bbox.max_longitude,
            WIND_FORECAST_LAT_STEP_DEG, WIND_FORECAST_LON_STEP_DEG,
        )
        latitudes, longitudes = lattice.coordinates()
        try:
            series = await msm_client.read_series(latitudes, longitudes)
        except (MsmUnavailableError, OSError, ValueError, KeyError):
            return None
        if not series.times:
            return None
        speed, direction = wind_speed_and_direction(series.wind_u_ms, series.wind_v_ms)
        return WindForecastSeries(
            times=[datetime.fromisoformat(t) for t in series.times],
            speed_ms=speed,
            direction_deg=direction,
            lattice=lattice,
        )

    async def get_wind_grid(self, points: list[Coordinates]) -> tuple[list[str], list[WindGridPoint | None]]:
        """複数地点の時間別風向・風速・降水量をまとめて取得する。特定時刻1点へ収束させず、
        予報期間ぶんの時系列をそのまま返す。

        時刻配列は全地点で共通のため、戻り値の先頭要素として1本だけ返す（応答サイズ削減）。
        MSMを読めない場合は時刻列を空、全地点をNoneとして返す。
        """
        if not points:
            return [], []
        latitudes = np.array([point.latitude for point in points], dtype=float)
        longitudes = np.array([point.longitude for point in points], dtype=float)
        try:
            series = await msm_client.read_series(latitudes, longitudes)
        except (MsmUnavailableError, OSError, ValueError, KeyError):
            return [], [None] * len(points)
        if not series.times:
            return [], [None] * len(points)

        speed, direction = wind_speed_and_direction(series.wind_u_ms, series.wind_v_ms)
        # 数万要素をPythonのループで丸めると地点数に比例して重くなるため、配列のまま
        # まとめて丸めてからリストへ変換する。
        speeds = np.round(speed, 2).tolist()
        directions = np.round(direction, 1).tolist()
        precipitations = np.round(series.precipitation_mm, 2).tolist()
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
        return series.times, results

    def _conditions_from_series(self, point: Coordinates, series: MsmSeries) -> WeatherConditions:
        """MSMの時系列（1地点ぶん）から「今日」のパネル向けの値を組み立てる。時系列の先頭（現在時刻の
        正時）を現在値として扱い、日次の集計は同じJST暦日の残り時間ぶんを対象にする。"""
        times = series.times
        speed, direction = wind_speed_and_direction(series.wind_u_ms[0], series.wind_v_ms[0])
        temperature = series.temperature_c[0]
        precipitation = series.precipitation_mm[0]
        today = today_indices(times)

        return WeatherConditions(
            temperature_c=round(float(temperature[0]), 1),
            wind_speed_ms=round(float(speed[0]), 1),
            wind_direction_deg=round(float(direction[0]), 1),
            wind_direction_label=compass_label(float(direction[0])),
            precipitation_mm=round(float(precipitation[0]), 2),
            observed_at=times[0],
            twilight=sunrise_sunset_jst(point, datetime.fromisoformat(times[0]).date()),
            precipitation_max_mm=daily_max(precipitation, today),
            wind_speed_max_ms=daily_max(speed, today),
            temperature_range=daily_range(temperature, today),
            today_periods=period_outlooks(times, temperature, precipitation),
        )
