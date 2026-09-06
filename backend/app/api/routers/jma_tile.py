from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.cache_policy import IMMUTABLE_TILE, JMA_TARGET_TIMES, JMA_TILE_NOT_FOUND
from app.api.dependencies import enforce_rate_limit, get_jma_tile_client
from app.config import settings
from app.infrastructure.jma_tile_client import (
    JmaTileClient,
    JmaTileNotFoundError,
    TileNotFound,
    is_target_times_path,
)

router = APIRouter()

# このプロキシは1つのパスで性質の異なる3種類（内容が確定して以後変化しないタイル本体・
# 同じURLのまま更新される時刻一覧・恒久404）を返すため、`cache_policy.py`の対応表では
# `HANDLER_MANAGED`とし、どのポリシーを使うかだけをここで選ぶ。キャッシュ時間そのものは
# `cache_policy.py`が持つ。


def _cache_control(path: str) -> str:
    policy = JMA_TARGET_TIMES if is_target_times_path(path) else IMMUTABLE_TILE
    return policy.header()


@router.get("/api/jma-tile/{path:path}")
async def jma_tile_proxy(
    path: str, request: Request, jma_tile_client: JmaTileClient = Depends(get_jma_tile_client)
) -> Response:
    # クエリ文字列（例: liden/slmcs系のGeoJSONが要求する?id=liden）はpathへ連結して
    # そのままキャッシュキー・上流URLの一部にする（透過プロキシのため中身を解釈しない）。
    if request.url.query:
        path = f"{path}?{request.url.query}"
    # キャッシュヒットならレート制限を一切経由しない。認証なしで叩けるプロキシへの
    # 簡易な歯止め（basemap_proxyと同じ方針）は、実際に外部フェッチが発生する
    # ミス時のみ適用する。
    cached = await jma_tile_client.get_cached(path)
    if isinstance(cached, TileNotFound):
        # 恒久404（疎な格子状タイルでは珍しくない正常系）だと確認済みのため、
        # 上流へ問い合わせ直さず即座に404を返す。
        raise HTTPException(
            status_code=404,
            detail="指定されたタイルは存在しません",
            headers={"Cache-Control": JMA_TILE_NOT_FOUND.header()},
        )
    if cached is not None:
        content, content_type = cached
        return Response(
            content=content, media_type=content_type, headers={"Cache-Control": _cache_control(path)}
        )
    enforce_rate_limit(request, "jma-tile", settings.jma_tile_rate_limit_per_minute)
    try:
        result = await jma_tile_client.fetch(path)
    except JmaTileNotFoundError:
        # 疎な格子状タイル（降水・浸水想定区域等）では特定のz/x/yに対応するタイルが
        # 存在しないことは珍しくない正常系のため、502（上流障害）ではなく404を返す。
        raise HTTPException(
            status_code=404,
            detail="指定されたタイルは存在しません",
            headers={"Cache-Control": JMA_TILE_NOT_FOUND.header()},
        ) from None
    if result is None:
        # 上流障害は一時的なため、キャッシュさせず次のリクエストで取り直させる。
        raise HTTPException(status_code=502, detail="気象庁データの取得に失敗しました")
    content, content_type = result
    return Response(
        content=content, media_type=content_type, headers={"Cache-Control": _cache_control(path)}
    )
