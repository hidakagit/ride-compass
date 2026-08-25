"""地域タイル系エンドポイント（路面・POI・事故）で共通のレート制限・座標検証。

region.py（路面/POIタイル）とaccidents.py（事故タイル）が同じズーム範囲チェック・
`2**z`座標範囲チェック・レート制限処理を個別に実装していた（デッドコード監査で重複と
判明）ため、共有可能な形へ切り出した。挙動（ズーム範囲・座標範囲・エラー文言）は
元の実装から変更していない。
"""

from fastapi import HTTPException, Request

from app.api.dependencies import client_id
from app.domain.region import ROAD_TILE_MAX_ZOOM, ROAD_TILE_MIN_ZOOM
from app.infrastructure.debug_log import record_rate_limit_rejection
from app.infrastructure.rate_limiter import check_rate_limit


def check_tile_rate_limit(request: Request, prefix: str, limit_per_minute: int) -> None:
    """認証なしで叩ける地域タイル系エンドポイントへの簡易な歯止め（1クライアントIPあたり
    1分間の上限）。地域タイル・事故タイルはいずれもPostGISへの実問い合わせ・ディスク
    キャッシュ書き込みを伴うため、無制限に叩かれるとDB負荷やディスク消費に繋がる
    （詳細はrate_limiter.py）。キー・記録先の`prefix`、上限値`limit_per_minute`は
    タイル種別ごとに呼び出し元が指定する（路面/POIタイルは
    `settings.road_tile_rate_limit_per_minute`、事故タイルは
    `settings.accident_tile_rate_limit_per_minute`と別の設定値を使う）。
    """
    if not check_rate_limit(f"{prefix}:{client_id(request)}", limit_per_minute):
        record_rate_limit_rejection(prefix, client_id(request), f"{limit_per_minute}/min")
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")


def validate_tile_coords(z: int, x: int, y: int) -> None:
    """路面・POI・事故タイルで共通のズーム/座標範囲チェック
    （T54: POIタイルは既存の路面レイヤーと同じズーム範囲に準拠する。事故タイルも同じ範囲を使う）。
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
