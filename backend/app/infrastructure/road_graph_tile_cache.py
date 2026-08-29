"""road_graph_tilesタイル取得済みマーカーのRedis cache-aside層（改善計画T387）。

`road_graph_tiles`（PostGIS）は「このタイルはOverpass/PBF取込を完了した」という完了
マーカーであり、地理データそのものではない（road_graph_models.py: RoadGraphTileRowの
docstring参照）。GraphService._ensure_tiles_cachedがルート生成のリクエストごとに参照する
ホットパスのため、PostGIS往復をRedisで肩代わりしレイテンシを削減する狙い
（実測結果はdocs/tasks/T387.md参照）。

**cache-aside、PostGISを正本のまま維持する（置き換えない）**: このマーカーの再構築コストは
本来Overpassへの再問い合わせだが、改善計画T22でOverpassフォールバック自体を撤去済みのため、
このマーカーを失うと該当bboxのルート生成が「データ未整備」として拒否されてしまう
（再取得の自動復旧手段が無い）。Redisは永続化（RDB/AOF）設定を持たない前提のキャッシュ層
のため、ここを正本にすると再起動・エビクションのたびに広範囲のルート生成が壊れる重大な
後退になる。そのため書き込みは常にPostGIS（`RawOsmRepository.get_cached_tiles`が読む
`road_graph_tiles`、書き込みは`app/batch/import_pbf.py`の`_mark_tiles`）が正本を担い、
Redisは読み取りを高速化する派生キャッシュとしてのみ使う。読み取り時にRedisへキーが
無ければPostGISへフォールバックし、見つかった分をRedisへ書き戻す。Redis自体が疎通不能でも
PostGIS単独の従来動作へfail-openする（呼び出し元はRedis障害を意識しなくてよい）。
"""

import logging

from app.infrastructure.debug_log import log_throttled_warning
from app.infrastructure.redis_client import (
    get_redis_client,
    record_redis_failure,
    record_redis_success,
    redis_available,
)

logger = logging.getLogger("app.infrastructure.road_graph_tile_cache")

_KEY_PREFIX = "road:tile:fetched"
# 完了マーカーは頻繁に変わるデータではない（一度立てば実質恒久）が、TTL無し（永続）に
# するとPostGIS側の実態と離れて古いキーが残り続けるリスクがある。長めのTTLで定期的に
# PostGISへ問い合わせ直させ、cache-asideの自己修復サイクルを保つ。
_TTL_SECONDS = 24 * 60 * 60


def _key(zoom: int, x: int, y: int) -> str:
    return f"{_KEY_PREFIX}:{zoom}:{x}:{y}"


async def get_cached_subset(zoom: int, tiles: list[tuple[int, int]]) -> set[tuple[int, int]]:
    """Redis側で「取得済み」と判定できたタイルの集合を返す。

    Redisにキーが無いことは「未取得」を意味せず「cold cache」でもありうるため、戻り値に
    含まれないタイルは呼び出し元がPostGISへ問い合わせて確定させる必要がある
    （このモジュールは「分かる分だけ即答する」役割に徹する）。Redis自体が疎通不能な
    場合は空集合を返す（fail-open、全タイルの判定をPostGISへ委ねる）。
    """
    if not tiles or not redis_available():
        return set()
    client = get_redis_client()
    keys = [_key(zoom, x, y) for x, y in tiles]
    try:
        values = await client.mget(keys)
    except Exception as exc:  # noqa: BLE001 Redis障害はPostGISへのfail-open対象
        record_redis_failure()
        log_throttled_warning("cache:road-tile-redis", "[cache:road-tile-redis] read failed error=%r", exc)
        return set()
    record_redis_success()
    return {tile for tile, value in zip(tiles, values) if value is not None}


async def mark_fetched(zoom: int, tiles: list[tuple[int, int]]) -> None:
    """PostGISで取得済みと確定したタイルをRedisへ書き戻す。

    次回以降の読み取りを高速化するためのキャッシュ最適化であり、書き込み失敗は
    呼び出し元の処理結果（PBF取込・ルート生成のいずれも）に影響させない。
    """
    if not tiles or not redis_available():
        return
    client = get_redis_client()
    try:
        pipe = client.pipeline(transaction=False)
        for x, y in tiles:
            pipe.set(_key(zoom, x, y), "1", ex=_TTL_SECONDS)
        await pipe.execute()
    except Exception as exc:  # noqa: BLE001 書き込み失敗はPostGIS側の正本に影響しない
        record_redis_failure()
        log_throttled_warning("cache:road-tile-redis", "[cache:road-tile-redis] write failed error=%r", exc)
    else:
        record_redis_success()
