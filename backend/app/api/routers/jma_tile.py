from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.dependencies import client_id, get_jma_tile_client
from app.config import settings
from app.infrastructure.debug_log import record_rate_limit_rejection
from app.infrastructure.jma_tile_client import JmaTileClient
from app.infrastructure.rate_limiter import check_rate_limit

router = APIRouter()


@router.get("/api/jma-tile/{path:path}")
async def jma_tile_proxy(
    path: str, request: Request, jma_tile_client: JmaTileClient = Depends(get_jma_tile_client)
) -> Response:
    # 認証なしで叩けるプロキシへの簡易な歯止め（basemap_proxyと同じ方針）。
    if not check_rate_limit(f"jma-tile:{client_id(request)}", settings.jma_tile_rate_limit_per_minute):
        record_rate_limit_rejection(
            "jma-tile", client_id(request), f"{settings.jma_tile_rate_limit_per_minute}/min"
        )
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    result = await jma_tile_client.get(path)
    if result is None:
        raise HTTPException(status_code=502, detail="気象庁データの取得に失敗しました")
    content, content_type = result
    return Response(content=content, media_type=content_type)
