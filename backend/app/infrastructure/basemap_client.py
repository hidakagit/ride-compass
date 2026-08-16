import asyncio

import httpx

from app.infrastructure import tile_cache
from app.infrastructure.debug_log import error_type_label, log_external_call

UPSTREAM_HOST = "https://tiles.openfreemap.org"


class BasemapClient:
    """OpenFreeMapの地図タイル関連リソース（スタイルJSON・TileJSON・スプライト・グリフ・タイル）を
    透過的にプロキシしつつファイルシステムにキャッシュする（tile_cache）。

    スタイルJSON/TileJSONはOpenFreeMap本体への絶対URLを内包しているため、Content-TypeがJSONの
    レスポンスに限り、そのURLを自分自身（`proxy_base_url`、例: http://localhost:8000/api/basemap）
    への絶対URLに書き換える。MapLibreは相対URLをスタイル自身の取得元ではなく**ページのオリジン**に
    対して解決してしまう（spriteURLに至っては相対URLを明示的に拒否する）ため、相対パスではなく
    絶対URLへの書き換えが必須。
    """

    def __init__(self, http_client: httpx.AsyncClient, proxy_base_url: str):
        self._http_client = http_client
        self._proxy_base_url = proxy_base_url

    async def get(self, path: str) -> tuple[bytes, str] | None:
        with log_external_call("basemap:openfreemap", path=path) as fields:
            # tile_cacheの読み書きは同期的なディスクI/O。基礎地図読み込み時は数十件のタイル/フォント
            # リクエストが同時に来るため、awaitせず直接呼ぶとイベントループ全体をブロックし、
            # 同時に処理中の他のリクエスト（ルート生成等）が数十秒単位で詰まることを実機確認した。
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
            content_type = response.headers.get("content-type", "application/octet-stream")
            content = response.content
            if "json" in content_type:
                content = content.replace(f'"{UPSTREAM_HOST}'.encode(), f'"{self._proxy_base_url}'.encode())

            await asyncio.to_thread(tile_cache.set, path, content, content_type)
            return content, content_type
