import time

import httpx

from app.domain.route import Coordinates
from app.infrastructure.debug_log import log_external_call

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# 天候は数km単位でしか変わらないため、標高キャッシュ（4桁）より粗い精度で丸める。
CACHE_PRECISION = 2
# 標高と異なり天候は時間で変化するため、恒久キャッシュではなくTTLを設ける。
CACHE_TTL_SECONDS = 30 * 60

_forecast_cache: dict[tuple[float, float], tuple[float, dict]] = {}


class WeatherClient:
    """Open-Meteo Forecast APIのクライアント。

    `current`（現在の気象）と`hourly`（当日以降の時間別予報）を1回のリクエストで
    まとめて取得する。これにより「現在の天気」だけでなく「N時間後の天気」も
    追加リクエストなしで参照できる（`WeatherService.get_conditions`が利用する）。

    天候は付随情報のため、取得できなかった場合は例外を投げず`None`を返す。
    """

    async def get_forecast(self, client: httpx.AsyncClient, point: Coordinates) -> dict | None:
        key = (round(point.latitude, CACHE_PRECISION), round(point.longitude, CACHE_PRECISION))

        with log_external_call("weather:open-meteo", lat=key[0], lon=key[1]) as fields:
            cached = _forecast_cache.get(key)
            if cached is not None:
                fetched_at, data = cached
                if time.time() - fetched_at < CACHE_TTL_SECONDS:
                    fields["cache"] = "hit"
                    return data

            fields["cache"] = "miss"
            params = {
                "latitude": point.latitude,
                "longitude": point.longitude,
                "current": "temperature_2m,wind_speed_10m,wind_direction_10m",
                "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m,precipitation_probability",
                "forecast_days": 2,
                "timezone": "Asia/Tokyo",
                "wind_speed_unit": "ms",
            }

            try:
                response = await client.get(OPEN_METEO_URL, params=params)
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                fields["result"] = "error"
                fields["error"] = repr(exc)
                return None

            fields["result"] = "ok"
            fields["status"] = getattr(response, "status_code", None)
            _forecast_cache[key] = (time.time(), data)
            return data
