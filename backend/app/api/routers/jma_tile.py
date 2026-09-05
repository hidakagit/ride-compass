from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.dependencies import enforce_rate_limit, get_jma_tile_client
from app.config import settings
from app.infrastructure.jma_tile_client import JmaTileClient, JmaTileNotFoundError

router = APIRouter()


@router.get("/api/jma-tile/{path:path}")
async def jma_tile_proxy(
    path: str, request: Request, jma_tile_client: JmaTileClient = Depends(get_jma_tile_client)
) -> Response:
    # クエリ文字列（例: liden/slmcs系のGeoJSONが要求する?id=liden）はpathへ連結して
    # そのままキャッシュキー・上流URLの一部にする（透過プロキシのため中身を解釈しない）。
    if request.url.query:
        path = f"{path}?{request.url.query}"
    # 改善計画T510: キャッシュヒットならレート制限を一切経由しない（以前は
    # enforce_rate_limitを先に呼んでいたため、既にキャッシュ済みのタイルへの往復パンだけで
    # 429になっていた——429の直接原因）。認証なしで叩けるプロキシへの簡易な歯止め
    # （basemap_proxyと同じ方針）は、実際に外部フェッチが発生するミス時のみ適用する。
    cached = await jma_tile_client.get_cached(path)
    if cached is not None:
        content, content_type = cached
        return Response(content=content, media_type=content_type)
    enforce_rate_limit(request, "jma-tile", settings.jma_tile_rate_limit_per_minute)
    try:
        result = await jma_tile_client.fetch(path)
    except JmaTileNotFoundError:
        # 疎な格子状タイル（降水・浸水想定区域等）では特定のz/x/yに対応するタイルが
        # 存在しないことは珍しくない正常系のため、502（上流障害）ではなく404を返す。
        raise HTTPException(status_code=404, detail="指定されたタイルは存在しません") from None
    if result is None:
        raise HTTPException(status_code=502, detail="気象庁データの取得に失敗しました")
    content, content_type = result
    return Response(content=content, media_type=content_type)
