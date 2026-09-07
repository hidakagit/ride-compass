from fastapi import APIRouter, Depends, HTTPException, Request, Response

import logging

from app.api.cache_policy import IMMUTABLE_TILE, JMA_TARGET_TIMES, JMA_TILE_NOT_FOUND
from app.api.dependencies import enforce_rate_limit, get_jma_tile_client
from app.config import settings
from app.domain.jma_tile_specs import source_zoom_for_interpolation
from app.infrastructure.jma_tile_client import (
    JmaTileClient,
    JmaTileNotFoundError,
    TileNotFound,
    is_target_times_path,
)
from app.infrastructure.jma_tile_index import get_index
from app.infrastructure.jma_tile_interpolation import crop_and_upscale, parse_tile_path

logger = logging.getLogger("app.api.routers.jma_tile")

router = APIRouter()

# このプロキシは1つのパスで性質の異なる3種類（内容が確定して以後変化しないタイル本体・
# 同じURLのまま更新される時刻一覧・恒久404）を返すため、`cache_policy.py`の対応表では
# `HANDLER_MANAGED`とし、どのポリシーを使うかだけをここで選ぶ。キャッシュ時間そのものは
# `cache_policy.py`が持つ。


def _cache_control(path: str) -> str:
    policy = JMA_TARGET_TIMES if is_target_times_path(path) else IMMUTABLE_TILE
    return policy.header()


async def _interpolated_tile(jma_tile_client: JmaTileClient, path: str) -> bytes | None:
    """配信元が実データを持たないズームの要求に対し、親タイルから補間した画像を返す。

    対象外（実データがあるズーム・タイル以外のパス・ベクタタイル）はNone。親タイルの取得は
    `JmaTileClient.get()`を通すため、Redisキャッシュ・レート制限・上流への秒間上限が
    そのまま効く。補間した結果は呼び出し元が元のパスのキーでキャッシュへ書き戻す。
    """
    coords = parse_tile_path(path)
    if coords is None or coords.ext != "png":
        # ベクタタイル（洪水キキクル）はMVTのジオメトリ再エンコードが必要なため対象外
        # （docs/tasks/T641.md参照）。
        return None
    if source_zoom_for_interpolation(coords.element, coords.z) is None:
        return None
    parent = await jma_tile_client.get(coords.parent_path())
    if parent is None:
        return None
    parent_content, _parent_content_type = parent
    try:
        return crop_and_upscale(parent_content, coords.quadrant)
    except Exception as exc:  # noqa: BLE001 補間の失敗で地図表示自体を落とさない
        logger.warning(
            "JMAタイルの補間に失敗しました path=%s parent=%s error=%r",
            path,
            coords.parent_path(),
            exc,
        )
        return None


@router.get("/api/jma-tile-index")
async def jma_tile_index() -> dict:
    """どのタイルに描くものがあるかの一覧（`infrastructure/jma_tile_index.py`）。

    JMA動的タイルは疎で、平常時はほぼ全てのタイルが空である。クライアントはこれを1回
    受け取り、載っていないタイルは要求しない。`available: false`のときは従来どおり
    全タイルを取りに行く（インデックスが無いことで表示が欠けてはならない）。

    `coverage`の外は在否が不明のため、クライアントはその範囲のタイルを従来どおり取得する。
    """
    index = await get_index()
    if index is None:
        return {"available": False}
    return {"available": True, **index}


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
    # 配信元が実データを持たないズームは、上流へ問い合わせても空タイルしか返らない。
    # 親タイルから補間したものを、元のパスのキーでキャッシュへ書き戻して返す。
    interpolated = await _interpolated_tile(jma_tile_client, path)
    if interpolated is not None:
        await jma_tile_client.store(path, interpolated, "image/png")
        return Response(
            content=interpolated, media_type="image/png", headers={"Cache-Control": _cache_control(path)}
        )
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
