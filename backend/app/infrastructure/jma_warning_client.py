"""JMA警報・注意報API、地域マスタ(area.json)、国土地理院逆ジオコーダのクライアント
（改善計画T205）。

いずれもOpen-Meteoと比べて更新頻度が低い（area.jsonは行政区画変更でしか変わらず、
警報自体も分単位で動くOpen-Meteoの予報と比べれば粗い）ため、weather_client.pyのような
429前提のtenacity再試行は設けない。取得失敗はNoneを返し、呼び出し元
（warning_service.py）が「警報なし」として扱う（T205完了条件「取得失敗時は警告なし」、
安全側ではない既知のトレードオフをT174と共有する）。
"""

import time

import httpx

from app.infrastructure.debug_log import error_type_label, log_external_call

GSI_REVERSE_GEOCODER_URL = "https://mreversegeocoder.gsi.go.jp/reverse-geocoder/LonLatToAddress"
JMA_AREA_JSON_URL = "https://www.jma.go.jp/bosai/common/const/area.json"
JMA_WARNING_URL_TEMPLATE = "https://www.jma.go.jp/bosai/warning/data/r8/{office_code}.json"

# 緯度経度→市区町村は数百m単位でしか変わらないため、天候(2桁丸め)よりやや細かく丸める。
_MUNI_CACHE_PRECISION = 3
_MUNI_CACHE_TTL_SECONDS = 24 * 60 * 60

# area.jsonは行政区画変更でしか変わらない静的に近いデータのため長いTTL。
_AREA_DATA_CACHE_TTL_SECONDS = 24 * 60 * 60

# 警報は数分〜数十分単位で更新されうるため、他の2つより短いTTL。
_WARNING_CACHE_TTL_SECONDS = 10 * 60

REQUEST_TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0)

_muni_code_cache: dict[tuple[float, float], tuple[float, str | None]] = {}
_area_data_cache: tuple[float, dict] | None = None
_warning_cache: dict[str, tuple[float, list]] = {}


async def fetch_municipality_code(client: httpx.AsyncClient, lat: float, lon: float) -> str | None:
    """国土地理院の逆ジオコーダで緯度経度→JIS市区町村コード（5桁）を引く。"""
    key = (round(lat, _MUNI_CACHE_PRECISION), round(lon, _MUNI_CACHE_PRECISION))
    with log_external_call("weather:gsi-reverse-geocode", lat=key[0], lon=key[1]) as fields:
        cached = _muni_code_cache.get(key)
        if cached is not None and time.time() - cached[0] < _MUNI_CACHE_TTL_SECONDS:
            fields["cache"] = "hit"
            return cached[1]
        fields["cache"] = "miss"
        try:
            response = await client.get(
                GSI_REVERSE_GEOCODER_URL, params={"lat": lat, "lon": lon}, timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
            muni_cd = data.get("results", {}).get("muniCd")
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
            return None
        fields["result"] = "ok"
        _muni_code_cache[key] = (time.time(), muni_cd)
        return muni_cd


async def fetch_area_data(client: httpx.AsyncClient) -> dict | None:
    """気象庁の地域マスタ(area.json)を取得する。行政区画変更以外では変化しないため
    プロセス内で長時間キャッシュする。"""
    global _area_data_cache
    with log_external_call("weather:jma-area") as fields:
        if _area_data_cache is not None and time.time() - _area_data_cache[0] < _AREA_DATA_CACHE_TTL_SECONDS:
            fields["cache"] = "hit"
            return _area_data_cache[1]
        fields["cache"] = "miss"
        try:
            response = await client.get(JMA_AREA_JSON_URL, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
            return None
        fields["result"] = "ok"
        _area_data_cache = (time.time(), data)
        return data


async def fetch_warning_documents(client: httpx.AsyncClient, office_code: str) -> list | None:
    """指定した府県予報区コードの警報・注意報電文一覧（r8スキーマ、令和8年5月29日の
    運用切替以降の現行API）を取得する。

    JMAは大雨・土砂災害・高潮・暴風/暴風雪・波浪・大雪・その他の注意報を別々の電文
    （VPWW55〜61）として発表するため、レスポンスは1地点でも複数電文の配列になる
    （domain/jma_warning.py参照）。"""
    with log_external_call("weather:jma-warning", office_code=office_code) as fields:
        cached = _warning_cache.get(office_code)
        if cached is not None and time.time() - cached[0] < _WARNING_CACHE_TTL_SECONDS:
            fields["cache"] = "hit"
            return cached[1]
        fields["cache"] = "miss"
        try:
            response = await client.get(
                JMA_WARNING_URL_TEMPLATE.format(office_code=office_code), timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
            return None
        if not isinstance(data, list):
            fields["result"] = "error"
            fields["error_type"] = "unexpected_shape"
            return None
        fields["result"] = "ok"
        _warning_cache[office_code] = (time.time(), data)
        return data
