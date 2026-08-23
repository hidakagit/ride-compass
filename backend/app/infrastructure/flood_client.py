"""JMA指定河川洪水予報APIのクライアント（改善計画T212、T176調査で発見）。

`https://www.jma.go.jp/bosai/flood/data/r8/flood_xml.json`は全国の現在発表中/直近解除済みの
指定河川洪水予報を1つの配列で返す（府県別・河川別に分かれておらず1回のGETで完結する）。
T205のjma_warning_client.pyと同じ理由（更新頻度がOpen-Meteoほど高くない、機械アクセス制限の
明記なし）でtenacity再試行は設けず、TTLキャッシュのみで済ませる。取得失敗はNoneを返す。
"""

import httpx
from cachetools import TTLCache

from app.infrastructure.debug_log import error_type_label, log_external_call

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
    （実機確認、2026-08-22: 解除された河川はcode=10のまま配列に残り続ける）。"""
    with log_external_call("weather:jma-flood") as fields:
        cached = _flood_cache.get(_FLOOD_CACHE_KEY)
        if cached is not None:
            fields["cache"] = "hit"
            return cached
        fields["cache"] = "miss"
        try:
            response = await client.get(FLOOD_API_URL, timeout=REQUEST_TIMEOUT)
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
        _flood_cache[_FLOOD_CACHE_KEY] = data
        return data
