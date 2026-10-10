"""JMA指定河川洪水予報APIのクライアント。

`https://www.jma.go.jp/bosai/flood/data/r8/flood_xml.json`は全国の現在発表中/直近解除済みの
指定河川洪水予報を1つの配列で返す（府県別・河川別に分かれておらず1回のGETで完結する）。
jma_warning_client.pyと同じ理由（更新頻度が高くない、機械アクセス制限の
明記なし）で再試行は設けず、TTLキャッシュのみで済ませる。取得失敗はNoneを返す。
電文の形はここで解き、呼び出し元へは`FloodBulletin`で渡す。

電文のコード→段の表は、気象庁「指定河川洪水予報」電文フォーマット解説資料の表２
（令和8年度出水期以降の対応表）を典拠とする。
"""

import httpx
from cachetools import TTLCache

from app.domain.flood_forecast import FloodBulletin
from app.domain.warning_levels import WarningBadgeLevel
from app.infrastructure.simple_api_client import cached_fetch, get_json

FLOOD_API_URL = "https://www.jma.go.jp/bosai/flood/data/r8/flood_xml.json"

# 発表は数十分単位で更新されうるため、JMA警報（jma_warning_client.py）と同じ10分TTL。
_FLOOD_CACHE_TTL_SECONDS = 10 * 60

REQUEST_TIMEOUT = httpx.Timeout(connect=3.0, read=8.0, write=5.0, pool=5.0)

# キー無しの単一値キャッシュ（全国1本の電文一覧のため、固定キーで代用）。
_FLOOD_CACHE_KEY = "flood"


def new_flood_cache() -> TTLCache:
    """`fetch_flood_documents`へ渡すキャッシュ。リクエストをまたいで持つのは組み立てる側（`api/dependencies.py`）。"""
    return TTLCache(maxsize=1, ttl=_FLOOD_CACHE_TTL_SECONDS)

# 電文の`item.code`→段。警報（jma_warning_client.py）と異なり、状態の文字列ではなくコード自体が
# 発表・継続・上位の警報の解除による引き下げを分ける（例: "20"=新規発表、"21"=継続、"22"=引き下げ）。
# 完全解除（今は発表が無い）を表すコード"10"は載せない——載っているコードはどれも発表中、が表の意味である。
_CODE_LEVELS: dict[str, WarningBadgeLevel] = {
    "20": "advisory",
    "21": "advisory",
    "22": "advisory",
    "30": "warning",
    "31": "warning",
    "40": "severe_warning",
    "41": "severe_warning",
    "51": "emergency_warning",
    "53": "emergency_warning",
}

#: 運用の電文の`status`。これ以外（訓練・試験）の電文は上へ渡さない。
_OPERATIONAL_STATUS = "通常"


def _parse_bulletin(entry: dict) -> FloodBulletin:
    # 文字の項目は、キーが無くても値がnullでも空の文字として読む（1件の欠けで取り出しごと落とさない）。
    item = entry.get("item") or {}
    code = item.get("code")
    return FloodBulletin(
        level=_CODE_LEVELS.get(code) if isinstance(code, str) else None,
        class20_codes=tuple(entry.get("class20Codes") or ()),
        class10_codes=tuple(entry.get("class10Codes") or ()),
        river_code=entry.get("riverCode") or "",
        river_name=entry.get("riverName") or "",
        condition=item.get("condition") or "",
    )


async def fetch_flood_documents(client: httpx.AsyncClient, cache: TTLCache) -> list[FloodBulletin] | None:
    """全国の指定河川洪水予報のうち運用の電文。1件=1河川の最新状態（発表・継続・解除の
    いずれか）で、解除された河川も解除のコードのまま残り続ける。"""

    async def fetch() -> list[FloodBulletin]:
        payload = await get_json(client, FLOOD_API_URL, list, "flood bulletins are", timeout=REQUEST_TIMEOUT)
        return [
            _parse_bulletin(entry)
            for entry in payload
            if isinstance(entry, dict) and entry.get("status") == _OPERATIONAL_STATUS
        ]

    return await cached_fetch("weather:jma-flood", fetch, cache=cache, key=_FLOOD_CACHE_KEY)
