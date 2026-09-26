"""JMA指定河川洪水予報APIのクライアント。

`https://www.jma.go.jp/bosai/flood/data/r8/flood_xml.json`は全国の現在発表中/直近解除済みの
指定河川洪水予報を1つの配列で返す（府県別・河川別に分かれておらず1回のGETで完結する）。
jma_warning_client.pyと同じ理由（更新頻度が高くない、機械アクセス制限の
明記なし）で再試行は設けず、TTLキャッシュのみで済ませる。取得失敗はNoneを返す。
電文の形はここで解き、呼び出し元へは`FloodBulletin`で渡す。
"""

import httpx
from cachetools import TTLCache

from app.domain.flood_forecast import FloodBulletin
from app.infrastructure.simple_api_client import UnexpectedShapeError, cached_fetch

FLOOD_API_URL = "https://www.jma.go.jp/bosai/flood/data/r8/flood_xml.json"

# 発表は数十分単位で更新されうるため、JMA警報（jma_warning_client.py）と同じ10分TTL。
_FLOOD_CACHE_TTL_SECONDS = 10 * 60

REQUEST_TIMEOUT = httpx.Timeout(connect=3.0, read=8.0, write=5.0, pool=5.0)

# キー無しの単一値キャッシュ（全国1本の電文一覧のため、固定キーで代用）。
_FLOOD_CACHE_KEY = "flood"
_flood_cache: TTLCache = TTLCache(maxsize=1, ttl=_FLOOD_CACHE_TTL_SECONDS)

#: 運用の電文の`status`。これ以外（訓練・試験）の電文は上へ渡さない。
_OPERATIONAL_STATUS = "通常"


def _parse_bulletin(entry: dict) -> FloodBulletin:
    # 文字の項目は、キーが無くても値がnullでも空の文字として読む（1件の欠けで取り出しごと落とさない）。
    item = entry.get("item") or {}
    return FloodBulletin(
        code=item.get("code"),
        class20_codes=tuple(entry.get("class20Codes") or ()),
        class10_codes=tuple(entry.get("class10Codes") or ()),
        river_code=entry.get("riverCode") or "",
        river_name=entry.get("riverName") or "",
        condition=item.get("condition") or "",
        report_datetime=entry.get("reportDatetime") or "",
    )


async def fetch_flood_documents(client: httpx.AsyncClient) -> list[FloodBulletin] | None:
    """全国の指定河川洪水予報のうち運用の電文。1件=1河川の最新状態（発表・継続・解除の
    いずれか）で、解除された河川も解除のコードのまま残り続ける。"""

    async def fetch() -> list[FloodBulletin]:
        response = await client.get(FLOOD_API_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise UnexpectedShapeError(f"flood bulletins are {type(payload).__name__}")
        return [
            _parse_bulletin(entry)
            for entry in payload
            if isinstance(entry, dict) and entry.get("status") == _OPERATIONAL_STATUS
        ]

    return await cached_fetch("weather:jma-flood", fetch, cache=_flood_cache, key=_FLOOD_CACHE_KEY)
