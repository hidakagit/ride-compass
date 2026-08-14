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

        hourly = data.get("hourly")
        if not hourly or not hourly.get("time"):
            return None

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
            index = self._nearest_hourly_index(hourly["time"], target)
            if index is None:
                return None
            observed_at = hourly["time"][index]
            temperature = hourly["temperature_2m"][index]
            wind_speed = hourly["wind_speed_10m"][index]
            wind_direction = hourly["wind_direction_10m"][index]
            precipitation_probability = hourly["precipitation_probability"][index]

        return WeatherConditions(
            temperature_c=temperature,
            wind_speed_ms=wind_speed,
            wind_direction_deg=wind_direction,
            wind_direction_label=compass_label(wind_direction),
            precipitation_probability_percent=precipitation_probability,
            observed_at=observed_at,
        )

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
