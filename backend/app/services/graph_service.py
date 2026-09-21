import asyncio
import logging
import time
from collections import Counter

from app.config import settings
from app.domain.attributes import (
    EdgeMaterialArrays,
    ElevationAttribute,
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

# ディスク永続化キャッシュ（tile_persistent_cache.py）読み込み（メモリmiss時の
# pickle復元）の同時実行数上限。残るCPUコストは`LeanEdge`等の再構築を伴うPython
# ループのためGILで直列化され、コア数を増やして効くのはファイルI/O部分だけ——
# タイル読み込みが増えても際限なくスレッドを起動しない歯止めとして持つ
# （他の`asyncio.Semaphore(settings.xxx)`と同じ流儀）。
_tile_cache_load_semaphore = asyncio.Semaphore(settings.tile_cache_load_max_concurrent)


class _CombinedEdgeMaterials:
    """複数タイルの材料を、どのタイルが持っているかだけ覚えて遅延で引くビュー。

    `_build_search_materials_from_tile_cache`が複数z12タイルを1つの`SearchMaterials`へ
    まとめるときに使う。列を連結すると、bbox全体（数十万Edge）ぶんの配列を作り直すことに
    なるため連結しない——探索は各タイルのスコア行列を結合したものを見ており、ここから
    引かれるのは**経路が確定したあとの数百区間の標高属性だけ**である。
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

    def __len__(self) -> int:
        return len(self._owner_by_edge_id)


class GraphService:
    """指定bboxのRoad Graphを`repository`経由で読む。**読むだけで、作らない。**

    道路網は取込・派生バッチが範囲全体ぶん先に作る。取込範囲の外はデータ未整備として
    Noneを返す（その場で作りに行く経路は持たない）。カバレッジは取込の宣言
    （`source_runs.profile`のtarget.bbox）から決まる。
    """

    def __init__(self, repository: RoadGraphRepository):
        self._repository = repository
        # repository内包のSQLAlchemy AsyncSessionは同一セッションへの同時アクセスが
        # 未定義動作/例外を招く（elevation_attribute_service.pyの同種ロックと同じ理由、
        # docs/records/decisions/road-graph-migration.md「AsyncSessionの同時使用クラッシュ」参照）
        # ため、asyncio.gather配下からrepositoryへ到達しうる経路だけをこのロックで
        # 直列化する。現在それに該当するのは_get_or_build_tile_materialsのキャッシュmiss時
        # のDB問い合わせ（_build_search_materials_from_tile_cacheがタイルごとにgatherで
        # 同時に呼ぶ）のみ。get_edges_with_geometryも同じロックを取るが、周回
        # （RoadGraphEngine.evaluate_loopsが距離フィルタ通過候補ぶんをまとめて1回、
        # 候補評価のgather開始前）・区間プレビュー（preview_segment）とも1リクエスト1回の
        # 逐次呼び出しで同時実行は無く、将来の並列化で前提が崩れたときの保険として
        # 残している。
        self._repository_lock = asyncio.Lock()

    async def get_search_materials_for_bbox(
        self, bbox: BoundingBox
    ) -> tuple[SearchMaterials, StaticEdgeScoreMatrix, frozenset[tuple[int, int, int]] | None] | None:
        """探索フェーズ（`RoadGraphEngine.prepare`）向けに、Road Graphのトポロジ＋材料
        （surface/edge_attribute_counts/way_tags/elevation_attributes/designated_edge_ids）と、
        「Edge×公開軸」静的スコア行列（`StaticEdgeScoreMatrix`）をまとめて返す。

        bboxをz12タイル（`ROAD_GRAPH_TILE_ZOOM`）へ分解し、タイル単位でプロセス内
        キャッシュ（`infrastructure/graph_material_cache.py`・
        `infrastructure/tile_score_matrix_cache.py`）を経由する。既にキャッシュ済みの
        タイルだけで足りるリクエストはDBへ一切アクセスせず、軸別スコアの算出
        （Edgeごとの重いPython評価）も行わない。

        タイル集合もあわせて返す。これはこのbboxを覆うz12タイルの集合で、呼び出し側（`RoadGraphEngine`）が
        探索用グラフ・索引のLRU（`infrastructure/search_graph_cache.py`）の鍵に使う。
        """
        # バッチが派生データを書き直してもbackendは再起動しないため、ここで（TTL付きで）
        # DBの世代と突き合わせる。**材料ディスクキャッシュを読むのはこの経路**のため、
        # 置き場所を間違えると定常状態では一度も発火しない。
        await derived_data_revision_service.ensure_caches_match_db(self._repository)

        if not await self._repository.is_covered(bbox):
            logger.warning(
                "取込範囲外のbbox (%.2f,%.2f,%.2f,%.2f)",
                bbox.min_latitude, bbox.min_longitude, bbox.max_latitude, bbox.max_longitude)
            return None

        # accident_count_per_km_year軸材料の年正規化に必要。静的スコア行列の構築に必要な
        # ため、タイル単位キャッシュへ入る前にここで1回だけ解決する。bboxに依存しない
        # グローバル値で既にプロセス内キャッシュ済みのため、追加のDB往復は増えない。
        accident_years_covered = await self.get_accident_years_covered()
        return await self._build_search_materials_from_tile_cache(bbox, accident_years_covered)

    async def _build_search_materials_from_tile_cache(
        self, bbox: BoundingBox, accident_years_covered: int
    ) -> tuple[SearchMaterials, StaticEdgeScoreMatrix, frozenset[tuple[int, int, int]]]:
        # このメソッドはタイルキャッシュ経路専用（_get_or_build_tile_materialsは常に
        # LeanRoadGraphを返す）のため、結合後もLeanRoadGraphで統一する。
        combined_nodes: dict[str, LeanNode] = {}
        combined_edges: dict[str, LeanEdge] = {}
        # 材料の列は連結しない（`_CombinedEdgeMaterials`参照）。owner_by_edge_id
        # （edge_id→タイルindexの軽量な辞書、combined_edgesの結合と同じO(Edge数)の
        # 避けられないコスト）だけをここで構築する。

        tiles = tiles_covering_bbox(bbox, ROAD_GRAPH_TILE_ZOOM)
        materials_stage_started = time.monotonic()
        # タイルごとの読み込み内訳（メモリ/ディスク/DBのいずれを経由したか、ディスク経由
        # ならread_ms）を集約し、リクエスト単位の1行INFOサマリへ載せる
        # （docs/conventions/logging.mdの方針、以後の回帰をログ1行で追えるようにする）。
        materials_read_stats: list[dict[str, object]] = [{} for _ in tiles]
        # 逐次forループだとタイルごとのキャッシュ読み込み（ディスクフォールバック時の
        # pickle読み込みを含む）が積み上がるため、asyncio.gatherで並列化する。
        # tiles/tile_materials_listの順序は一致する（asyncio.gatherは渡した順で結果を
        # 返す）ため、後続のcombine_static_edge_score_matricesの「後勝ち」セマンティクス
        # （列順）は保たれる。DB問い合わせが必要になるケース（キャッシュmiss）は
        # _get_or_build_tile_materials内でself._repository_lockにより直列化される。
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
                self._get_or_build_tile_score_matrix(x, y, materials, accident_years_covered, stats)
                for (x, y), materials, stats in zip(tiles, tile_materials_list, matrix_read_stats)
            )
        )

        graph = LeanRoadGraph(graph_version="tile-cache", nodes=combined_nodes, edges=combined_edges)
        # 複数タイルの静的スコア行列を、上と同じ「後勝ち」セマンティクスで結合する
        # （combine_static_edge_score_matrices参照）。
        score_matrix = combine_static_edge_score_matrices(list(tile_score_matrices))
        # このgraphはbboxを覆う全z12タイルの材料キャッシュをそのまま結合したものなので、
        # タイル集合そのものが「このgraph/score_matrixを再現するために必要十分なキー」に
        # なる（同じタイル集合なら、combined_nodes/combined_edgesの中身は常に同じ）。
        # 呼び出し元（RoadGraphEngine）はこの集合を探索用グラフ・索引のキャッシュキーとして使う
        # （infrastructure/search_graph_cache.py）。
        tile_set = frozenset((ROAD_GRAPH_TILE_ZOOM, x, y) for x, y in tiles)

        # メモリ/ディスク/DBの内訳とディスク経由の読み出し時間合計を1行INFOへまとめる
        # （材料・スコア行列の両方）。
        all_stats = materials_read_stats + matrix_read_stats
        source_counts = Counter(str(stats.get("source", "unknown")) for stats in all_stats)
        total_read_ms = sum(float(stats.get("read_ms", 0.0)) for stats in all_stats)
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
    ) -> SearchMaterials:
        # get_tile_materials自体はメモリLRU miss時にtile_persistent_cache経由で
        # ディスクのpickleファイルを同期的に読む。asyncio.to_threadでスレッドプールへ
        # 逃がすことで、呼び出し元（_build_search_materials_from_tile_cache）が
        # asyncio.gatherで複数タイルを同時に呼んだときディスクI/Oが実際に並列化される。
        # 同時実行数は`settings.tile_cache_load_max_concurrent`のsemaphoreで縛る
        # （残るCPUコストはPythonループのためGILで直列化され、コア数を増やして効くのは
        # I/O部分のみという前提。モジュール冒頭のコメント参照）。`read_stats`は
        # 呼び出し元が渡す出力用の辞書で、渡された場合のみ"source"（memory/disk/db）と
        # ディスク経由時の読み出し時間（read_ms）を書き込む（スコア行列側はDBを読まない
        # ためdbの代わりにcomputedを立てる。_get_or_build_tile_score_matrix参照）。
        async with _tile_cache_load_semaphore:
            cached = await asyncio.to_thread(
                graph_material_cache.get_tile_materials, ROAD_GRAPH_TILE_ZOOM, x, y, read_stats
            )
        if cached is not None:
            return cached

        # ディスクキャッシュもmissした場合のみDBへ問い合わせる。複数タイルが同時に
        # missするとself._repository（単一セッション）へ並行アクセスすることになり
        # 危険なため、get_edges_with_geometryと同じ理由でself._repository_lockにより
        # 直列化する（ロック待ちの間に他のgatherタスクが同じタイルを構築済みの可能性が
        # あるため、ロック取得後に再度キャッシュを確認する）。
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
        materials: SearchMaterials,
        accident_years_covered: int,
        read_stats: dict[str, object] | None = None,
    ) -> StaticEdgeScoreMatrix:
        """タイル単位の「Edge×公開軸」静的スコア行列を、材料キャッシュ
        （`graph_material_cache`）とは別枠のLRU（`tile_score_matrix_cache`）へキャッシュ
        する。軸スタジオでの軸定義編集時（`refresh_axis_definitions`）はこちらだけが
        クリアされ、材料キャッシュは温存される（`tile_score_matrix_cache.py`のdocstring
        参照）。`materials`は`_get_or_build_tile_materials`が返した同じタイルのSearchMaterials
        （キャッシュ済み/新規取得どちらでも、材料自体はここで再取得しない）。

        キャッシュ確認（ディスクフォールバック含む）を`_get_or_build_tile_materials`と
        同じ理由で`asyncio.to_thread`へ逃がす。`read_stats`は呼び出し元が渡す出力用の
        辞書（`_get_or_build_tile_materials`と同じ意味）。同時実行数のsemaphoreも共有する。
        """
        async with _tile_cache_load_semaphore:
            cached = await asyncio.to_thread(
                tile_score_matrix_cache.get, ROAD_GRAPH_TILE_ZOOM, x, y, read_stats
            )
        if cached is not None:
            return cached
        matrix = build_static_edge_score_matrix(materials.graph, materials.materials, accident_years_covered)
        if read_stats is not None:
            # スコア行列は材料から計算するだけでDBを読まない（材料側の"db"と区別する。
            # 混ぜるとサマリの内訳から「prepareが遅いのはDB問い合わせか計算か」を
            # 切り分けられなくなる）。
            read_stats["source"] = "computed"
        tile_score_matrix_cache.set(ROAD_GRAPH_TILE_ZOOM, x, y, matrix)
        return matrix

    async def get_accident_years_covered(self) -> int:
        """事故データの収録年数を返す。

        bboxに依存しないグローバルな値のため、プロセス内メモリへ単一値キャッシュする
        （`graph_material_cache`、タイル単位キャッシュとは別枠）。
        """
        cached = graph_material_cache.get_accident_years_covered()
        if cached is not None:
            return cached
        value = await self._repository.get_accident_years_covered()
        graph_material_cache.set_accident_years_covered(value)
        return value

    async def get_edges_with_geometry(self, edges: list[LeanEdge]) -> dict[str, LeanEdge]:
        """`LeanRoadGraph`として読み込んだ探索用グラフ（geometryプレースホルダのみ）の
        一部Edgeへ、実ジオメトリを後付けで取得する。

        呼び出し元は`RoadGraphEngine.evaluate_loops`（距離フィルタ通過候補ぶんをまとめて
        1回）と`preview_segment`（1経路ぶん1回）で、いずれも逐次呼び出しのため現在は
        同時実行されないが、`self._repository_lock`は保険として取り続ける
        （`__init__`のコメント参照）。
        """
        async with self._repository_lock:
            return await self._repository.get_edges_with_geometry(edges)
