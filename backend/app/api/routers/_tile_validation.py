"""地域タイル系エンドポイント（路面・POI・事故）で共通の座標検証。

region.py（路面/POIタイル）とaccidents.py（事故タイル）が同じズーム範囲チェック・
`2**z`座標範囲チェックを個別に実装するのを避けるため、共有可能な形へ切り出した。
レート制限は地域タイル系に限らず全router共通の`app.api.dependencies.enforce_rate_limit`
を使う（本モジュールの対象外）。
"""

from fastapi import HTTPException

from app.domain.region import ROAD_TILE_MAX_ZOOM, ROAD_TILE_MIN_ZOOM


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
