"""road_edgesの実ジオメトリ（`get_edges_with_geometry`）のRedis cache-aside層（改善計画T390）。

`DerivedGraphRepository.get_edges_with_geometry`は、prepareが読み込む探索用グラフ
（geometryプレースホルダのみ、改善計画T218/T12 Stage 0）から、Dijkstraで確定した経路
（1候補あたり数十〜数百Edge）だけへ実ジオメトリを取得し直す用途で、`RoadGraphEngine.
trace_loop`から8方位ぶん（`asyncio.gather`で並列）呼ばれる。本番実測（docs/tasks/T390.md）:
100 edgesのバッチで平均4.69ms/回、1リクエストで最大8回。

`DirectedEdge`（domain/graph.py）はshapelyジオメトリ等を含まないプレーンなPydantic
BaseModel（`geometry: list[list[float]]`）のため、road_graph_tiles/road_edge_attributesと
異なり素直にJSON化できる。

**キャッシュ対象はedge_id単位**（road_graph_tilesのタイル単位マーカーとは粒度が異なる）。
road_edgesはEdgeの分割結果が変わらない限りedge_id（決定論的、domain/graph.py参照）が
安定するため、`DerivedGraphRepository.save_graph`が`way_ids_to_replace`ぶんの新edge_idを
UPSERTした直後に、それら（`new_edge_ids`）のキャッシュエントリを無条件で削除する
（同じedge_idが再split後に異なる形状で再利用される可能性を潰す、precise invalidation）。
再importでroad_edges自体は変わらないためこちらの無効化は不要——road_graph_tile_cache.py側の
split-freshマーカー無効化（`invalidate_split_fresh`）経由で`is_split_up_to_date`が正しく
Falseへ倒れ、そこから`save_graph`が呼ばれて初めて本モジュールの無効化が効く連鎖になる。
"""

import logging

from app.domain.graph import DirectedEdge
from app.infrastructure.debug_log import error_type_label, log_external_call, log_throttled_warning
from app.infrastructure.redis_client import (
    get_redis_client,
    record_redis_failure,
    record_redis_success,
    redis_available,
)

logger = logging.getLogger("app.infrastructure.road_edge_geometry_cache")

_KEY_PREFIX = "road:edge:geom"
# road_graph_tilesの取得済みマーカーと同じ24時間（road_graph_tile_cache.py参照）。
# 書き込み側のprecise invalidation（save_graphのnew_edge_ids削除）が主たる正しさの担保で、
# TTLはその取りこぼし（例外経路での無効化漏れ）に対する自己修復用の安全網。
_TTL_SECONDS = 24 * 60 * 60


def _key(edge_id: str) -> str:
    return f"{_KEY_PREFIX}:{edge_id}"


async def get_cached_edges(edge_ids: list[str]) -> dict[str, DirectedEdge]:
    """Redis側でキャッシュヒットしたedge_idぶんのDirectedEdgeを返す。

    見つからなかったedge_idは戻り値に含まれない（呼び出し元がPostGISへ問い合わせて
    確定する）。Redis自体が疎通不能な場合は空辞書を返す（fail-open）。
    """
    if not edge_ids or not redis_available():
        return {}
    client = get_redis_client()
    keys = [_key(edge_id) for edge_id in edge_ids]
    with log_external_call("cache:edge-geometry-redis", edge_count=len(edge_ids)) as fields:
        try:
            values = await client.mget(keys)
        except Exception as exc:  # noqa: BLE001 Redis障害はPostGISへのfail-open対象
            record_redis_failure()
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
            return {}
        record_redis_success()
        result: dict[str, DirectedEdge] = {}
        for edge_id, value in zip(edge_ids, values):
            if value is None:
                continue
            try:
                result[edge_id] = DirectedEdge.model_validate_json(value)
            except ValueError as exc:
                # スキーマ変更等で旧形式の値が残っていた場合はキャッシュ無視でPostGISへ倒す
                # （road_edgesが正本のため、パース失敗を握りつぶしても実害はない）。
                log_throttled_warning(
                    "cache:edge-geometry-redis", "[cache:edge-geometry-redis] parse failed edge_id=%s error=%r",
                    edge_id, exc,
                )
        fields["result"] = "ok"
        fields["cache"] = "hit" if result else "miss"
        return result


async def cache_edges(edges: dict[str, DirectedEdge]) -> None:
    """PostGISから取得したDirectedEdgeをRedisへ書き戻す。"""
    if not edges or not redis_available():
        return
    client = get_redis_client()
    with log_external_call("cache:edge-geometry-redis", edge_count=len(edges)) as fields:
        try:
            pipe = client.pipeline(transaction=False)
            for edge_id, edge in edges.items():
                pipe.set(_key(edge_id), edge.model_dump_json(), ex=_TTL_SECONDS)
            await pipe.execute()
        except Exception as exc:  # noqa: BLE001 書き込み失敗はPostGIS側の正本に影響しない
            record_redis_failure()
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
        else:
            record_redis_success()
            fields["result"] = "ok"


async def invalidate_edges(edge_ids: list[str]) -> None:
    """`save_graph`がedge_idを再UPSERTした直後に呼ぶ（改善計画T390）。

    同じedge_idが再split後に異なる形状で再利用されるケースに備え、無条件で削除する
    （書き戻しは次回の`get_cached_edges`ミス経由の`cache_edges`に委ねる）。
    """
    if not edge_ids or not redis_available():
        return
    client = get_redis_client()
    with log_external_call("cache:edge-geometry-redis", edge_count=len(edge_ids)) as fields:
        try:
            await client.delete(*(_key(edge_id) for edge_id in edge_ids))
        except Exception as exc:  # noqa: BLE001 無効化失敗はTTL経由で自己修復する
            record_redis_failure()
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
        else:
            record_redis_success()
            fields["result"] = "ok"
