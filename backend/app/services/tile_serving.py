"""地域タイル配信（路面/POI/事故）で共通のキャッシュ確認・取得・キャッシュ書き込み骨格。

`RegionService._get_tile`（路面/POIタイル）と`AccidentService.get_accident_tile`
（事故タイル）は、実際のタイル取得方法（カバレッジ判定・repositoryの呼び出し方・
バックグラウンドのRoad Graph構築トリガーの有無）は別だが、
「ファイルキャッシュ確認→ミスなら取得→取得成功ならキャッシュへ書いて返す→
取得不可(None)なら空タイルを返す」という外側の骨格（`log_external_call`・
`tile_cache` get/set）を個別実装していた（デッドコード監査で重複と判明）ため、
この骨格だけを共有する。取得不可の理由をどうWARNINGログへ出すか（文言・
`fields`への記録内容）はタイル種別ごとに異なる（路面/POIは「取込範囲外」、
事故は「repository未接続」等）ため、その判断・ログ出力は引き続き呼び出し元の
`fetch_tile`側の責務のまま残す。
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.infrastructure import tile_cache
from app.infrastructure.debug_log import log_external_call


@dataclass(frozen=True)
class TileResponse:
    """タイル本体と、それをブラウザへ長期キャッシュさせてよいかどうか。

    取得不可（`fetch_tile`が`None`）のとき返す空タイルには2種類ある——「取込範囲外で
    恒久的にデータが無い」場合と、「DB障害・混雑で一時的に取れなかった」場合である。
    後者を`api/cache_policy.py`の`BATCH_TILE`（1時間）でキャッシュさせると、サーバーが
    回復した後も利用者のブラウザにはその区画の空白が1時間残り続ける。サーバー側の
    ファイルキャッシュには書かない（下記`serve_cached_tile`参照）ため次のリクエストでは
    正しく生成され、**取り残されるのはブラウザ側だけ**という気づきにくい壊れ方をする。
    """

    content: bytes
    cacheable: bool = True


async def serve_cached_tile(
    *,
    z: int,
    x: int,
    y: int,
    cache_path: str,
    empty_tile: bytes,
    content_type: str,
    external_call_name: str,
    fetch_tile: Callable[[dict], Awaitable[bytes | None]],
) -> TileResponse:
    """キャッシュヒットならそれを返す。ミス時は`fetch_tile(fields)`を1回呼び、
    tile bytesが返れば`tile_cache`へ書いて返す。`None`が返れば「取得不可」として
    空タイル（`empty_tile`）を返す（WARNINGログ自体は`fetch_tile`側の責務）。

    取得不可が一時的な失敗（`fetch_tile`が`fields["postgis"] = "error"`を立てた場合）
    だったときは`cacheable=False`で返す。呼び出し元のルーターはこれを見て
    `Cache-Control: no-store`を明示する（`TileResponse`のdocstring参照）。
    """
    with log_external_call(external_call_name, z=z, x=x, y=y) as fields:
        cached = await asyncio.to_thread(tile_cache.get, cache_path)
        if cached is not None:
            fields["cache"] = "hit"
            content, _content_type = cached
            return TileResponse(content)
        fields["cache"] = "miss"

        tile_bytes = await fetch_tile(fields)
        if tile_bytes is None:
            fields["source"] = "uncovered_empty"
            # DB障害等の一時的な失敗と、取込範囲外（恒久的にデータが無い）を区別する。
            # 前者はブラウザへキャッシュさせず、回復後の次のリクエストで取り直させる。
            return TileResponse(empty_tile, cacheable=fields.get("postgis") != "error")

        fields["source"] = "postgis"
        fields["tile_bytes"] = len(tile_bytes)
        await asyncio.to_thread(tile_cache.set, cache_path, tile_bytes, content_type)
        return TileResponse(tile_bytes)
