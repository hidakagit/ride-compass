import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.dependencies import client_id, get_region_service
from app.config import settings
from app.domain.region import ROAD_TILE_MAX_ZOOM, ROAD_TILE_MIN_ZOOM
from app.infrastructure.debug_log import record_rate_limit_rejection
from app.infrastructure.rate_limiter import check_rate_limit
from app.services.region_service import RegionService

router = APIRouter()

# 地域タイル（路面・停止要因POI/交差点密度）の同時実行上限
# （settings.road_tile_max_concurrent、値の根拠はconfig.py参照）。
#
# かつて密集した都市部のタイルはPostGISから1万件超のway行を転送してPython側でMVT
# エンコードしており（実測: 東京駅付近z13タイルで約7.6秒）、地図の短時間パン/ズームで
# ブラウザが並列に大量のタイルを要求すると、この重い処理が同時に積み上がりCPUを奪い合い、
# Renderのヘルスチェックすら応答できず「Instance failed」でプロセスごと再起動される事故が
# 実機で発生した。現在はMVT生成をPostGIS側（ST_AsMVT、road_graph_repository.py）へ移して
# 1タイルのコストを大幅に下げたが、キャッシュミスのバーストが遠隔DB/Session poolerへ
# 無制限に並ぶのを防ぐ歯止めとして同時実行数制限は維持する。
#
# 上限超過分は即座に429を返すルート生成とは異なり、こちらは「待たせて全件処理する」
# （semaphoreの取得をブロックさせる）方式にしている。MapLibreは失敗したタイル要求を
# 自動再試行しないため、429にすると1画面に収まる範囲で上限を超えるタイル（皇居周辺のような
# 広い範囲では珍しくない）が永久に空白のまま描画されない不具合が実機で発生した。
# 待たせる方式でもRender再起動事故の再発防止という目的は変わらない（同時に重い処理が
# 走る数は上限のまま増えないため）。/healthはこのsemaphoreを経由しない別の同期ハンドラの
# ため、待機中のタイル要求に巻き込まれず応答し続けられる。
#
# 停止要因POI・交差点密度タイル（改善計画T54）も同じDB接続プールを取り合うため、
# 専用semaphoreを新設せずこれを共有する（プール上限15接続に対し、独立semaphoreを
# 追加すると2種のタイルの同時実行数の合計がプール上限を超えうる）。
_region_tile_semaphore = asyncio.Semaphore(settings.road_tile_max_concurrent)


def _check_tile_rate_limit(request: Request, prefix: str) -> None:
    """認証なしで叩ける地域タイルへの簡易な歯止め（1クライアントIPあたり1分間の上限）。
    地域タイルはPostGISへの実問い合わせ・ディスクキャッシュ書き込みを伴うため、
    無制限に叩かれるとDB負荷やディスク消費に繋がる（詳細はrate_limiter.py）。
    路面・POI/交差点密度タイルで同じ上限値（settings.road_tile_rate_limit_per_minute）を
    使うが、キー・記録先の`prefix`は種別ごとに分ける。
    """
    if not check_rate_limit(f"{prefix}:{client_id(request)}", settings.road_tile_rate_limit_per_minute):
        record_rate_limit_rejection(prefix, client_id(request), f"{settings.road_tile_rate_limit_per_minute}/min")
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")


def _validate_tile_coords(z: int, x: int, y: int) -> None:
    """路面・POI/交差点密度タイルで共通のズーム/座標範囲チェック
    （T54: POI/交差点密度タイルは既存の路面レイヤーと同じズーム範囲に準拠する）。
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


@router.get("/api/region/road-surface-tiles/{z}/{x}/{y}.pbf")
async def region_road_surface_tile(
    z: int,
    x: int,
    y: int,
    request: Request,
    region_service: RegionService = Depends(get_region_service),
) -> Response:
    _check_tile_rate_limit(request, "road-tile")
    _validate_tile_coords(z, x, y)
    # 同時実行数の上限（_region_tile_semaphoreのコメント参照）は、超過分を待たせて
    # 全件処理する（即座に429で拒否しない）。キャッシュヒットは軽量（実測数ms）なので
    # すぐ解放され、実質的に重い（PostGIS問い合わせを伴う）リクエストだけが待ち行列の
    # 原因になる。
    async with _region_tile_semaphore:
        tile_bytes = await region_service.get_road_surface_tile(z, x, y)
    # ブラウザ側HTTPキャッシュを1時間許可する。路面データはPBF取込時にしか変わらないため、
    # ページ再読み込み・再訪時の同一タイル再取得（＝バーストの主成分）を丸ごと省ける。
    # サーバーからブラウザキャッシュは無効化できないため、取込・範囲拡大の反映遅れを
    # 最大1時間に抑える値にする（サーバー側ディスクキャッシュの一括削除とは独立）。
    return Response(
        content=tile_bytes,
        media_type="application/vnd.mapbox-vector-tile",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/api/region/poi-tiles/{z}/{x}/{y}.pbf")
async def region_poi_tile(
    z: int,
    x: int,
    y: int,
    request: Request,
    region_service: RegionService = Depends(get_region_service),
) -> Response:
    """停止要因POI（信号・横断歩道・一時停止・踏切）・交差点密度レイヤー（改善計画T54）。
    静的道路属性P1で評価にのみ使われていたosm_raw_pois/road_nodesの可視化。
    路面タイルと同じ歯止め・同時実行制御をそのまま流用する。
    """
    _check_tile_rate_limit(request, "poi-tile")
    _validate_tile_coords(z, x, y)
    async with _region_tile_semaphore:
        tile_bytes = await region_service.get_poi_tile(z, x, y)
    return Response(
        content=tile_bytes,
        media_type="application/vnd.mapbox-vector-tile",
        headers={"Cache-Control": "public, max-age=3600"},
    )
