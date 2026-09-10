from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.admin_auth import require_admin_basic_auth
from app.api.dependencies import enforce_rate_limit, get_basemap_client
from app.config import settings
from app.infrastructure import tile_cache
from app.infrastructure.basemap_client import BasemapClient

router = APIRouter()


@router.get("/api/basemap/{path:path}")
async def basemap_proxy(
    path: str, request: Request, basemap_client: BasemapClient = Depends(get_basemap_client)
) -> Response:
    # 認証なしで叩けるbasemapプロキシへの簡易な歯止め（1クライアントIPあたり1分間の上限）。
    # basemapはOpenFreeMapへの中継を伴うため、無制限に叩かれると外部サービス負荷や
    # ディスク消費に繋がる（詳細はrate_limiter.py）。
    enforce_rate_limit(request, "basemap", settings.basemap_rate_limit_per_minute)
    result = await basemap_client.get(path)
    if result is None:
        raise HTTPException(status_code=502, detail="地図タイルの取得に失敗しました")
    content, content_type = result
    return Response(content=content, media_type=content_type)


@router.post(
    "/api/admin/basemap/refresh",
    dependencies=[Depends(require_admin_basic_auth)],
)
def basemap_refresh() -> dict[str, str]:
    """サーバー側のタイルファイルキャッシュを全消去する（管理画面`/admin`「鮮度」タブから使う）。

    基礎地図タイルと路面ベクタタイルは同じファイルキャッシュを共有しているため、この
    一括クリアで両方とも消える。影響は押した人だけでなく**全利用者**に及ぶ（次のタイル要求で
    作り直されるまで、外部サービスへの実問い合わせやタイル生成が走る）ため、
    axis_admin.py/debug_admin.pyと同じ管理API認可境界（require_admin_basic_auth）の内側に置く。

    各利用者の画面へ反映されるのは、ブラウザが持つ既存タイルの`Cache-Control`が切れた後
    （`api/cache_policy.py`のBASEMAP: 10分）。
    """
    tile_cache.clear_all()
    return {"status": "ok"}
