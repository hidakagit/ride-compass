import asyncio

import httpx

from app.infrastructure import tile_cache
from app.infrastructure.debug_log import error_type_label, log_external_call

UPSTREAM_HOST = "https://tiles.openfreemap.org"
# 書き換え前（上流そのまま）のJSONを保存するキャッシュキーの接頭辞。
_RAW_JSON_CACHE_PREFIX = "basemap-raw/"


class BasemapNotFound:
    """要求された部品が配信元に存在しないこと（404）を確認済みという事実を表すセンチネル。"""


BASEMAP_NOT_FOUND = BasemapNotFound()


class BasemapClient:
    """OpenFreeMapの地図タイル関連リソース（スタイルJSON・TileJSON・スプライト・グリフ・タイル）を
    透過的にプロキシしつつファイルシステムにキャッシュする（tile_cache）。

    スタイルJSON/TileJSONはOpenFreeMap本体への絶対URLを内包しているため、Content-TypeがJSONの
    レスポンスに限り、そのURLを自分自身（`proxy_base_url`、例: http://localhost:8000/api/basemap）
    への絶対URLに書き換える。MapLibreは相対URLをスタイル自身の取得元ではなく**ページのオリジン**に
    対して解決してしまう（spriteURLに至っては相対URLを明示的に拒否する）ため、相対パスではなく
    絶対URLへの書き換えが必須。

    書き換えはキャッシュに保存する前ではなく返す直前に行い、キャッシュには上流の内容をそのまま
    置く（キャッシュキーも`_RAW_JSON_CACHE_PREFIX`で書き換え済み世代と分ける）。`proxy_base_url`
    の設定変更がキャッシュを消さずに即座に反映されるようにするため。
    """

    def __init__(self, http_client: httpx.AsyncClient, proxy_base_url: str):
        self._http_client = http_client
        self._proxy_base_url = proxy_base_url

    async def get(self, path: str) -> tuple[bytes, str] | BasemapNotFound | None:
        with log_external_call("basemap:openfreemap", path=path) as fields:
            # tile_cacheの読み書きは同期的なディスクI/O。基礎地図読み込み時は数十件のタイル/フォント
            # リクエストが同時に来るため、awaitせず直接呼ぶとイベントループ全体をブロックし、
            # 同時に処理中の他のリクエスト（ルート生成等）が数十秒単位で詰まる。
            cached = await asyncio.to_thread(tile_cache.get, path)
            if cached is not None and "json" in cached[1]:
                # 素の鍵が持ってよいのは書き換えの要らない内容だけ。JSONがここにあるのは
                # 生の内容を_RAW_JSON_CACHE_PREFIX側へ分ける前の世代が書いたもので、当時の
                # proxy_base_urlが焼き付いている。採用せず、生キャッシュ→上流の順で引き直す。
                fields["stale"] = "rewritten-json"
                cached = None
            if cached is not None:
                fields["cache"] = "hit"
                return cached
            cached_json = await asyncio.to_thread(tile_cache.get, _RAW_JSON_CACHE_PREFIX + path)
            if cached_json is not None:
                fields["cache"] = "hit"
                content, content_type = cached_json
                return self._rewrite_upstream_urls(content), content_type
            fields["cache"] = "miss"

            try:
                response = await self._http_client.get(f"{UPSTREAM_HOST}/{path}")
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    # 配信元が用意していない部品（書体の一部等）。上流障害ではないため、
                    # エラー扱い（WARNING・/api/debug/statsのerror集計）にしない。
                    fields["result"] = "ok"
                    fields["status"] = 404
                    return BASEMAP_NOT_FOUND
                fields["result"] = "error"
                fields["error"] = repr(exc)
                fields["error_type"] = error_type_label(exc)
                return None
            except httpx.HTTPError as exc:
                fields["result"] = "error"
                fields["error"] = repr(exc)
                fields["error_type"] = error_type_label(exc)
                return None

            fields["result"] = "ok"
            fields["status"] = response.status_code
            content_type = response.headers.get("content-type", "application/octet-stream")
            content = response.content
            if "json" in content_type:
                await asyncio.to_thread(tile_cache.set, _RAW_JSON_CACHE_PREFIX + path, content, content_type)
                return self._rewrite_upstream_urls(content), content_type

            await asyncio.to_thread(tile_cache.set, path, content, content_type)
            return content, content_type

    def _rewrite_upstream_urls(self, content: bytes) -> bytes:
        """書き換えるのはURLとして始まる出現（引用符に続くもの）だけで、地の文に現れる
        上流の名前——出典の表記等——はそのまま残す。"""
        return content.replace(f'"{UPSTREAM_HOST}'.encode(), f'"{self._proxy_base_url}'.encode())
