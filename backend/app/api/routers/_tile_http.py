"""z/x/yで配るタイルのエンドポイントで共通のHTTP層。

region.py（路面/点/土地被覆タイル）・gsi_tile.py（標高タイル）が、
座標検証と応答の組み立てをそれぞれ個別に実装するのを避けるため共有する。レート制限は地域タイル系に限らず全router
共通の`app.api.rate_limit.enforce_rate_limit`を使う（本モジュールの対象外）。
"""

from fastapi import Response
from fastapi.exceptions import RequestValidationError
from pydantic_core import PydanticCustomError

from app.api.cache_policy import NO_STORE
from app.domain.region import check_tile_index
from app.infrastructure.media_types import MVT_CONTENT_TYPE
from app.infrastructure.region_tile_cache import TileResponse


def validate_tile_coords(z: int, x: int, y: int) -> None:
    """タイルで共通の座標の検査。ズームの範囲と列・行の下限は経路の引数の型（レイヤーのズームの型・
    `domain/region.py: TileIndex`）が見るので、ここは列・行の上限（ズームに依る）だけを、型の検査と同じ422で断る。

    MapLibre側もsourceのminzoom/maxzoomと世界の範囲の外は要求しないが、直接APIを叩かれた場合の安全弁。
    """
    try:
        check_tile_index(z, x, y)
    except PydanticCustomError as error:
        raise RequestValidationError(
            [{"type": error.type, "loc": ("path",), "msg": error.message(), "input": {"z": z, "x": x, "y": y}}]
        ) from None


def tile_response(tile: TileResponse, media_type: str = MVT_CONTENT_TYPE) -> Response:
    """タイル応答を組み立てる。

    通常は`api/cache_policy.py`の対応表（`BATCH_TILE`）がミドルウェアで`Cache-Control`を
    付けるが、一時的な失敗で空タイルを返した場合だけは`no-store`を明示して、その空白が
    利用者のブラウザへ1時間残らないようにする（`TileResponse`のdocstring参照）。
    """
    headers = None if tile.cacheable else {"Cache-Control": NO_STORE.header()}
    return Response(content=tile.content, media_type=media_type, headers=headers)
