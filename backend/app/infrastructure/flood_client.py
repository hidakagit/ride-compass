"""JMA指定河川洪水予報APIのクライアント。

`https://www.jma.go.jp/bosai/flood/data/r8/flood_xml.json`は全国の現在発表中/直近解除済みの
指定河川洪水予報を1つの配列で返す（府県別・河川別に分かれておらず1回のGETで完結する）。
jma_warning_client.pyと同じ理由（更新頻度がOpen-Meteoほど高くない、機械アクセス制限の
明記なし）で再試行は設けず、TTLキャッシュのみで済ませる。取得失敗はNoneを返す。
"""

import httpx
from cachetools import TTLCache

from app.infrastructure.simple_api_client import UnexpectedShapeError, cached_fetch

FLOOD_API_URL = "https://www.jma.go.jp/bosai/flood/data/r8/flood_xml.json"

# 発表は数十分単位で更新されうるため、JMA警報（jma_warning_client.py）と同じ10分TTL。
_FLOOD_CACHE_TTL_SECONDS = 10 * 60

REQUEST_TIMEOUT = httpx.Timeout(connect=3.0, read=8.0, write=5.0, pool=5.0)

# キー無しの単一値キャッシュ（全国1本の電文一覧のため、固定キーで代用）。
_FLOOD_CACHE_KEY = "flood"
_flood_cache: TTLCache = TTLCache(maxsize=1, ttl=_FLOOD_CACHE_TTL_SECONDS)


async def fetch_flood_documents(client: httpx.AsyncClient) -> list | None:
    """全国の指定河川洪水予報の電文一覧を取得する。1エントリ=1河川の最新状態
    （発表・継続・解除のいずれか）で、河川ごとに配列内で更新される
    （解除された河川はcode=10のまま配列に残り続ける）。"""

    async def fetch() -> list:
        response = await client.get(FLOOD_API_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise UnexpectedShapeError("flood documents response is not a list")
        return data

    return await cached_fetch(_flood_cache, _FLOOD_CACHE_KEY, "weather:jma-flood", fetch)
