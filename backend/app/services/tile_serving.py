"""タイル配信で共通の、キャッシュ確認・取得・キャッシュ書き込みの骨格。

取得不可の理由をどうWARNINGログへ出すか（文言・`fields`への記録内容）はタイル種別ごとに
違う（「取込範囲外」「DB障害」等）ため、その判断とログ出力は呼び出し元が渡す
`fetch_tile`の責務にしてある。
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.infrastructure import tile_cache
from app.infrastructure.debug_log import log_external_call


# MVT（Mapbox Vector Tile）のMIMEタイプ。タイルを作る側も配る側も同じ値を使う——別々に
# 持つと、片方だけ変えたときにキャッシュキー（content_type込み）と応答ヘッダがずれる。
MVT_CONTENT_TYPE = "application/vnd.mapbox-vector-tile"


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
    source_label: str = "postgis",
    persist: bool = True,
) -> TileResponse:
    """キャッシュにあればそれを、無ければ`fetch_tile`で作ったものを返す。

    取得不可が一時的な失敗（`fetch_tile`が`fields["postgis"] = "error"`を立てた場合）
    だったときは`cacheable=False`で返す。呼び出し元のルーターはこれを見て
    `Cache-Control: no-store`を明示する（`TileResponse`のdocstring参照）。

    `persist=False`はディスクへ書かずに返す。**どの世代の中身か分からないまま焼いたタイルを
    残さない**ため——ディスクの鍵は形の署名だけで世代を持たず、残すと後で世代が判明しても
    正しいものと区別できない（`infrastructure/cache_identity.py: UNKNOWN_REVISION`）。
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
            return TileResponse(empty_tile, cacheable=fields.get("postgis") != "error")

        # どこから作ったか（`source_label`）はタイル種別で違う。/api/debug/statsの内訳が
        # 実際の取得元と食い違わないよう、呼び出し元が名乗る。
        fields["source"] = source_label
        fields["tile_bytes"] = len(tile_bytes)
        fields["persisted"] = persist
        if persist:
            await asyncio.to_thread(tile_cache.set, cache_path, tile_bytes, content_type)
        return TileResponse(tile_bytes)
