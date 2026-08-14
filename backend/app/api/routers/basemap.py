from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.dependencies import client_id, get_basemap_client
from app.config import settings
from app.infrastructure import tile_cache
from app.infrastructure.basemap_client import BasemapClient
from app.infrastructure.debug_log import record_rate_limit_rejection
from app.infrastructure.rate_limiter import check_rate_limit

router = APIRouter()


@router.get("/api/basemap/{path:path}")
async def basemap_proxy(
    path: str, request: Request, basemap_client: BasemapClient = Depends(get_basemap_client)
) -> Response:
    # 認証なしで叩けるbasemapプロキシへの簡易な歯止め（1クライアントIPあたり1分間の上限）。
    # basemapはOpenFreeMapへの中継を伴うため、無制限に叩かれると外部サービス負荷や
    # ディスク消費に繋がる（詳細はrate_limiter.py）。
    if not check_rate_limit(f"basemap:{client_id(request)}", settings.basemap_rate_limit_per_minute):
        record_rate_limit_rejection(
            "basemap", client_id(request), f"{settings.basemap_rate_limit_per_minute}/min"
        )
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    result = await basemap_client.get(path)
    if result is None:
        raise HTTPException(status_code=502, detail="地図タイルの取得に失敗しました")
    content, content_type = result
    return Response(content=content, media_type=content_type)


@router.post("/api/basemap/refresh")
def basemap_refresh(request: Request) -> dict[str, str]:
    # 基礎地図タイルと路面ベクタタイル（Step10）は同じファイルキャッシュを共有しているため、
    # この一括クリアで両方とも消える。認証が無いため、連打でキャッシュが常に温まらず
    # 外部サービス（Overpass/OpenFreeMap）への実問い合わせが発生し続けることを防ぐため
    # 他のエンドポイントよりも厳しいレート制限をかける（config.py参照）。
    if not check_rate_limit(f"basemap-refresh:{client_id(request)}", settings.basemap_refresh_rate_limit_per_minute):
        record_rate_limit_rejection(
            "basemap-refresh", client_id(request), f"{settings.basemap_refresh_rate_limit_per_minute}/min"
        )
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。しばらく待ってから再試行してください。")
    tile_cache.clear_all()
    return {"status": "ok"}
