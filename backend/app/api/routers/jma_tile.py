from functools import partial
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.cache_policy import (
    IMMUTABLE_TILE,
    JMA_NOT_YET_DELIVERED,
    JMA_TARGET_TIMES,
    JMA_TILE_NOT_FOUND,
    CachePolicy,
)
from app.api.dependencies import get_jma_tile_client
from app.api.rate_limit import enforce_rate_limit
from app.config import settings
from app.infrastructure.jma_tile_client import (
    EmptyTile,
    JmaTileClient,
    JmaTileNotFoundError,
    is_target_times_path,
)
from app.infrastructure.jma_tile_index import JmaTileIndex, get_index
from app.infrastructure.jma_tile_paths import is_final_absence
from app.domain.strict_model import StrictModel
from app.services.jma_tile_proxy_service import proxied_tile

router = APIRouter()

# このプロキシは1つのパスで性質の異なる4種類（内容が確定して以後変化しないタイル本体・
# 同じURLのまま更新される時刻一覧・恒久404・配信前の地物の404）を返すため、`cache_policy.py`の対応表では
# `HANDLER_MANAGED`とし、どのポリシーを使うかだけをここで選ぶ。キャッシュ時間そのものは
# `cache_policy.py`が持つ。


def _cache_control(path: str) -> str:
    policy = JMA_TARGET_TIMES if is_target_times_path(path) else IMMUTABLE_TILE
    return policy.header()


def _not_found(policy: CachePolicy) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail="指定されたタイルは存在しません",
        headers={"Cache-Control": policy.header()},
    )


class JmaTileIndexAvailable(JmaTileIndex):
    available: Literal[True] = True


class JmaTileIndexUnavailable(StrictModel):
    """インデックス未保存・Redis障害。クライアントは従来どおり全タイルを取りに行く。"""

    available: Literal[False] = False


# `GET /api/jma-tile-index`の応答。範囲と要素は、インデックスが在るときだけ在る。
JmaTileIndexResponse = JmaTileIndexAvailable | JmaTileIndexUnavailable


@router.get("/api/jma-tile-index", response_model=JmaTileIndexResponse)
async def jma_tile_index() -> JmaTileIndexResponse:
    """どのタイルに描くものがあるかの一覧（`infrastructure/jma_tile_index.py`）。

    JMA動的タイルは疎で、平常時はほぼ全てのタイルが空である。クライアントはこれを1回
    受け取り、載っていないタイルは要求しない。`available: false`のときは従来どおり
    全タイルを取りに行く（インデックスが無いことで表示が欠けてはならない）。

    `coverage`の外は在否が不明のため、クライアントはその範囲のタイルを従来どおり取得する。
    """
    index = await get_index()
    if index is None:
        return JmaTileIndexUnavailable()
    return JmaTileIndexAvailable(coverage=index.coverage, elements=index.elements)


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
    try:
        tile = await proxied_tile(
            jma_tile_client,
            path,
            partial(enforce_rate_limit, request, "jma-tile", settings.jma_tile_rate_limit_per_minute),
        )
    except JmaTileNotFoundError:
        # 疎な格子状タイル（降水・浸水想定区域等）では特定のz/x/yに対応するタイルが
        # 存在しないことは珍しくない正常系のため、502（上流障害）ではなく404を返す。
        raise _not_found(JMA_TILE_NOT_FOUND if is_final_absence(path) else JMA_NOT_YET_DELIVERED) from None
    if isinstance(tile, EmptyTile):
        # 描くものが無いと確認済みのため、上流へ問い合わせ直さず即座に404を返す
        # （上流が404で返すか空タイルで返すかに関わらず、クライアントから見れば同じ）。
        raise _not_found(JMA_TILE_NOT_FOUND)
    if tile is None:
        # 上流障害は一時的なため、キャッシュさせず次のリクエストで取り直させる。
        raise HTTPException(status_code=502, detail="気象庁データの取得に失敗しました")
    content, content_type = tile
    return Response(
        content=content, media_type=content_type, headers={"Cache-Control": _cache_control(path)}
    )
