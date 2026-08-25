import asyncio

from fastapi import APIRouter, Depends, Request, Response

from app.api.dependencies import get_accident_service
from app.api.routers._tile_validation import check_tile_rate_limit, validate_tile_coords
from app.config import settings
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
    # 認証なしで叩ける事故タイルへの簡易な歯止め・座標検証（routers/region.pyと共有、
    # _tile_validation.py参照）。
    check_tile_rate_limit(request, "accident-tile", settings.accident_tile_rate_limit_per_minute)
    validate_tile_coords(z, x, y)
    async with _accident_tile_semaphore:
        tile_bytes = await accident_service.get_accident_tile(z, x, y)
    return Response(
        content=tile_bytes,
        media_type="application/vnd.mapbox-vector-tile",
        headers={"Cache-Control": "public, max-age=3600"},
    )
