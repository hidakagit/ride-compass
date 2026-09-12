from fastapi import APIRouter, Depends, HTTPException, Request, Response

import logging

from app.api.cache_policy import IMMUTABLE_TILE, JMA_TARGET_TIMES, JMA_TILE_NOT_FOUND
from app.api.dependencies import enforce_rate_limit, get_jma_tile_client
from app.config import settings
from app.domain.jma_tile_specs import source_zoom_for_interpolation
from app.infrastructure.jma_tile_client import (
    EmptyTile,
    JmaTileClient,
    JmaTileNotFoundError,
    is_target_times_path,
)
from pydantic import ValidationError

from app.infrastructure.jma_tile_index import get_index
from app.domain.strict_model import StrictModel
from app.infrastructure.jma_tile_interpolation import (
    crop_and_upscale,
    crop_and_upscale_mvt,
    parse_tile_path,
)

logger = logging.getLogger("ridecompass.routers.jma_tile")

router = APIRouter()

# このプロキシは1つのパスで性質の異なる3種類（内容が確定して以後変化しないタイル本体・
# 同じURLのまま更新される時刻一覧・恒久404）を返すため、`cache_policy.py`の対応表では
# `HANDLER_MANAGED`とし、どのポリシーを使うかだけをここで選ぶ。キャッシュ時間そのものは
# `cache_policy.py`が持つ。


def _cache_control(path: str) -> str:
    policy = JMA_TARGET_TIMES if is_target_times_path(path) else IMMUTABLE_TILE
    return policy.header()


async def _interpolated_tile(jma_tile_client: JmaTileClient, path: str) -> tuple[bytes, str] | None:
    """配信元が実データを持たないズームの要求に対し、親タイルから補間したタイルを返す。

    ラスタ（画像の拡大）・ベクタ（座標の変換）のどちらも対象で、戻り値は内容とContent-Type。
    対象外（実データがあるズーム・タイル以外のパス）はNone。親タイルの取得は
    `JmaTileClient.get()`を通すため、Redisキャッシュ・レート制限・上流への秒間上限が
    そのまま効く。補間した結果は呼び出し元が元のパスのキーでキャッシュへ書き戻す。

    Content-Typeは親タイルのものをそのまま使う（配信元が返す値と揃え、拡張子から
    推測しない）。
    """
    coords = parse_tile_path(path)
    if coords is None:
        return None
    if source_zoom_for_interpolation(coords.element, coords.z) is None:
        return None
    parent = await jma_tile_client.get(coords.parent_path())
    if parent is None or isinstance(parent, EmptyTile):
        # 親が空なら拡大しても空にしかならない。呼び出し元は上流フェッチへ進み、
        # そこでも空・404なら404を返す。
        return None
    parent_content, parent_content_type = parent
    try:
        if coords.ext == "pbf":
            return crop_and_upscale_mvt(parent_content, coords.quadrant), parent_content_type
        return crop_and_upscale(parent_content, coords.quadrant), parent_content_type
    except Exception as exc:  # noqa: BLE001 補間の失敗で地図表示自体を落とさない
        logger.warning(
            "JMAタイルの補間に失敗しました path=%s parent=%s error=%r",
            path,
            coords.parent_path(),
            exc,
        )
        return None


class JmaTileIndexCoverage(StrictModel):
    """インデックスが網羅している地理範囲（プリウォームの対象bbox）。"""

    min_longitude: float
    min_latitude: float
    max_longitude: float
    max_latitude: float


class JmaTileIndexElement(StrictModel):
    """要素（risk系・nowc系・rasrf系）ごとの在否。

    `basetime`はクライアントが「自分が描こうとしている世代と一致するか」を確かめるために
    使う（要素ごとに更新タイミングが異なり、1つの`basetime`では表せない）。
    """

    basetime: str | None = None
    validtime: str | None = None
    member: str = "none"
    # ズーム（文字列キー）→ 中身のあるタイル座標[x, y]の一覧。JSONのオブジェクトキーは
    # 文字列のため、生成側（`jma_tile_prewarm_service._store_index`）で揃えてある。
    zooms: dict[str, list[list[int]]] = {}


class JmaTileIndexResponse(StrictModel):
    """`GET /api/jma-tile-index`の応答。

    `available=False`（インデックス未保存・Redis障害）のとき`coverage`/`elements`は
    いずれもNoneで、クライアントは従来どおり全タイルを取りに行く。
    """

    available: bool
    coverage: JmaTileIndexCoverage | None = None
    elements: dict[str, JmaTileIndexElement] | None = None


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
        return JmaTileIndexResponse(available=False)
    try:
        return JmaTileIndexResponse(available=True, **index)
    except ValidationError as exc:
        # Redisに残っているのは**過去のコードが書いた形**で、鍵にも版が無い。今のモデルと
        # 食い違えば`**index`は例外になる——それを外へ出すと、インデックスが無いときより
        # 悪い（500で地図が出ない）。fail-openの契約どおり「無い」へ倒す。
        logger.warning("JMAタイル在否インデックスの形が現在のモデルと一致しません error=%r", exc)
        return JmaTileIndexResponse(available=False)


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
    if isinstance(cached, EmptyTile):
        # 描くものが無いと確認済みのため、上流へ問い合わせ直さず即座に404を返す
        # （上流が404で返すか空タイルで返すかに関わらず、クライアントから見れば同じ）。
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
        content, content_type = interpolated
        await jma_tile_client.store(path, content, content_type)
        return Response(
            content=content, media_type=content_type, headers={"Cache-Control": _cache_control(path)}
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
