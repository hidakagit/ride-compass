"""JMA警報・注意報API、地域マスタ(area.json)、国土地理院逆ジオコーダのクライアント。

いずれもOpen-Meteoと比べて更新頻度が低い（area.jsonは行政区画変更でしか変わらず、
警報自体も分単位で動くOpen-Meteoの予報と比べれば粗い）ため、weather_client.pyのような
429前提のtenacity再試行は設けない。取得失敗はNoneを返し、呼び出し元
（warning_service.py）が「警報なし」として扱う（安全側ではない既知のトレードオフを
WBGTと共有する）。
"""

import httpx
from cachetools import TTLCache

from app.infrastructure.simple_api_client import UnexpectedShapeError, cached_fetch

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

# maxsizeは実運用で想定されるキー数（市区町村約1,700・府県予報区約50）に十分な余裕を
# 持たせた上限（LRU的なサイズ超過退避が実質発生しない値。TTL切れによる鮮度管理が主）。
_muni_code_cache: TTLCache = TTLCache(maxsize=4096, ttl=_MUNI_CACHE_TTL_SECONDS)
_area_data_cache: TTLCache = TTLCache(maxsize=1, ttl=_AREA_DATA_CACHE_TTL_SECONDS)
_warning_cache: TTLCache = TTLCache(maxsize=256, ttl=_WARNING_CACHE_TTL_SECONDS)
_AREA_DATA_CACHE_KEY = "area"


async def fetch_municipality_code(client: httpx.AsyncClient, lat: float, lon: float) -> str | None:
    """国土地理院の逆ジオコーダで緯度経度→JIS市区町村コード（5桁）を引く。"""
    key = (round(lat, _MUNI_CACHE_PRECISION), round(lon, _MUNI_CACHE_PRECISION))

    async def fetch() -> str | None:
        response = await client.get(GSI_REVERSE_GEOCODER_URL, params={"lat": lat, "lon": lon}, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        return data.get("results", {}).get("muniCd")

    return await cached_fetch(
        _muni_code_cache,
        key,
        "weather:gsi-reverse-geocode",
        fetch,
        catch=(httpx.HTTPError, ValueError, AttributeError),
        lat=key[0],
        lon=key[1],
    )


async def fetch_area_data(client: httpx.AsyncClient) -> dict | None:
    """気象庁の地域マスタ(area.json)を取得する。行政区画変更以外では変化しないため
    プロセス内で長時間キャッシュする。"""

    async def fetch() -> dict:
        response = await client.get(JMA_AREA_JSON_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()

    return await cached_fetch(_area_data_cache, _AREA_DATA_CACHE_KEY, "weather:jma-area", fetch)


async def fetch_warning_documents(client: httpx.AsyncClient, office_code: str) -> list | None:
    """指定した府県予報区コードの警報・注意報電文一覧（r8スキーマ、令和8年5月29日の
    運用切替以降の現行API）を取得する。

    JMAは大雨・土砂災害・高潮・暴風/暴風雪・波浪・大雪・その他の注意報を別々の電文
    （VPWW55〜61）として発表するため、レスポンスは1地点でも複数電文の配列になる
    （domain/jma_warning.py参照）。"""

    async def fetch() -> list:
        response = await client.get(JMA_WARNING_URL_TEMPLATE.format(office_code=office_code), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise UnexpectedShapeError("warning documents response is not a list")
        return data

    return await cached_fetch(_warning_cache, office_code, "weather:jma-warning", fetch, office_code=office_code)
