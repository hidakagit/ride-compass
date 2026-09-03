import asyncio

import httpx

from app.infrastructure import tile_cache
from app.infrastructure.debug_log import error_type_label, log_external_call

UPSTREAM_HOST = "https://cyberjapandata.gsi.go.jp"


class GsiReliefTileClient:
    """国土地理院 色別標高図タイル（`{z}/{x}/{y}.png`）を透過的にプロキシしつつ
    ファイルシステムにキャッシュする（改善計画T572）。`basemap_client.py`と同じ
    「pathを丸ごとプロキシ＋`tile_cache`の永続ファイルキャッシュ」方式だが、
    タイルはPNG単体でJSON応答（basemapのスタイルJSON等）を持たないため、URL書き換えは
    不要。地理院タイルは`basetime`/`validtime`のような時刻依存パラメータを持たない
    静的データのため、TTL付きキャッシュ（`jma_tile_client.py`のtargetTimes分岐）も不要。
    """

    def __init__(self, http_client: httpx.AsyncClient):
        self._http_client = http_client

    async def get(self, path: str) -> tuple[bytes, str] | None:
        with log_external_call("gsi-relief-tile", path=path) as fields:
            # tile_cacheの読み書きは同期的なディスクI/O。basemap_client.pyと同じ理由
            # （多数のタイルリクエストが同時に来るとイベントループをブロックする）で
            # asyncio.to_threadへ逃がす。
            cached = await asyncio.to_thread(tile_cache.get, path)
            if cached is not None:
                fields["cache"] = "hit"
                return cached
            fields["cache"] = "miss"

            try:
                response = await self._http_client.get(f"{UPSTREAM_HOST}/{path}")
                response.raise_for_status()
            except httpx.HTTPError as exc:
                fields["result"] = "error"
                fields["error"] = repr(exc)
                fields["error_type"] = error_type_label(exc)
                return None

            fields["result"] = "ok"
            fields["status"] = getattr(response, "status_code", None)
            content_type = response.headers.get("content-type", "image/png")
            content = response.content
            await asyncio.to_thread(tile_cache.set, path, content, content_type)
            return content, content_type
