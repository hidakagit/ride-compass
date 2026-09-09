"""地域タイル系エンドポイント（路面・POI・事故）で共通のHTTP層。

region.py（路面/POIタイル）とaccidents.py（事故タイル）が、座標検証と応答の組み立てを
それぞれ個別に実装するのを避けるため共有する。レート制限は地域タイル系に限らず全router
共通の`app.api.dependencies.enforce_rate_limit`を使う（本モジュールの対象外）。
"""

from fastapi import HTTPException, Response

from app.domain.region import ROAD_TILE_MAX_ZOOM, ROAD_TILE_MIN_ZOOM
from app.services.tile_serving import MVT_CONTENT_TYPE, TileResponse


def validate_tile_coords(z: int, x: int, y: int) -> None:
    """路面・POI・事故タイルで共通のズーム/座標範囲チェック
    （POI・事故タイルも路面レイヤーと同じズーム範囲に準拠する）。
    """
    # MapLibre側もvector sourceのminzoom/maxzoomでこの範囲外は要求しないが、
    # 直接APIを叩かれた場合の安全弁として範囲外は拒否する。
    if z < ROAD_TILE_MIN_ZOOM or z > ROAD_TILE_MAX_ZOOM:
        raise HTTPException(status_code=400, detail="対応していないズームレベルです。")
    # x/yがそのズームレベルで存在しうる範囲（0 <= x,y < 2**z）を外れると、
    # domain/region.pyのtile_bounds_lonlatがmath.sinhでOverflowErrorを送出しうるため、
    # ここで先に弾く（例: 直接APIを叩かれてy=10**18のような極端な値が渡された場合）。
    tile_index_max = 2**z
    if not (0 <= x < tile_index_max) or not (0 <= y < tile_index_max):
        raise HTTPException(status_code=400, detail="タイル座標が範囲外です。")


def tile_response(tile: TileResponse) -> Response:
    """タイル応答を組み立てる。

    通常は`api/cache_policy.py`の対応表（`BATCH_TILE`）がミドルウェアで`Cache-Control`を
    付けるが、一時的な失敗で空タイルを返した場合だけは`no-store`を明示して、その空白が
    利用者のブラウザへ1時間残らないようにする（`TileResponse`のdocstring参照）。
    """
    headers = None if tile.cacheable else {"Cache-Control": "no-store"}
    return Response(content=tile.content, media_type=MVT_CONTENT_TYPE, headers=headers)
