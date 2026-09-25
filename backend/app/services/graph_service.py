import asyncio
import logging
import time

from app.domain.errors import SearchAreaTooLargeError
from app.domain.evaluation import StaticEdgeScoreMatrix, build_static_edge_score_matrix
from app.domain.graph import LeanEdge
from app.domain.region import ROAD_GRAPH_TILE_ZOOM, BoundingBox, tile_bounds_lonlat, tiles_covering_bbox
from app.domain.road_network import RoadSlice, material_arrays_of, slice_network
from app.infrastructure import road_network_store
from app.infrastructure.road_graph_repository import RoadGraphRepository

logger = logging.getLogger("ridecompass.graph")

# 1回の生成が切り出してよい有向の区間の上限。探索素材と探索用グラフは区間の数に比例してメモリを
# 使い、backendのコンテナの上限（6GB）を超えるとプロセスごと落ちて全員の生成と地図が止まる。
# 都心の40km周回（有向約100万本）が収まり、60km（約200万本）が断られる値にしてある。
MAX_SEARCH_EDGES = 1_200_000


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

        切り出すのはbboxを覆うz12タイルの外接矩形。あわせて返すタイル集合は、同じ範囲を
        指す鍵として使える（学習した迂回率の鍵）。
        """
        if not await self._repository.is_covered(bbox):
            logger.warning(
                "取込範囲外のbbox (%.2f,%.2f,%.2f,%.2f)",
                bbox.min_latitude, bbox.min_longitude, bbox.max_latitude, bbox.max_longitude)
            return None

        started = time.monotonic()
        tiles = tiles_covering_bbox(bbox, ROAD_GRAPH_TILE_ZOOM)
        envelope = _tiles_envelope(tiles)
        network = await asyncio.to_thread(road_network_store.current)
        road = slice_network(
            network, envelope.min_longitude, envelope.min_latitude, envelope.max_longitude, envelope.max_latitude)
        if road.edge_count > MAX_SEARCH_EDGES:
            logger.warning(
                "探索範囲の区間が上限を超えたため使わない bbox=(%.2f,%.2f,%.2f,%.2f) tiles=%d edges=%d limit=%d",
                bbox.min_latitude, bbox.min_longitude, bbox.max_latitude, bbox.max_longitude,
                len(tiles), road.edge_count, MAX_SEARCH_EDGES)
            raise SearchAreaTooLargeError(road.edge_count, MAX_SEARCH_EDGES)
        slice_ms = round((time.monotonic() - started) * 1000)
        matrix = await asyncio.to_thread(build_static_edge_score_matrix, material_arrays_of(road))
        logger.info(
            "get_search_slice tiles=%d edges=%d nodes=%d slice_ms=%d total_ms=%d",
            len(tiles), road.edge_count, road.node_count, slice_ms, round((time.monotonic() - started) * 1000),
        )
        tile_set = frozenset((ROAD_GRAPH_TILE_ZOOM, x, y) for x, y in tiles)
        return road, matrix, tile_set

    async def get_edges_with_geometry(self, edges: list[LeanEdge]) -> dict[str, LeanEdge]:
        """探索用グラフは形を持たない。確定した経路の区間へ実体を後付けする。"""
        return await self._repository.get_edges_with_geometry(edges)


def _tiles_envelope(tiles: list[tuple[int, int]]) -> BoundingBox:
    bounds = [tile_bounds_lonlat(ROAD_GRAPH_TILE_ZOOM, x, y) for x, y in tiles]
    return BoundingBox(
        min_latitude=min(b.min_latitude for b in bounds),
        min_longitude=min(b.min_longitude for b in bounds),
        max_latitude=max(b.max_latitude for b in bounds),
        max_longitude=max(b.max_longitude for b in bounds),
    )
