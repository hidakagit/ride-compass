from datetime import datetime

import httpx

from app.domain.geo import compass_label
from app.domain.route import Coordinates
from app.domain.weather import WeatherConditions
from app.infrastructure.weather_client import WeatherClient


class WeatherService:
    """地点の天候を取得する。

    `at`（時刻）を渡せない/Noneの場合は現在の気象を返す。`at`に未来時刻を渡した場合は
    取得済みの時間別予報（hourly、forecast_days=2分）から最も近い時刻のデータを返す。
    Step6ではフロントから`at`は渡さない（現在地の現在の天候のみ表示）が、Step7以降で
    ルート上の各点＋推定到達時刻を渡す拡張がこのメソッドのシグネチャ変更なしで行える。
    """

    def __init__(self, client: WeatherClient, http_client: httpx.AsyncClient):
        self._client = client
        self._http_client = http_client

    async def get_conditions(self, point: Coordinates, at: datetime | None = None) -> WeatherConditions | None:
        data = await self._client.get_forecast(self._http_client, point)
        if data is None:
            return None
        return self._conditions_from_data(data, at)

    async def get_conditions_many(
        self, points: list[Coordinates], times: list[datetime | None]
    ) -> list[WeatherConditions | None]:
        """複数地点の天候を、可能な限り1回のOpen-Meteo呼び出しでまとめて取得する（WindService用）。

        地点ごとの時刻（times[i]）が異なっていても、予報自体は地点ごとにforecast_days分の
        hourly系列をまとめて取得しているため、取得後にそれぞれ最も近い時刻を選ぶだけでよい
        （get_conditionsと同じ選択ロジックを_conditions_from_dataへ切り出して共有する）。
        """
        forecasts = await self._client.get_forecast_many(self._http_client, points)
        results = []
        for point, at in zip(points, times):
            data = forecasts.get(self._client.cache_key(point))
            results.append(None if data is None else self._conditions_from_data(data, at))
        return results

    def _conditions_from_data(self, data: dict, at: datetime | None) -> WeatherConditions | None:
        hourly = data.get("hourly")
        if not hourly or not hourly.get("time"):
            return None

        # Open-Meteoが200を返してもJSON形状が期待と食い違う（一時的なAPI障害・スキーマ変更等）
        # 場合、直下の添字アクセスがKeyError/IndexErrorを送出しうる。ここで捕捉せず伝播させると
        # 「取得失敗は握りつぶしてnull」という他の外部API（標高・路面）と同じ方針から外れ、
        # 8方位分の候補が確定済みでも1件の異常レスポンスでルート生成全体が500になってしまう
        # （route_generator.pyのgatherはtrace_loopのみreturn_exceptions=True保護対象）。
        try:
            if at is None:
                current = data.get("current")
                if not current:
                    return None
                observed_at = current["time"]
                temperature = current["temperature_2m"]
                wind_speed = current["wind_speed_10m"]
                wind_direction = current["wind_direction_10m"]
                precipitation_probability = self._hourly_value_near(hourly, observed_at, "precipitation_probability")
            else:
                target = at.strftime("%Y-%m-%dT%H:%M")
                if not self._within_hourly_range(hourly["time"], target):
                    # 取得済みhourly（forecast_days=2分）の範囲外。範囲内の最も近い時刻を
                    # 代用すると「遠い未来/過去の天候」として誤って提示することになるため、
                    # 範囲外は素直にNoneを返す（他の欠損時と同じ方針）。
                    return None
                index = self._nearest_hourly_index(hourly["time"], target)
                if index is None:
                    return None
                observed_at = hourly["time"][index]
                temperature = hourly["temperature_2m"][index]
                wind_speed = hourly["wind_speed_10m"][index]
                wind_direction = hourly["wind_direction_10m"][index]
                precipitation_probability = hourly["precipitation_probability"][index]
        except (KeyError, IndexError, TypeError):
            return None

        return WeatherConditions(
            temperature_c=temperature,
            wind_speed_ms=wind_speed,
            wind_direction_deg=wind_direction,
            wind_direction_label=compass_label(wind_direction),
            precipitation_probability_percent=precipitation_probability,
            observed_at=observed_at,
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
