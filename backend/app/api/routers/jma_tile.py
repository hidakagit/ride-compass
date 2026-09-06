from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.dependencies import enforce_rate_limit, get_jma_tile_client
from app.config import settings
from app.infrastructure.jma_tile_client import (
    JmaTileClient,
    JmaTileNotFoundError,
    TileNotFound,
    is_target_times_path,
)

router = APIRouter()

# タイル本体のURLは`basetime`/`validtime`を含み、内容が確定して以後変化しない。ブラウザは
# MapLibreがタイルを再要求するたび（ズームレベルの跨ぎ・画面外へパンして戻る・`setTiles`に
# よるソース更新）に同じURLを引き直すため、再検証なしでキャッシュから返せることが効く。
# `max-age`は`jma_tile_redis_cache.py`のTTL（20分）と揃える——それを超えて生き残った
# ブラウザキャッシュがbackend側の再取得より古くなることは無い（URLが変われば別エントリに
# なる）が、揃えておくとキャッシュ層ごとの寿命を別々に考えなくて済む。
_TILE_CACHE_CONTROL = "public, max-age=1200, immutable"
# 時刻一覧だけは同じURLのまま内容が更新されるため`immutable`にできない。新しいフレームの
# 発見が遅れないよう、`JmaTileClient`のプロセス内TTLCache（2分）より短くする。
_TARGET_TIMES_CACHE_CONTROL = "public, max-age=60"
# 確認済みの404も`basetime`が確定した過去の一時点に対する結果のため、再問い合わせしても
# 変わらない（`jma_tile_redis_cache.py: TileNotFound`と同じ理由）。疎な格子状タイルでは
# 404が正常系として多数発生するため、これを再要求させない効果はタイル本体と変わらない。
_NOT_FOUND_CACHE_CONTROL = "public, max-age=600"


def _cache_control(path: str) -> str:
    return _TARGET_TIMES_CACHE_CONTROL if is_target_times_path(path) else _TILE_CACHE_CONTROL


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
            headers={"Cache-Control": _NOT_FOUND_CACHE_CONTROL},
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
            headers={"Cache-Control": _NOT_FOUND_CACHE_CONTROL},
        ) from None
    if result is None:
        # 上流障害は一時的なため、キャッシュさせず次のリクエストで取り直させる。
        raise HTTPException(status_code=502, detail="気象庁データの取得に失敗しました")
    content, content_type = result
    return Response(
        content=content, media_type=content_type, headers={"Cache-Control": _cache_control(path)}
    )
