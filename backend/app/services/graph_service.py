import asyncio
import logging
import time
from collections import Counter
from typing import SupportsFloat, cast

from app.config import settings
from app.domain.attributes import (
    EdgeMaterialArrays,
    ElevationAttribute,
    ElevationSource,
    SearchMaterials,
)
from app.domain.evaluation import (
    StaticEdgeScoreMatrix,
    build_static_edge_score_matrix,
    combine_static_edge_score_matrices,
)
from app.domain.graph import LeanEdge, LeanNode, LeanRoadGraph
from app.domain.region import ROAD_GRAPH_TILE_ZOOM, BoundingBox, tile_bounds_lonlat, tiles_covering_bbox
from app.infrastructure import graph_material_cache, tile_score_matrix_cache
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services import derived_data_revision_service

logger = logging.getLogger("ridecompass.graph")

# ディスクキャッシュ読み込みの同時実行数上限。タイル数が増えても際限なくスレッドを
# 起動しないための歯止め。並列化して効くのはファイルI/O部分だけで、残るCPUコストは
# Pythonループのため結局GILで直列化される。
_tile_cache_load_semaphore = asyncio.Semaphore(settings.tile_cache_load_max_concurrent)


class _CombinedEdgeMaterials:
    """複数タイルの材料を、どのタイルが持っているかだけ覚えて遅延で引くビュー。

    **列を連結しない。** 連結するとbbox全体ぶんの配列を作り直すことになる。探索が見るのは
    各タイルのスコア行列を結合したもので、ここから引かれるのは経路が確定したあとの
    標高属性だけである。
    """

    __slots__ = ("_tile_materials", "_owner_by_edge_id")

    def __init__(
        self,
        tile_materials: list[EdgeMaterialArrays],
        owner_by_edge_id: dict[str, int],
    ) -> None:
        self._tile_materials = tile_materials
        self._owner_by_edge_id = owner_by_edge_id

    def elevation_attribute(self, edge_id: str) -> ElevationAttribute | None:
        owner = self._owner_by_edge_id.get(edge_id)
        if owner is None:
            return None
        return self._tile_materials[owner].elevation_attribute(edge_id)


class GraphService:
    """指定bboxのRoad Graphを`repository`経由で読む。**読むだけで、作らない。**

    道路網は取込・派生バッチが範囲全体ぶん先に作る。取込範囲の外はデータ未整備として
    Noneを返す（その場で作りに行く経路は持たない）。カバレッジは取込の宣言
    （`source_runs.profile`のtarget.bbox）から決まる。
    """

    def __init__(self, repository: RoadGraphRepository):
        self._repository = repository
        # repositoryが内包するAsyncSessionは同時に使えない（未定義動作・例外になる）。
        # `asyncio.gather`配下からrepositoryへ到達しうる経路は、このロックで直列化する。
        self._repository_lock = asyncio.Lock()

    async def get_search_materials_for_bbox(
        self, bbox: BoundingBox
    ) -> tuple[SearchMaterials[ElevationSource], StaticEdgeScoreMatrix, frozenset[tuple[int, int, int]]] | None:
        """探索フェーズ向けに、グラフのトポロジ＋材料と静的スコア行列をまとめて返す。

        bboxをタイルへ分解し、タイル単位でプロセス内キャッシュを経由する。既にキャッシュ
        済みのタイルだけで足りるリクエストは、DBへ一切アクセスせず軸別スコアも計算しない。

        あわせて返すタイル集合は、この結果を再現するために必要十分な鍵になる（同じタイル
        集合なら中身は常に同じ）。呼び出し側は探索用グラフ・索引のキャッシュキーに使う。
        """
        # **材料ディスクキャッシュを読むのはこの経路**のため、世代の突き合わせもここへ置く。
        # 他所へ移すと、定常状態では一度も発火しない。
        await derived_data_revision_service.ensure_caches_match_db(self._repository)

        if not await self._repository.is_covered(bbox):
            logger.warning(
                "取込範囲外のbbox (%.2f,%.2f,%.2f,%.2f)",
                bbox.min_latitude, bbox.min_longitude, bbox.max_latitude, bbox.max_longitude)
            return None

        # 事故材料の年正規化に要る。タイル単位キャッシュへ入る前にここで1回だけ解決する。
        accident_years_covered = await self.get_accident_years_covered()
        return await self._build_search_materials_from_tile_cache(bbox, accident_years_covered)

    async def _build_search_materials_from_tile_cache(
        self, bbox: BoundingBox, accident_years_covered: int
    ) -> tuple[SearchMaterials[ElevationSource], StaticEdgeScoreMatrix, frozenset[tuple[int, int, int]]]:
        combined_nodes: dict[str, LeanNode] = {}
        combined_edges: dict[str, LeanEdge] = {}

        tiles = tiles_covering_bbox(bbox, ROAD_GRAPH_TILE_ZOOM)
        materials_stage_started = time.monotonic()
        # タイルごとの読み込み内訳を集約し、リクエスト単位の1行INFOサマリへ載せる。
        materials_read_stats: list[dict[str, object]] = [{} for _ in tiles]
        # 並列化しないとタイルごとのディスク読み込みが積み上がる。`asyncio.gather`は渡した
        # 順で結果を返すため、後続のスコア行列結合の「後勝ち」は順序ごと保たれる。
        tile_materials_list = await asyncio.gather(
            *(
                self._get_or_build_tile_materials(x, y, accident_years_covered, stats)
                for (x, y), stats in zip(tiles, materials_read_stats)
            )
        )
        owner_by_edge_id: dict[str, int] = {}
        for i, tile in enumerate(tile_materials_list):
            combined_nodes.update(tile.graph.nodes)
            combined_edges.update(tile.graph.edges)
            for edge_id in tile.graph.edges:
                owner_by_edge_id[edge_id] = i  # 後勝ち: dict.updateと同じ「後のタイルが勝つ」規約

        matrix_read_stats: list[dict[str, object]] = [{} for _ in tiles]
        tile_score_matrices = await asyncio.gather(
            *(
                self._get_or_build_tile_score_matrix(x, y, materials, stats)
                for (x, y), materials, stats in zip(tiles, tile_materials_list, matrix_read_stats)
            )
        )

        graph = LeanRoadGraph(graph_version="tile-cache", nodes=combined_nodes, edges=combined_edges)
        # 上と同じ「後勝ち」で結合する。
        score_matrix = combine_static_edge_score_matrices(list(tile_score_matrices))
        tile_set = frozenset((ROAD_GRAPH_TILE_ZOOM, x, y) for x, y in tiles)

        all_stats = materials_read_stats + matrix_read_stats
        source_counts = Counter(str(stats.get("source", "unknown")) for stats in all_stats)
        total_read_ms = sum(float(cast(SupportsFloat, stats.get("read_ms", 0.0))) for stats in all_stats)
        materials_ms = round((time.monotonic() - materials_stage_started) * 1000)
        logger.info(
            "_build_search_materials_from_tile_cache tiles=%d memory=%d disk=%d db=%d computed=%d "
            "disk_read_ms=%.1f materials_ms=%d",
            len(tiles), source_counts.get("memory", 0), source_counts.get("disk", 0),
            source_counts.get("db", 0), source_counts.get("computed", 0), total_read_ms, materials_ms,
        )

        return (
            SearchMaterials(
                graph=graph,
                materials=_CombinedEdgeMaterials(
                    tile_materials=[tile.materials for tile in tile_materials_list],
                    owner_by_edge_id=owner_by_edge_id,
                ),
            ),
            score_matrix,
            tile_set,
        )

    async def _get_or_build_tile_materials(
        self, x: int, y: int, accident_years_covered: int, read_stats: dict[str, object] | None = None
    ) -> SearchMaterials[EdgeMaterialArrays]:
        # ディスク読み込みは同期I/Oのため、スレッドへ逃がさないと並列に呼んでも順番に待つ。
        # `read_stats`は呼び出し元が渡す出力用の辞書で、渡されたときだけ"source"
        # （memory/disk/db）とディスク経由時のread_msを書き込む。
        async with _tile_cache_load_semaphore:
            cached = await asyncio.to_thread(
                graph_material_cache.get_tile_materials, ROAD_GRAPH_TILE_ZOOM, x, y, read_stats
            )
        if cached is not None:
            return cached

        # ディスクもmissした場合だけDBへ行く。ロック待ちの間に他のタスクが同じタイルを
        # 構築し終えている可能性があるため、ロック取得後にもう一度キャッシュを見る。
        async with self._repository_lock:
            cached = graph_material_cache.get_tile_materials(ROAD_GRAPH_TILE_ZOOM, x, y, read_stats)
            if cached is not None:
                return cached

            tile_bbox = tile_bounds_lonlat(ROAD_GRAPH_TILE_ZOOM, x, y)
            graph = await self._repository.get_graph_topology_in_bbox(tile_bbox)
            if graph is None:
                # このタイルに道路が1本も無い（取得失敗ではない）。空の結果もキャッシュする
                # （毎回このタイルを無駄に再問い合わせしないため）。
                graph = LeanRoadGraph(graph_version="tile-cache-empty", nodes={}, edges={})

            # 材料はDB側で導出させ、列ごとの配列として受け取る（`MaterialSpec.value_sql`）。
            # 区間ごとのPythonオブジェクトを作らないため、構築もディスクからの復元も
            # Edge数に比例しない。
            materials = SearchMaterials(
                graph=graph,
                materials=await self._repository.get_edge_material_arrays(
                    list(graph.edges.values()), accident_years_covered
                ),
            )
            if read_stats is not None:
                read_stats["source"] = "db"
            graph_material_cache.set_tile_materials(ROAD_GRAPH_TILE_ZOOM, x, y, materials)
            return materials

    async def _get_or_build_tile_score_matrix(
        self,
        x: int,
        y: int,
        materials: SearchMaterials[EdgeMaterialArrays],
        read_stats: dict[str, object] | None = None,
    ) -> StaticEdgeScoreMatrix:
        """タイル単位の「Edge×公開軸」静的スコア行列。材料とは別枠のキャッシュを使う。

        `materials`は同じタイルについて既に取れているものを渡すこと。ここでは取り直さない。
        """
        async with _tile_cache_load_semaphore:
            cached = await asyncio.to_thread(
                tile_score_matrix_cache.get, ROAD_GRAPH_TILE_ZOOM, x, y, read_stats
            )
        if cached is not None:
            return cached
        matrix = build_static_edge_score_matrix(materials.materials)
        if read_stats is not None:
            # 材料側の"db"と区別する。混ぜると、サマリの内訳から「遅いのはDB問い合わせか
            # 計算か」を切り分けられなくなる。
            read_stats["source"] = "computed"
        tile_score_matrix_cache.set(ROAD_GRAPH_TILE_ZOOM, x, y, matrix)
        return matrix

    async def get_accident_years_covered(self) -> int:
        """事故データの収録年数。bboxに依存しないため、プロセス内へ単一値でキャッシュする。"""
        cached = graph_material_cache.get_accident_years_covered()
        if cached is not None:
            return cached
        value = await self._repository.get_accident_years_covered()
        graph_material_cache.set_accident_years_covered(value)
        return value

    async def get_edges_with_geometry(self, edges: list[LeanEdge]) -> dict[str, LeanEdge]:
        """探索用グラフはgeometryをプレースホルダで持つ。その一部Edgeへ実体を後付けする。"""
        async with self._repository_lock:
            return await self._repository.get_edges_with_geometry(edges)
