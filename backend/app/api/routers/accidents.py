import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.dependencies import client_id, get_accident_service
from app.config import settings
from app.domain.region import ROAD_TILE_MAX_ZOOM, ROAD_TILE_MIN_ZOOM
from app.infrastructure.debug_log import record_rate_limit_rejection
from app.infrastructure.rate_limiter import check_rate_limit
from app.services.accident_service import AccidentService

router = APIRouter()

# 同時実行数の上限（settings.accident_tile_max_concurrent）。road-surface-tilesの
# 同時実行制限（routers/region.py）と同じ理由（キャッシュミスのバーストが遠隔DBへ
# 無制限に並ぶのを防ぐ歯止め）で、待たせて全件処理する方式も揃える。
_accident_tile_semaphore = asyncio.Semaphore(settings.accident_tile_max_concurrent)


@router.get("/api/region/accident-tiles/{z}/{x}/{y}.pbf")
async def region_accident_tile(
    z: int,
    x: int,
    y: int,
    request: Request,
    accident_service: AccidentService = Depends(get_accident_service),
) -> Response:
    # 認証なしで叩ける事故タイルへの簡易な歯止め（routers/region.pyと同じ考え方）。
    if not check_rate_limit(f"accident-tile:{client_id(request)}", settings.accident_tile_rate_limit_per_minute):
        record_rate_limit_rejection(
            "accident-tile", client_id(request), f"{settings.accident_tile_rate_limit_per_minute}/min"
        )
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    # 事故タイルも路面タイルと同じXYZズーム範囲（domain/region.py）を使う。
    if z < ROAD_TILE_MIN_ZOOM or z > ROAD_TILE_MAX_ZOOM:
        raise HTTPException(status_code=400, detail="対応していないズームレベルです。")
    tile_index_max = 2**z
    if not (0 <= x < tile_index_max) or not (0 <= y < tile_index_max):
        raise HTTPException(status_code=400, detail="タイル座標が範囲外です。")
    async with _accident_tile_semaphore:
        tile_bytes = await accident_service.get_accident_tile(z, x, y)
    return Response(
        content=tile_bytes,
        media_type="application/vnd.mapbox-vector-tile",
        headers={"Cache-Control": "public, max-age=3600"},
    )
