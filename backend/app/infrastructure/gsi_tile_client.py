import asyncio

import httpx
from cachetools import LRUCache

from app.infrastructure import tile_cache
from app.infrastructure.debug_log import error_type_label, log_external_call

UPSTREAM_HOST = "https://cyberjapandata.gsi.go.jp"

#: 整備区域外の記憶に使う上限付きLRUの大きさ（キー=path）。
NOT_FOUND_MAX_ENTRIES = 2000


class GsiTileNotFound:
    """指定パスのタイルが上流（GSI）に存在しないこと（404）を確認済みという
    キャッシュ済みの事実を表すセンチネル。"""


GSI_TILE_NOT_FOUND = GsiTileNotFound()


class GsiTileClient:
    """国土地理院のタイル（色別標高図・標高タイル等）をパスで指定して透過的にプロキシしつつ
    ファイルシステムにキャッシュする。

    製品ごとの解釈は持たない——標高タイルをMapLibreが読む形へ移す変換は
    `services/terrain_tile_service.py`が担う。地理院タイルは時刻依存パラメータを持たない
    静的データのため、キャッシュにTTLは要らない。
    """

    def __init__(self, http_client: httpx.AsyncClient, not_found_paths: LRUCache):
        """`not_found_paths`は**呼び出し側が持つ**。

        地理院のタイルは整備区域外で404を返す（恒久的に正しい事実で、再取得しても変わらない）。
        このクライアントはリクエストごとに作られるため、記憶を自分で持つと毎回空になる。
        一方でプロセスより長く持つとGSI側の整備区域が広がったときに取り直す機会が無くなるので、
        `tile_cache`の永続ファイルへは書かず、渡された入れ物へだけ残す。
        """
        self._http_client = http_client
        self._not_found_paths = not_found_paths

    async def get(self, path: str) -> tuple[bytes, str] | GsiTileNotFound | None:
        if path in self._not_found_paths:
            return GSI_TILE_NOT_FOUND
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
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    # 整備区域外。珍しくない正常系のため、エラー扱い（WARNING・
                    # /api/debug/statsのerror集計）にしない。
                    fields["result"] = "ok"
                    fields["status"] = 404
                    self._not_found_paths[path] = None
                    return GSI_TILE_NOT_FOUND
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
            content_type = response.headers.get("content-type", "image/png")
            content = response.content
            await asyncio.to_thread(tile_cache.set, path, content, content_type)
            return content, content_type
