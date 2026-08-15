import asyncio
import time

import httpx

from app.domain.route import Coordinates
from app.infrastructure.debug_log import log_external_call

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# 天候は数km単位でしか変わらないため、標高キャッシュ（4桁）より粗い精度で丸める。
CACHE_PRECISION = 2
# 標高と異なり天候は時間で変化するため、恒久キャッシュではなくTTLを設ける。
CACHE_TTL_SECONDS = 30 * 60

# ルート生成中はWindServiceが区間ごとに（同時実行数5で）Open-Meteoへ問い合わせるため、
# 1ルートの評価だけで数十件のリクエストが短時間に集中しうる。実測ではこの程度の
# 同時実行数（5並列）だけでも、Open-Meteo側の429 Too Many Requestsに加えて
# ConnectTimeout（TLSハンドシェイクの混雑によるものとみられる接続タイムアウト）が
# 発生し、単発の/api/weather呼び出し（現在地表示）まで巻き込まれて502になっていた
# （原因調査ログ参照）。どちらも数百ms〜数秒待てば解消する一時的な状態のため、
# 短いバックオフで数回だけ再試行する。
RETRY_STATUS_CODE = 429
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 0.3
# 共有クライアントの既定タイムアウト（10秒）のままだと、ConnectTimeout1回の失敗だけで
# 再試行の予算をほぼ使い切ってしまう。この呼び出しだけ短いタイムアウトへ上書きし、
# 早期に失敗を検知して再試行に回す。
REQUEST_TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0)

_forecast_cache: dict[tuple[float, float], tuple[float, dict]] = {}


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Retry-Afterヘッダ（秒数形式のみ想定、Open-Meteoは日付形式を返さない）を解釈する。"""
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


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

            attempt = 0
            while True:
                try:
                    response = await client.get(OPEN_METEO_URL, params=params, timeout=REQUEST_TIMEOUT)
                    response.raise_for_status()
                    data = response.json()
                    break
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == RETRY_STATUS_CODE and attempt < MAX_RETRIES:
                        attempt += 1
                        fields["retries"] = attempt
                        await asyncio.sleep(_retry_after_seconds(exc.response) or RETRY_BACKOFF_SECONDS * attempt)
                        continue
                    fields["result"] = "error"
                    fields["error"] = repr(exc)
                    return None
                except httpx.TransportError as exc:
                    # 接続タイムアウト等、応答自体を受け取れなかった失敗。ConnectTimeoutは
                    # 実測で数並列アクセスだけでも発生しており(原因調査ログ参照)、429と同様に
                    # 短時間で解消することが多いため同じ回数だけ再試行する。
                    if attempt < MAX_RETRIES:
                        attempt += 1
                        fields["retries"] = attempt
                        await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)
                        continue
                    fields["result"] = "error"
                    fields["error"] = repr(exc)
                    return None
                except (httpx.HTTPError, ValueError) as exc:
                    fields["result"] = "error"
                    fields["error"] = repr(exc)
                    return None

            fields["result"] = "ok"
            fields["status"] = getattr(response, "status_code", None)
            _forecast_cache[key] = (time.time(), data)
            return data
