"""JMAアメダス観測値APIのクライアント（改善計画T387）。

jma_warning_client.pyと同じ「JMA公式の非公開だが広く使われているエンドポイント」を使う。
アメダスは10分ごとに更新されるため、jma_warning_client.pyの警報（10分TTL）と同程度の
更新頻度感覚で扱う。取得失敗時は他のJMA系クライアントと同じくNoneを返し、
呼び出し元（jma_amedas_service.py）が「観測値なし」として扱う。
"""

import httpx
from cachetools import TTLCache

from app.infrastructure.debug_log import error_type_label, log_external_call

AMEDAS_STATION_TABLE_URL = "https://www.jma.go.jp/bosai/amedas/const/amedas.json"
AMEDAS_LATEST_TIME_URL = "https://www.jma.go.jp/bosai/amedas/data/latest_time_list.json"
AMEDAS_OBSERVATION_URL_TEMPLATE = "https://www.jma.go.jp/bosai/amedas/data/map/{timestamp}.json"

REQUEST_TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0)

# 観測所マスタ（緯度経度・名称）は行政区画変更等でしか変わらない静的に近いデータのため、
# jma_warning_client.pyのarea.jsonと同じ長寿命TTL。
_STATION_TABLE_CACHE_TTL_SECONDS = 24 * 60 * 60
# 最新観測時刻の一覧は10分更新のアメダスの鮮度に合わせた短いTTL。
_LATEST_TIME_CACHE_TTL_SECONDS = 5 * 60

_station_table_cache: TTLCache = TTLCache(maxsize=1, ttl=_STATION_TABLE_CACHE_TTL_SECONDS)
_latest_time_cache: TTLCache = TTLCache(maxsize=1, ttl=_LATEST_TIME_CACHE_TTL_SECONDS)
_STATION_TABLE_CACHE_KEY = "stations"
_LATEST_TIME_CACHE_KEY = "latest_time"


async def fetch_station_table(client: httpx.AsyncClient) -> dict | None:
    """観測所マスタ（station_id -> {lat, lon, kjName(漢字名), ...}）を取得する。

    JMAのlat/lonは[度, 分]の配列で表現される独特の形式（呼び出し元
    jma_amedas_service.pyで10進度へ変換する）。
    """
    with log_external_call("weather:jma-amedas-stations") as fields:
        cached = _station_table_cache.get(_STATION_TABLE_CACHE_KEY)
        if cached is not None:
            fields["cache"] = "hit"
            return cached
        fields["cache"] = "miss"
        try:
            response = await client.get(AMEDAS_STATION_TABLE_URL, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
            return None
        fields["result"] = "ok"
        _station_table_cache[_STATION_TABLE_CACHE_KEY] = data
        return data


async def fetch_latest_observation_time(client: httpx.AsyncClient) -> str | None:
    """最新の観測時刻一覧のうち先頭（最新）のISO時刻文字列を返す。"""
    with log_external_call("weather:jma-amedas-latest-time") as fields:
        cached = _latest_time_cache.get(_LATEST_TIME_CACHE_KEY)
        if cached is not None:
            fields["cache"] = "hit"
            return cached
        fields["cache"] = "miss"
        try:
            response = await client.get(AMEDAS_LATEST_TIME_URL, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
            return None
        if not isinstance(data, list) or not data:
            fields["result"] = "error"
            fields["error_type"] = "unexpected_shape"
            return None
        fields["result"] = "ok"
        latest = data[0]
        _latest_time_cache[_LATEST_TIME_CACHE_KEY] = latest
        return latest


async def fetch_observation_map(client: httpx.AsyncClient, timestamp: str) -> dict | None:
    """指定時刻（fetch_latest_observation_timeが返すISO文字列）の全観測所ぶんの生観測値を取得する。

    URLはYYYYMMDDHHMMSS形式のコンパクトなタイムスタンプを要求するため、呼び出し元
    （jma_amedas_service.py）がISO文字列から変換して渡す。
    """
    with log_external_call("weather:jma-amedas-observation", timestamp=timestamp) as fields:
        try:
            response = await client.get(
                AMEDAS_OBSERVATION_URL_TEMPLATE.format(timestamp=timestamp), timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
            return None
        fields["result"] = "ok"
        return data
