"""JMA警報・注意報API、地域マスタ(area.json)のクライアント。

どちらも更新頻度が低い（area.jsonは行政区画変更でしか変わらず、
警報自体も分単位では動かない）ため、429前提の再試行は設けない。取得失敗はNoneを返し、呼び出し元
（warning_service.py）が「警報なし」として扱う（安全側ではない既知のトレードオフを
WBGTと共有する）。
"""

import httpx
from cachetools import TTLCache

from app.infrastructure.simple_api_client import cached_fetch

JMA_AREA_JSON_URL = "https://www.jma.go.jp/bosai/common/const/area.json"
JMA_WARNING_URL_TEMPLATE = "https://www.jma.go.jp/bosai/warning/data/r8/{office_code}.json"

# area.jsonは行政区画変更でしか変わらない静的に近いデータのため長いTTL。
_AREA_DATA_CACHE_TTL_SECONDS = 24 * 60 * 60

# 警報は数分〜数十分単位で更新されうるため、area.jsonより短いTTL。
_WARNING_CACHE_TTL_SECONDS = 10 * 60

REQUEST_TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0)

# maxsizeは実運用で想定されるキー数（府県予報区約50）に十分な余裕を持たせた上限
# （LRU的なサイズ超過退避が実質発生しない値。TTL切れによる鮮度管理が主）。
_area_data_cache: TTLCache = TTLCache(maxsize=1, ttl=_AREA_DATA_CACHE_TTL_SECONDS)
_warning_cache: TTLCache = TTLCache(maxsize=256, ttl=_WARNING_CACHE_TTL_SECONDS)
_AREA_DATA_CACHE_KEY = "area"


async def fetch_area_data(client: httpx.AsyncClient) -> dict | None:
    """気象庁の地域マスタ(area.json)を取得する。行政区画変更以外では変化しないため
    プロセス内で長時間キャッシュする。"""

    async def fetch() -> dict:
        response = await client.get(JMA_AREA_JSON_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()

    return await cached_fetch(
        "weather:jma-area", fetch, cache=_area_data_cache, key=_AREA_DATA_CACHE_KEY
    )


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
        return data

    return await cached_fetch(
        "weather:jma-warning",
        fetch,
        cache=_warning_cache,
        key=office_code,
        expect=list,
        office_code=office_code,
    )
