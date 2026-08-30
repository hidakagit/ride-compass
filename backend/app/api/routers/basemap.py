from fastapi import APIRouter, Depends, HTTPException, Request, Response

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


@router.post("/api/basemap/refresh")
def basemap_refresh(request: Request) -> dict[str, str]:
    # 基礎地図タイルと路面ベクタタイル（Step10）は同じファイルキャッシュを共有しているため、
    # この一括クリアで両方とも消える。改善計画T467で検討: axis_admin.py/debug_admin.pyと同じ
    # 管理API認可境界（require_admin_basic_auth）の追加を検討したが、このエンドポイントは
    # 一般ユーザー向け地図UIの「変わらないデータを更新」ボタン（MapView.tsx:
    # refreshBasemapCache）から直接叩かれる——本アプリにはユーザーアカウント自体が無く
    # （画面はRouteSettingsPanel等の一般公開UIのみ、/adminは別surface）、管理者専用の認証を
    # 付けると一般利用者のボタンが401になり機能そのものが壊れる。認証が無いこと自体は
    # 他の公開API（road-surface-tiles等）と同じ位置づけであり、対応は「連打でキャッシュが
    # 常に温まらず外部サービスへの実問い合わせが発生し続ける」リスクへの厳しめのレート制限
    # （既存のbasemap_refresh_rate_limit_per_minute）に留める。
    enforce_rate_limit(request, "basemap-refresh", settings.basemap_refresh_rate_limit_per_minute)
    tile_cache.clear_all()
    return {"status": "ok"}
