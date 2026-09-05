from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.dependencies import enforce_rate_limit, get_gsi_relief_tile_client
from app.config import settings
from app.infrastructure.gsi_relief_tile_client import GsiReliefTileClient, ReliefTileNotFound

router = APIRouter()


@router.get("/api/gsi-relief-tile/{path:path}")
async def gsi_relief_tile_proxy(
    path: str, request: Request, gsi_relief_tile_client: GsiReliefTileClient = Depends(get_gsi_relief_tile_client)
) -> Response:
    # 認証なしで叩けるプロキシへの簡易な歯止め（basemap_proxy/jma_tile_proxyと同じ方針）。
    enforce_rate_limit(request, "gsi-relief-tile", settings.gsi_relief_tile_rate_limit_per_minute)
    result = await gsi_relief_tile_client.get(path)
    if isinstance(result, ReliefTileNotFound):
        # 改善計画T605: 整備区域外（珍しくない正常系）だと確認済みのため、502（上流障害）
        # ではなく404を返す。
        raise HTTPException(status_code=404, detail="指定されたタイルは存在しません")
    if result is None:
        raise HTTPException(status_code=502, detail="地理院タイルの取得に失敗しました")
    content, content_type = result
    return Response(content=content, media_type=content_type)
