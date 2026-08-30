from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.dependencies import enforce_rate_limit, get_jma_tile_client
from app.config import settings
from app.infrastructure.jma_tile_client import JmaTileClient

router = APIRouter()


@router.get("/api/jma-tile/{path:path}")
async def jma_tile_proxy(
    path: str, request: Request, jma_tile_client: JmaTileClient = Depends(get_jma_tile_client)
) -> Response:
    # 認証なしで叩けるプロキシへの簡易な歯止め（basemap_proxyと同じ方針）。
    enforce_rate_limit(request, "jma-tile", settings.jma_tile_rate_limit_per_minute)
    result = await jma_tile_client.get(path)
    if result is None:
        raise HTTPException(status_code=502, detail="気象庁データの取得に失敗しました")
    content, content_type = result
    return Response(content=content, media_type=content_type)
