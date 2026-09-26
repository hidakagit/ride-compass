import asyncio
import logging
import time

from app.config import settings
from app.domain.errors import SearchAreaTooLargeError
from app.domain.evaluation import StaticEdgeScoreMatrix, build_static_edge_score_matrix
from app.domain.graph import LeanEdge
from app.domain.region import BoundingBox, tiles_covering_bbox
from app.domain.road_network import RoadSlice, material_arrays_of, slice_network
from app.infrastructure import container_memory, road_network_store
from app.infrastructure.road_graph_repository import RoadGraphRepository

logger = logging.getLogger("ridecompass.graph")

#: 生成以外（地図タイルの配信・プロセスの常駐分）のために取り置くメモリ。
_RESERVED_BYTES = 2 * 1024**3
#: 1件の生成が、切り出した有向の区間1本あたりに使うメモリ（探索用グラフ・コスト配列・ターン構造・候補の評価の合計）。
_BYTES_PER_EDGE = 1050
#: 近い探索範囲をまとめる粒度。bboxを覆うこのズームのタイル集合が同じなら、学習した迂回率
#: （`detour_ratio_cache`）を共有する。z12は東京付近で1辺約8km。
_RANGE_KEY_ZOOM = 12


def _max_search_edges() -> int | None:
    """1回の生成が切り出してよい有向の区間の上限。コンテナのメモリ上限が無ければNone（断らない）。

    同時に動く生成（`generate_max_concurrent`）がそろって上限いっぱいの範囲を組んでも、取り置きを残して
    メモリ上限に収まる本数にする。上限を超えるとプロセスごと落ち、全員の生成と地図が止まる。
    """
    limit = container_memory.memory_limit_bytes()
    if limit is None:
        return None
    return max(0, (limit - _RESERVED_BYTES) // settings.generate_max_concurrent // _BYTES_PER_EDGE)


class GraphService:
    """探索範囲の道路網を、取込範囲全体の配列（`infrastructure/road_network_store.py`）から
    切り出す。**読むだけで、作らない。**

    取込範囲の外はデータ未整備としてNoneを返す。カバレッジは取込の宣言
    （`source_runs.profile`のtarget.bbox）から決まる。
    """

    def __init__(self, repository: RoadGraphRepository):
        self._repository = repository

    async def get_search_slice(
        self, bbox: BoundingBox
    ) -> tuple[RoadSlice, StaticEdgeScoreMatrix, frozenset[tuple[int, int, int]]] | None:
        """探索範囲の区間と、その静的スコア行列（行は切り出した区間の順）を返す。

        切り出すのはbboxそのもの。あわせて返すbboxを覆うz12タイルの集合は、近い範囲をまとめて
        指す鍵として使う（学習した迂回率の鍵）。
        """
        if not await self._repository.is_covered(bbox):
            logger.warning(
                "取込範囲外のbbox (%.2f,%.2f,%.2f,%.2f)",
                bbox.min_latitude, bbox.min_longitude, bbox.max_latitude, bbox.max_longitude)
            return None

        started = time.monotonic()
        tiles = tiles_covering_bbox(bbox, _RANGE_KEY_ZOOM)
        network = await asyncio.to_thread(road_network_store.current)
        road = slice_network(network, bbox.min_longitude, bbox.min_latitude, bbox.max_longitude, bbox.max_latitude)
        limit = _max_search_edges()
        if limit is not None and road.edge_count > limit:
            logger.warning(
                "探索範囲の区間が上限を超えたため使わない bbox=(%.2f,%.2f,%.2f,%.2f) tiles=%d edges=%d limit=%d",
                bbox.min_latitude, bbox.min_longitude, bbox.max_latitude, bbox.max_longitude,
                len(tiles), road.edge_count, limit)
            raise SearchAreaTooLargeError(road.edge_count, limit)
        slice_ms = round((time.monotonic() - started) * 1000)
        matrix = await asyncio.to_thread(build_static_edge_score_matrix, material_arrays_of(road))
        logger.info(
            "get_search_slice tiles=%d edges=%d nodes=%d slice_ms=%d total_ms=%d",
            len(tiles), road.edge_count, road.node_count, slice_ms, round((time.monotonic() - started) * 1000),
        )
        tile_set = frozenset((_RANGE_KEY_ZOOM, x, y) for x, y in tiles)
        return road, matrix, tile_set

    async def get_edges_with_geometry(self, edges: list[LeanEdge]) -> dict[str, LeanEdge]:
        """探索用グラフは形を持たない。確定した経路の区間へ実体を後付けする。"""
        return await self._repository.get_edges_with_geometry(edges)
