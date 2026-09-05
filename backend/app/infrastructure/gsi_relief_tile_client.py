import asyncio
from collections import OrderedDict

import httpx

from app.infrastructure import tile_cache
from app.infrastructure.debug_log import error_type_label, log_external_call

UPSTREAM_HOST = "https://cyberjapandata.gsi.go.jp"

# 改善計画T605: 色別標高図タイルも、DEMタイル（elevation_client.py: _CoverageGap）と同じ
# GSIホストの整備区域外で404を返す（恒久的に正しい事実、再フェッチしても変わらない）。
# プロセス内メモリのみに留める（tile_cache.pyの永続ファイルキャッシュへは書かない——
# 将来GSI側の整備区域が広がった場合、プロセス再起動だけで再取得の機会が来るようにする）。
# 上限付きLRU（elevation_client.py: _tile_grid_cacheと同じ設計、キー=path）。
_NOT_FOUND_MAX_ENTRIES = 2000
_not_found_paths: "OrderedDict[str, None]" = OrderedDict()


class ReliefTileNotFound:
    """指定パスの色別標高図タイルが上流（GSI）に存在しないこと（404）を確認済みという
    キャッシュ済みの事実を表すセンチネル（elevation_client.py: _CoverageGapと同じ設計）。"""


RELIEF_TILE_NOT_FOUND = ReliefTileNotFound()


def _remember_not_found(path: str) -> None:
    _not_found_paths[path] = None
    _not_found_paths.move_to_end(path)
    if len(_not_found_paths) > _NOT_FOUND_MAX_ENTRIES:
        _not_found_paths.popitem(last=False)


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

    async def get(self, path: str) -> tuple[bytes, str] | ReliefTileNotFound | None:
        if path in _not_found_paths:
            return RELIEF_TILE_NOT_FOUND
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
                    _remember_not_found(path)
                    return RELIEF_TILE_NOT_FOUND
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
            fields["status"] = getattr(response, "status_code", None)
            content_type = response.headers.get("content-type", "image/png")
            content = response.content
            await asyncio.to_thread(tile_cache.set, path, content, content_type)
            return content, content_type
