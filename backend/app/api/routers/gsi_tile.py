from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.cache_policy import GSI_TILE_NOT_FOUND
from app.api.dependencies import enforce_rate_limit, get_gsi_tile_client
from app.api.routers._tile_http import validate_tile_coords
from app.config import settings
from app.infrastructure.gsi_tile_client import GsiTileClient, GsiTileNotFound
from app.services.terrain_tile_service import (
    PNG_CONTENT_TYPE,
    TERRAIN_TILE_MAX_ZOOM,
    TERRAIN_TILE_MIN_ZOOM,
    get_terrain_rgb_tile,
)

router = APIRouter()


@router.get("/api/gsi-relief-tile/{path:path}")
async def gsi_relief_tile_proxy(
    path: str, request: Request, gsi_tile_client: GsiTileClient = Depends(get_gsi_tile_client)
) -> Response:
    # 認証なしで叩けるプロキシへの簡易な歯止め（basemap_proxy/jma_tile_proxyと同じ方針）。
    enforce_rate_limit(request, "gsi-relief-tile", settings.gsi_tile_rate_limit_per_minute)
    result = await gsi_tile_client.get(path)
    if isinstance(result, GsiTileNotFound):
        # 整備区域外（珍しくない正常系）だと確認済みのため、502（上流障害）
        # ではなく404を返す。
        raise HTTPException(
            status_code=404,
            detail="指定されたタイルは存在しません",
            headers={"Cache-Control": GSI_TILE_NOT_FOUND.header()},
        )
    if result is None:
        raise HTTPException(status_code=502, detail="地理院タイルの取得に失敗しました")
    content, content_type = result
    return Response(content=content, media_type=content_type)


@router.get("/api/gsi-terrain-tile/{z}/{x}/{y}.png")
async def gsi_terrain_tile(
    z: int,
    x: int,
    y: int,
    request: Request,
    gsi_tile_client: GsiTileClient = Depends(get_gsi_tile_client),
) -> Response:
    """地理院の標高タイルをTerrain-RGBへ移して返す（MapLibreの`raster-dem`が読む形）。

    整備区域外の404は上のプロキシと同じく正常系。MapLibreはそのタイルの陰影を描かないだけで、
    地図全体は成立する。
    """
    enforce_rate_limit(request, "gsi-terrain-tile", settings.gsi_tile_rate_limit_per_minute)
    validate_tile_coords(z, x, y, TERRAIN_TILE_MIN_ZOOM, TERRAIN_TILE_MAX_ZOOM)
    result = await get_terrain_rgb_tile(gsi_tile_client, z, x, y)
    if isinstance(result, GsiTileNotFound):
        raise HTTPException(
            status_code=404,
            detail="指定されたタイルは存在しません",
            headers={"Cache-Control": GSI_TILE_NOT_FOUND.header()},
        )
    if result is None:
        raise HTTPException(status_code=502, detail="地理院タイルの取得に失敗しました")
    return Response(content=result, media_type=PNG_CONTENT_TYPE)
