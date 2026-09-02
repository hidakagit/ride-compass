import asyncio
import logging
import time
from collections import Counter
from dataclasses import replace

from app.config import settings
from app.domain.attributes import EdgeMaterialBundle, EdgeMaterialTable, SearchMaterials, surface_by_edge_id
from app.domain.evaluation import StaticEdgeScoreMatrix, build_static_edge_score_matrix, combine_static_edge_score_matrices
from app.domain.graph import DirectedEdge, LeanEdge, LeanNode, LeanRoadGraph, RoadGraph, RoadGraphLike, build_road_graph
from app.domain.region import ROAD_GRAPH_TILE_ZOOM, BoundingBox, tile_bounds_lonlat, tiles_covering_bbox
from app.infrastructure import graph_material_cache, road_graph_tile_cache, tile_score_matrix_cache
from app.infrastructure.database import get_session_factory
from app.infrastructure.road_graph_repository import RoadGraphRepository

logger = logging.getLogger("ridecompass.graph")

# 改善計画T546: ディスク永続化キャッシュ（tile_persistent_cache.py）読み込み（メモリmiss時の
# pickle復元）の同時実行数上限。案C1で残るCPUコストは`LeanEdge`等の再構築を伴うPython
# ループのためGILで直列化され（本番実測、docs/tasks/T546.md「背景」の「2スレッド同時
# loads」参照）、コア数を増やして効くのはファイルI/O部分だけ——タイル読み込みが増えても
# 際限なくスレッドを起動しない歯止めとして持つ（他の`asyncio.Semaphore(settings.xxx)`と
# 同じ流儀、`region_service.py: _graph_build_semaphore`等参照）。
_tile_cache_load_semaphore = asyncio.Semaphore(settings.tile_cache_load_max_concurrent)


class _CombinedEdgeMaterials:
    """複数タイルの材料（`_get_or_build_tile_materials`が返す`SearchMaterials.materials`、
    `EdgeMaterialTable`または`dict[str, EdgeMaterialBundle]`）を、Edge単位で即座に復元
    せず遅延結合するビュー（改善計画T546）。

    `_build_search_materials_from_tile_cache`が複数z12タイルの材料を1つの
    `SearchMaterials`へ結合する際、以前は`dict.update`でbbox全体（数十万Edge）ぶんの
    `EdgeMaterialBundle`を即座に復元・結合していた。これは`EdgeMaterialTable`導入の
    目的（Edge単位のPythonオブジェクト再構築を経路上のEdge[数百本]だけに限定し、
    ディスク復元コストと切り離す）を結合時点で台無しにしてしまうため、本クラスは
    `owner_by_edge_id`（edge_id→タイルindex、`combined_edges`の結合と同じ避けられない
    O(Edge数)コストだが中身は軽量なint）だけを持ち、実際のEdgeMaterialBundle復元は
    `get(edge_id)`が呼ばれた時点で該当タイルへ1回だけ委譲する。
    """

    __slots__ = ("_tile_materials", "_owner_by_edge_id")

    def __init__(
        self,
        tile_materials: list["dict[str, EdgeMaterialBundle] | EdgeMaterialTable"],
        owner_by_edge_id: dict[str, int],
    ) -> None:
        self._tile_materials = tile_materials
        self._owner_by_edge_id = owner_by_edge_id

    def get(self, edge_id: str) -> EdgeMaterialBundle | None:
        owner = self._owner_by_edge_id.get(edge_id)
        if owner is None:
            return None
        return self._tile_materials[owner].get(edge_id)

    def __getitem__(self, edge_id: str) -> EdgeMaterialBundle:
        bundle = self.get(edge_id)
        if bundle is None:
            raise KeyError(edge_id)
        return bundle

    def values(self):
        for edge_id in self._owner_by_edge_id:
            bundle = self.get(edge_id)
            if bundle is not None:
                yield bundle

    def __len__(self) -> int:
        return len(self._owner_by_edge_id)


# 改善計画T248: split直後の初回リクエスト（_build_search_materials_uncached）は
# graph_material_cacheへ書き込まないため、次のリクエストもタイル単位のDB読み出しから
# やり直していた（本番実測: 1回目27.6秒[新規split]→2回目13.3秒[キャッシュ未着火]→
# 3回目4.9秒[真の温パス、T224目標達成]）。レスポンスを遅らせないよう、split直後に
# バックグラウンドで対象タイルのキャッシュを温める（region_service.pyの
# _maybe_trigger_graph_build/_build_graph_for_tile_backgroundと同じ考え方。対象データ
# ・キャッシュ先が異なる別モジュールのため状態は分けて持つ）。
_warming_tiles: set[tuple[int, int, int]] = set()
# 改善計画T469: 温め失敗後、同じタイルが即座に無条件で再試行され続けると（対象bboxを含む
# リクエストのたびにトリガーされるため）、持続的に失敗する要因（DB障害等）があった場合に
# 無駄なバックグラウンドセッションを開き続けてしまう。region_service.py:
# _last_build_check/_GRAPH_CHECK_TTL_SECONDSと同じ設計（試行[成功/失敗問わず]ごとに
# 一定時間は同じタイルへの再試行を抑える、成功時は次回のキャッシュヒット判定で
# そもそもこのクールダウンへ到達しないため実質は失敗時の再試行間隔として働く）。
_last_warm_attempt: dict[tuple[int, int, int], float] = {}
_WARM_RECHECK_TTL_SECONDS = 300.0


def _maybe_warm_tile_cache(bbox: BoundingBox) -> None:
    now = time.monotonic()
    for x, y in tiles_covering_bbox(bbox, ROAD_GRAPH_TILE_ZOOM):
        tile = (x, y)
        if tile in _warming_tiles or graph_material_cache.get_tile_materials(ROAD_GRAPH_TILE_ZOOM, x, y) is not None:
            continue
        last_attempt = _last_warm_attempt.get(tile)
        if last_attempt is not None and now - last_attempt < _WARM_RECHECK_TTL_SECONDS:
            continue
        _warming_tiles.add(tile)
        asyncio.create_task(_warm_tile_cache_background(x, y, now))


async def _warm_tile_cache_background(x: int, y: int, attempted_at: float) -> None:
    """リクエストのセッションとは別の新規セッションを使う（HTTPレスポンスが返った後も
    タスクを続けるため、T59の_build_graph_for_tile_backgroundと同じ理由）。

    改善計画T536: 材料（graph_material_cache）だけでなく静的スコア行列
    （tile_score_matrix_cache）もあわせて温める——ここで温めておかないと、次回の
    リクエストが材料キャッシュはヒットするのにスコア行列だけ未着火のまま構築する
    手戻りが発生する。
    """
    try:
        async with get_session_factory()() as session:
            service = GraphService(repository=RoadGraphRepository(session))
            materials = await service._get_or_build_tile_materials(x, y)
            accident_years_covered = await service.get_accident_years_covered()
            await service._get_or_build_tile_score_matrix(x, y, materials, accident_years_covered)
    except Exception as exc:  # noqa: BLE001 バックグラウンド温めの失敗は元のレスポンスに影響させない
        logger.warning(
            "タイル材料キャッシュのバックグラウンド温めに失敗 zoom=%d x=%d y=%d error=%r",
            ROAD_GRAPH_TILE_ZOOM, x, y, exc,
        )
    finally:
        _warming_tiles.discard((x, y))
        _last_warm_attempt[(x, y)] = attempted_at


class GraphService:
    """指定bboxのRoad Graph（Node/Directed Edge）をPostGIS（`repository`）経由で取得する。

    既存のルート探索（RouteGenerator）から使われる。地図表示（RegionService）も
    タイル配信のバックグラウンドで`get_or_build_graph_with_attributes`を呼ぶ（改善計画T59:
    ルート生成した地点でしか道路グラフが構築されず、地図を眺めるだけの利用では
    road_nodes/road_edgesが永遠に空のままだった問題への対応。region_service.py参照）。

    `get_or_build_graph_with_attributes`はPostGIS（PBF取込バッチ等でタイル取得済みマーク
    された範囲）のみを読み、取込範囲外はデータ未整備としてNoneを返す（Overpassへは
    問い合わせない。改善計画T22でOverpassフォールバックを撤去済み）。タイル取得時に
    交差点分割（build_road_graph）は行わない。分割計算はDB上の既知の生データ全体から
    近傍Wayを含めて都度行う（タイル境界依存の交差点分割不一致問題への根本対応。
    詳細はdocs/architecture.md参照）。ただし生データが前回のsplit以降変わっていなければ、
    その分割計算・永続化を丸ごと省略して既存のroad_edges/road_nodesを直接読む
    （`RoadGraphRepository.is_split_up_to_date`参照）。

    `repository`未接続（DBなし構成）でOverpassから都度構築する経路は改善計画T222で
    撤去済み（`repository`は必須）。
    """

    def __init__(self, repository: RoadGraphRepository):
        self._repository = repository
        # 改善計画T391: get_edges_with_geometryのみ、RouteGenerator.generate_loopsの
        # 8方位asyncio.gather経由でRoadGraphEngine.trace_loopから同時に呼ばれうる
        # （このメソッド以外は常にgather開始前のprepare段階で逐次呼ばれるため対象外）。
        # repository内包のSQLAlchemy AsyncSessionは同一セッションへの同時アクセスが
        # 未定義動作/例外を招くため（elevation_attribute_service.pyの同種ロックと同じ理由、
        # docs/decisions/road-graph-migration.md「AsyncSessionの同時使用クラッシュ」参照）、
        # そこだけロックで直列化する。
        self._repository_lock = asyncio.Lock()

    async def _ensure_tiles_cached(self, bbox: BoundingBox) -> bool:
        """bboxを覆う全z12タイルが取込済みかを1クエリで判定する（改善計画T229:
        タイル数ぶん`is_tile_cached`を個別に呼ぶループを`get_cached_tiles`の1回の
        バッチ問い合わせへ集約。半径10kmの起点1件で6回の個別往復が発生していたのを解消）。

        1つでも未取込のタイルがあれば、そのbboxは「データ未整備」としてFalseを返す
        （Overpassへは問い合わせない。改善計画T22でOverpassフォールバックを撤去済み。
        ログ方針: 常時WARNING。PBF取込漏れ・想定外の範囲へのリクエストを運用で
        気づけるようにする）。
        """
        tiles = tiles_covering_bbox(bbox, ROAD_GRAPH_TILE_ZOOM)
        cached_tiles = await self._repository.get_cached_tiles(ROAD_GRAPH_TILE_ZOOM, tiles)
        missing = [tile for tile in tiles if tile not in cached_tiles]
        if not missing:
            return True
        x, y = missing[0]
        logger.warning(
            "Road Graphタイルが取込範囲外 z=%d x=%d y=%d bbox=(%.2f,%.2f,%.2f,%.2f)",
            ROAD_GRAPH_TILE_ZOOM, x, y,
            bbox.min_latitude, bbox.min_longitude, bbox.max_latitude, bbox.max_longitude,
        )
        return False

    async def _ensure_split_up_to_date(self, bbox: BoundingBox) -> bool:
        """`is_split_up_to_date`のRedis cache-aside（改善計画T390）。

        `_ensure_tiles_cached`と同じ「bboxを覆う全z12タイルについて、Redisで
        判定できる分は即答し、できない分だけPostGISへ問い合わせる」構造。
        `is_split_up_to_date`はbbox内の主対象Wayが1件でも未splitならFalseを返す判定のため、
        タイル単位でTrue/Falseへ分解できない——Redisに「split鮮度確認済み」が立っている
        タイルが1枚でも欠けていれば、bbox全体をPostGISへ問い合わせて確定させる（部分的な
        キャッシュヒットで済ませない、正しさを優先する設計）。Trueと確定した場合のみ、
        覆う全タイルへ確認済みマーカーを書き戻す（road_graph_tile_cache.get_split_fresh_subset/
        mark_split_freshのdocstring参照。Falseはキャッシュしない——次回のリクエストで
        `get_or_build_graph_with_attributes`がsave_graph経由で改めてマークする）。
        """
        tiles = tiles_covering_bbox(bbox, ROAD_GRAPH_TILE_ZOOM)
        fresh_tiles = await road_graph_tile_cache.get_split_fresh_subset(ROAD_GRAPH_TILE_ZOOM, tiles)
        if len(fresh_tiles) == len(tiles):
            return True
        up_to_date = await self._repository.is_split_up_to_date(bbox)
        if up_to_date:
            await road_graph_tile_cache.mark_split_fresh(ROAD_GRAPH_TILE_ZOOM, tiles)
        return up_to_date

    async def get_or_build_graph_with_attributes(
        self, bbox: BoundingBox
    ) -> tuple[RoadGraphLike, dict[str, str | None]] | None:
        """PostGIS（`repository`）のみを参照してRoad Graphを返す。

        まず要求bboxを`domain/region.py: ROAD_GRAPH_TILE_ZOOM`のXYZタイル群に分解し、
        `_ensure_tiles_cached`で「生データを取得済みか」を判定する（地域路面レイヤー/
        RegionServiceと同じ「タイル単位で厳密にキャッシュする」考え方）。
        未取得のタイルが1つでもあれば、そのbboxは「データ未整備」としてNoneを返す
        （Overpassへは問い合わせない。改善計画T22）。

        全タイルの生データ取得を確認できた後、まず`is_split_up_to_date`で「対象bboxの生データが
        前回のsplit以降変わっていないか」を確認する。変わっていなければ`get_graph_in_bbox`で
        road_edges/road_nodesを直接読み出し、`get_surface_attributes`で
        road_edges.osm_way_id経由のosm_raw_ways.surfaceをJOIN導出する（省略パス。
        closure再計算・Edge全量再UPSERTを丸ごと避けられる。実データでの計測は
        `benchmarks/bench_postgis_prepare.py`参照）。

        生データが変わっていた場合（または未取込）は、`get_way_specs_with_closure`でDB上の
        既知の生データ全体から対象Wayとその近傍Wayを取得し、その場でbuild_road_graphを
        実行して交差点分割を計算する通常経路にフォールバックする。これにより、どのタイル
        経由で取得したデータかに関わらず一貫した分割結果が得られる（タイル境界依存の
        交差点分割不一致問題への根本対応。詳細・残存する制約はdocs/architecture.md参照）。
        """
        if not await self._ensure_tiles_cached(bbox):
            return None

        # 生データ（osm_raw_ways）が前回のsplit以降変わっていなければ、closure再計算・
        # Edge全量再UPSERTを省略してroad_edges/road_nodesを直接読む（実測で全体の
        # 85〜90%を占めるsave_graphのコストを丸ごと避けられる。docs/osm-pbf-import.md参照）。
        if await self._ensure_split_up_to_date(bbox):
            graph = await self._repository.get_graph_in_bbox(bbox)
            if graph is None:
                # 道路が1本も無い地域を確認できた（取得に失敗したのではない）。空グラフを返す。
                empty_graph: RoadGraphLike = RoadGraph(graph_version="cached-empty", nodes={}, edges={})
                return empty_graph, {}
            surface_attributes = await self._repository.get_surface_attributes(list(graph.edges.keys()))
            return graph, surface_attributes

        # 改善計画T264: 冷パス（未split地点、都心規模で数十万Edge級）でどの段が支配的かを
        # 特定するため、closure取得・build_road_graph・save_graph（自身が個別ログ済み）を
        # ステージ別に計測する（docs/logging.mdの方針、save_graphの既存ログと同じ考え方）。
        rebuild_started = time.monotonic()

        # 必要なタイルの生データは全て取得済み（元々キャッシュ済み、または今回の取得に成功）。
        way_specs, node_coords, primary_way_ids = await self._repository.get_way_specs_with_closure(bbox)
        closure_ms = round((time.monotonic() - rebuild_started) * 1000)
        if not way_specs:
            # 道路が1本も無い地域を確認できた（取得に失敗したのではない）。空グラフを返す。
            # 改善計画T262: この経路（再構築フォールバック）はLeanRoadGraphで統一する。
            return LeanRoadGraph(graph_version="cached-empty", nodes={}, edges={}), {}

        # 改善計画T261: build_road_graph（交差点分割、純Pythonの同期CPU処理）は都心規模
        # （数万way）で数秒規模かかる（bench_postgis_prepare.py実測: 4kmで1.1秒、
        # 20km規模ではさらに長くなる）。awaitせず直接呼ぶとイベントループを丸ごと塞ぎ、
        # その間ヘルスチェック（/health）にも応答できなくなる。road_graph_repository.pyの
        # `_rows_to_road_graph`/`_topology_rows_to_road_graph`が同種の重いCPU処理を
        # asyncio.to_threadで逃がしているのと同じ対応。T105が記録した「タイル要求急増→
        # CPU専有→ヘルスチェック無応答→Render強制再起動」と同型の障害が、本番の実プロセス
        # 経由での大規模ルート生成リクエストで再現したことを受けて追加した。
        build_started = time.monotonic()
        graph = await asyncio.to_thread(build_road_graph, way_specs, node_coords)
        build_ms = round((time.monotonic() - build_started) * 1000)
        surface_by_way_id = {w.osm_way_id: w.surface for w in way_specs if w.osm_way_id is not None}

        # 永続化・返却するのは主対象Way分のみ（近傍Wayは分割の文脈情報として使うだけで、
        # この呼び出しでは保存・返却しない。road_graph_repository.pyのdocstring参照）。
        primary_edges = {
            edge_id: edge for edge_id, edge in graph.edges.items() if edge.osm_way_id in primary_way_ids
        }
        referenced_node_ids = {edge.from_node_id for edge in primary_edges.values()} | {
            edge.to_node_id for edge in primary_edges.values()
        }
        primary_nodes = {node_id: node for node_id, node in graph.nodes.items() if node_id in referenced_node_ids}
        # 改善計画T262: build_road_graphが既にLeanRoadGraphを返すため、ここでも
        # 再度Pydantic RoadGraphへ変換せずLeanRoadGraphのまま保持する。
        primary_graph = LeanRoadGraph(graph_version=graph.graph_version, nodes=primary_nodes, edges=primary_edges)
        primary_surface_attributes = surface_by_edge_id(primary_graph, surface_by_way_id)

        save_started = time.monotonic()
        await self._repository.save_graph(primary_graph, way_ids_to_replace=primary_way_ids)
        # 「分割結果の保存」を1コミットで確定する（上記と同じ規約。surfaceは
        # road_edges.osm_way_id経由でosm_raw_ways.surfaceから導出するため、Edge単位の
        # 保存は不要、改善計画T9）。
        await self._repository.commit()
        # 改善計画T390: このbboxの主対象Way（primary_way_ids）は今まさにsplit_at=now相当まで
        # 更新済みのため、is_split_up_to_dateのcache-asideへ即座に確認済みマークを書き戻す
        # （次回同一エリアへのリクエストがPostGISへ再確認しに行かずに済む。bboxを覆う
        # タイル集合は_ensure_split_up_to_dateと同じtiles_covering_bboxで求める——
        # primary_way_idsは元々このbboxに対するis_split_up_to_date判定が対象にした集合と
        # 同一なので、このbboxのタイル集合をそのままフレッシュとしてマークしてよい）。
        await road_graph_tile_cache.mark_split_fresh(
            ROAD_GRAPH_TILE_ZOOM, tiles_covering_bbox(bbox, ROAD_GRAPH_TILE_ZOOM)
        )
        save_ms = round((time.monotonic() - save_started) * 1000)
        total_ms = round((time.monotonic() - rebuild_started) * 1000)
        logger.info(
            "get_or_build_graph_with_attributes rebuild ways=%d primary_ways=%d primary_edges=%d "
            "closure_ms=%d build_ms=%d save_ms=%d total_ms=%d",
            len(way_specs), len(primary_way_ids), len(primary_edges),
            closure_ms, build_ms, save_ms, total_ms,
        )

        return primary_graph, primary_surface_attributes

    async def get_search_materials_for_bbox(
        self, bbox: BoundingBox
    ) -> tuple[SearchMaterials, StaticEdgeScoreMatrix, frozenset[tuple[int, int, int]] | None] | None:
        """探索フェーズ（`RoadGraphEngine.prepare`）向けに、Road Graphのトポロジ＋材料
        （surface/edge_attribute_counts/way_tags/elevation_attributes/designated_edge_ids）と、
        改善計画T536の「Edge×公開軸」静的スコア行列（`StaticEdgeScoreMatrix`）をまとめて
        返す（改善計画T219、T12 Stage 1）。

        `get_or_build_graph_with_attributes`は1回のリクエストのbbox全体で
        素材を都度取得するため、同じエリアへ2回目以降のリクエストが来ても毎回DBへ
        問い合わせていた。本メソッドはbboxをz12タイル（`ROAD_GRAPH_TILE_ZOOM`）に分解し、
        タイル単位でプロセス内メモリキャッシュ（`infrastructure/graph_material_cache.py`・
        `infrastructure/tile_score_matrix_cache.py`）を経由することで、既にキャッシュ済みの
        タイルだけで完結するリクエストはDBへ一切アクセスせず、探索コストの軸別スコア
        算出（Edgeごとの重いPython評価）も行わない。

        対象bboxのデータが前回のsplit以降変わっている稀なケース（`is_split_up_to_date`が
        False）は、既存の`get_or_build_graph_with_attributes`（フルグラフ構築・保存を含む
        重い経路）と個別の材料取得メソッドをそのまま呼ぶ。このリクエスト自体の応答は
        タイルキャッシュを経由せず返すが（bboxはタイル境界と一致しないため、部分的な
        データをタイル単位キャッシュへ書き込むと次回以降のリクエストへ不完全な結果を
        返しかねない）、応答後にバックグラウンドで対象タイルを正規の経路
        （`_get_or_build_tile_materials`、タイル全体をDBから取得）で温める
        （改善計画T248: 温めが無いと直後の2回目リクエストもキャッシュ未着火のまま
        DB読み出しになる問題があった。`_maybe_warm_tile_cache`参照）。

        改善計画T537: 戻り値の3つ目（タイル集合）は、`graph`がbboxを覆う全z12タイルの
        材料キャッシュをそのまま結合したもの（`_build_search_materials_from_tile_cache`
        経由）である場合のみ設定される。`_build_search_materials_uncached`（split鮮度が
        古くbbox限定で再構築した経路）はNoneを返す——このgraphはタイル境界と一致しない
        不完全な集合（上記のタイルキャッシュを書き込まない理由と同じ）のため、
        呼び出し側（`RoadGraphEngine`）は`infrastructure/search_graph_cache.py`
        （探索用グラフ・索引のタイル集合キーLRU）をこの場合は経由しない。
        """
        if not await self._ensure_tiles_cached(bbox):
            return None

        # accident_count_per_km_year軸材料の年正規化に必要（改善計画T536: 静的スコア
        # 行列の構築に必要なため、タイル単位キャッシュへ入る前にここで1回だけ解決する。
        # get_accident_years_coveredはbboxに依存しないグローバル値で既にプロセス内
        # 単一値キャッシュ済みのため、ここで先に呼んでも追加のDB往復は増えない）。
        accident_years_covered = await self.get_accident_years_covered()

        if not await self._ensure_split_up_to_date(bbox):
            built = await self._build_search_materials_uncached(bbox, accident_years_covered)
            if built is None:
                return None
            materials, score_matrix = built
            return materials, score_matrix, None

        return await self._build_search_materials_from_tile_cache(bbox, accident_years_covered)

    async def _build_search_materials_uncached(
        self, bbox: BoundingBox, accident_years_covered: int
    ) -> tuple[SearchMaterials, StaticEdgeScoreMatrix] | None:
        built = await self.get_or_build_graph_with_attributes(bbox)
        if built is None:
            return None
        graph, surface_attributes = built
        edge_ids = list(graph.edges.keys())
        # 改善計画T264: get_or_build_graph_with_attributesのrebuild内訳
        # （closure_ms/build_ms/save_ms）をログ済みだが、その合計とprepare_ms全体との
        # 差分（本番30km実測で約17秒）がこのバッチ取得由来かをここで確認する。
        materials_started = time.monotonic()
        # 改善計画T248: surface_attributesはget_or_build_graph_with_attributesが
        # 既に取得済みのため、get_edge_materials_batchが返すbundle.surfaceは使わず
        # ここで上書きする（get_edge_materials_batch側のsurface取得自体は捨てる
        # 二重取得になるが、このメソッド自体が低頻度・重い処理のuncachedフォールバック
        # 経路のため許容する）。
        batch = await self._repository.get_edge_materials_batch(edge_ids)
        materials_ms = round((time.monotonic() - materials_started) * 1000)
        # isinstanceで実リポジトリのときだけ発火させる（region_service.pyの
        # _maybe_trigger_graph_build呼び出し箇所と同じ理由。テストのFakeRoadGraphRepositoryは
        # ダックタイピングでこのクラスを継承しないため、ここで弾かれ実DBセッションを
        # 開こうとしない）。
        if isinstance(self._repository, RoadGraphRepository):
            _maybe_warm_tile_cache(bbox)
        materials = {
            edge_id: replace(bundle, surface=surface_attributes.get(edge_id))
            for edge_id, bundle in batch.materials.items()
        }
        # 改善計画T536: このbboxはタイル境界と一致しないため結果をタイルキャッシュへ
        # 書き込まないのはmaterials同様だが、静的スコア行列自体はこの応答（探索コスト）が
        # 使うため、ここで1回だけ構築する（応答後のバックグラウンド温め成功後は次回以降
        # 正規のタイル単位キャッシュ経由になる）。
        score_matrix_started = time.monotonic()
        score_matrix = build_static_edge_score_matrix(graph, materials, accident_years_covered)
        score_matrix_ms = round((time.monotonic() - score_matrix_started) * 1000)
        logger.info(
            "_build_search_materials_uncached edges=%d materials_ms=%d score_matrix_ms=%d",
            len(edge_ids), materials_ms, score_matrix_ms,
        )
        return SearchMaterials(graph=graph, materials=materials), score_matrix

    async def _build_search_materials_from_tile_cache(
        self, bbox: BoundingBox, accident_years_covered: int
    ) -> tuple[SearchMaterials, StaticEdgeScoreMatrix, frozenset[tuple[int, int, int]]]:
        # 改善計画T248: このメソッドはタイルキャッシュ経路専用（_get_or_build_tile_materials
        # は常にLeanRoadGraphを返す）のため、結合後もLeanRoadGraphで統一する。
        combined_nodes: dict[str, LeanNode] = {}
        combined_edges: dict[str, LeanEdge] = {}
        # 改善計画T546: 複数タイルの材料（EdgeMaterialTable/dict、_get_or_build_tile_materials
        # が返すSearchMaterials.materials）は、以前は`dict.update`で即座にEdge単位の
        # EdgeMaterialBundleへ復元・結合していたが、これは`EdgeMaterialTable`導入の目的
        # （Edge単位のPythonオブジェクト再構築を経路上のEdge[数百本]だけに限定し、
        # ディスク復元コストと切り離す）を結合時点で台無しにしてしまう
        # （bbox全体[数十万Edge]ぶん毎回復元することになるため）。owner_by_edge_id
        # （edge_id→タイルindexの軽量な辞書、combined_edgesの結合と同じO(Edge数)の
        # 避けられないコスト）だけをここで構築し、実際のEdgeMaterialBundle復元は
        # `_CombinedEdgeMaterials.get(edge_id)`が呼ばれた時点まで遅延する。

        tiles = tiles_covering_bbox(bbox, ROAD_GRAPH_TILE_ZOOM)
        materials_stage_started = time.monotonic()
        # 改善計画T546: タイルごとの読み込み内訳（メモリ/ディスク/DBのいずれを経由したか、
        # ディスク経由ならread_ms/unpickle_ms/bytes）を集約し、リクエスト単位の1行INFO
        # サマリへ載せる（docs/logging.mdの方針、以後の回帰をログ1行で追えるようにする
        # ——対応方針項目6）。
        materials_read_stats: list[dict[str, object]] = [{} for _ in tiles]
        # 改善計画T538フォローアップ: 逐次forループだとタイルごとのキャッシュ読み込み
        # （ディスクフォールバック時のpickle読み込みを含む）が積み上がる（本番実測
        # 16タイルで約21.5秒）。asyncio.gatherで並列化する。tiles/tile_materials_listの
        # 順序は一致する（asyncio.gatherは渡した順で結果を返す）ため、後続の
        # combine_static_edge_score_matricesの「後勝ち」セマンティクス（列順）は
        # 従来と変わらない。DB問い合わせが必要になるケース（キャッシュmiss）は
        # _get_or_build_tile_materials内でself._repository_lockにより直列化される。
        tile_materials_list = await asyncio.gather(
            *(
                self._get_or_build_tile_materials(x, y, stats)
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
        # 改善計画T536: 複数タイルの静的スコア行列を、上と同じ「後勝ち」セマンティクスで
        # 結合する（combine_static_edge_score_matrices参照）。
        score_matrix = combine_static_edge_score_matrices(list(tile_score_matrices))
        # 改善計画T537: このgraphはbboxを覆う全z12タイルの材料キャッシュをそのまま結合した
        # ものなので、タイル集合そのものが「このgraph/score_matrixを再現するために必要十分な
        # キー」になる（同じタイル集合なら、combined_nodes/combined_edgesの中身は常に同じ）。
        # 呼び出し元（RoadGraphEngine）はこの集合を探索用グラフ・索引のキャッシュキーとして使う
        # （infrastructure/search_graph_cache.py）。
        tile_set = frozenset((ROAD_GRAPH_TILE_ZOOM, x, y) for x, y in tiles)

        # 改善計画T546（対応方針項目6）: メモリ/ディスク/DBの内訳とディスク経由の
        # read_ms/unpickle_ms/bytes合計を1行INFOへまとめる（材料・スコア行列の両方）。
        all_stats = materials_read_stats + matrix_read_stats
        source_counts = Counter(str(stats.get("source", "db")) for stats in all_stats)
        total_read_ms = sum(float(stats.get("read_ms", 0.0)) for stats in all_stats)
        total_unpickle_ms = sum(float(stats.get("unpickle_ms", 0.0)) for stats in all_stats)
        total_bytes = sum(int(stats.get("bytes", 0)) for stats in all_stats)
        materials_ms = round((time.monotonic() - materials_stage_started) * 1000)
        logger.info(
            "_build_search_materials_from_tile_cache tiles=%d memory=%d disk=%d db=%d "
            "disk_read_ms=%.1f disk_unpickle_ms=%.1f disk_bytes=%d materials_ms=%d",
            len(tiles), source_counts.get("memory", 0), source_counts.get("disk", 0),
            source_counts.get("db", 0), total_read_ms, total_unpickle_ms, total_bytes, materials_ms,
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
        self, x: int, y: int, read_stats: dict[str, object] | None = None
    ) -> SearchMaterials:
        # 改善計画T538フォローアップ: get_tile_materials自体はメモリLRU miss時に
        # tile_persistent_cache経由でディスクのpickleファイルを同期的に読む。
        # asyncio.to_threadでスレッドプールへ逃がすことで、呼び出し元
        # （_build_search_materials_from_tile_cache）がasyncio.gatherで複数タイルを
        # 同時に呼んだときディスクI/Oが実際に並列化される（本番実測で確認、
        # docs/tasks/T538.md参照）。改善計画T546: 同時実行数は
        # `settings.tile_cache_load_max_concurrent`のsemaphoreで縛る（対応方針項目7、
        # C1で残るCPUコストはPythonループのためGILで直列化され、コア数を増やして
        # 効くのはI/O部分のみという前提。モジュール冒頭のコメント参照）。`read_stats`は
        # 呼び出し元が渡す出力用の辞書で、渡された場合のみ"source"（memory/disk/db）と
        # ディスク経由時の内訳（read_ms/unpickle_ms/bytes）を書き込む。
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

            edge_ids = list(graph.edges.keys())
            # 改善計画T248・T533: 材料を個別に取得する代わりに1回のJOINクエリへ統合し
            # （dev DB実測、71,791 Edgeで現行5クエリ8.33秒→統合1クエリ1.30秒、6.4倍）、
            # 戻り値もEdge単位で1オブジェクトへ統合する（EdgeMaterialBundle参照）。
            batch = await self._repository.get_edge_materials_batch(edge_ids)
            # 改善計画T546（対応方針項目2）: DB冷パス自体（行→bundle構築）は無変更にし、
            # キャッシュへ入れる直前にfrom_bundles()で列指向テーブル化する
            # （ディスク永続化されるのはこのEdgeMaterialTableで、以後の復元コストが
            # Edge数に依存しなくなる、docs/tasks/T546.md参照）。
            materials = SearchMaterials(
                graph=graph, materials=EdgeMaterialTable.from_bundles(edge_ids, batch.materials)
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
        """改善計画T536: タイル単位の「Edge×公開軸」静的スコア行列を、材料キャッシュ
        （`graph_material_cache`）とは別枠のLRU（`tile_score_matrix_cache`）へキャッシュ
        する。軸スタジオでの軸定義編集時（`refresh_axis_definitions`）はこちらだけが
        クリアされ、材料キャッシュは温存される（`tile_score_matrix_cache.py`のdocstring
        参照）。`materials`は`_get_or_build_tile_materials`が返した同じタイルのSearchMaterials
        （キャッシュ済み/新規取得どちらでも、材料自体はここで再取得しない）。

        改善計画T538フォローアップ: キャッシュ確認（ディスクフォールバック含む）を
        `_get_or_build_tile_materials`と同じ理由で`asyncio.to_thread`へ逃がす。
        改善計画T546: `read_stats`は呼び出し元が渡す出力用の辞書（`_get_or_build_tile_
        materials`と同じ意味）。同時実行数のsemaphoreも共有する。
        """
        async with _tile_cache_load_semaphore:
            cached = await asyncio.to_thread(
                tile_score_matrix_cache.get, ROAD_GRAPH_TILE_ZOOM, x, y, read_stats
            )
        if cached is not None:
            return cached
        matrix = build_static_edge_score_matrix(materials.graph, materials.materials, accident_years_covered)
        if read_stats is not None:
            read_stats["source"] = "db"
        tile_score_matrix_cache.set(ROAD_GRAPH_TILE_ZOOM, x, y, matrix)
        return matrix

    async def get_accident_years_covered(self) -> int:
        """事故データの収録年数を返す。

        bboxに依存しないグローバルな値のため、改善計画T219でプロセス内メモリへ
        単一値キャッシュする（`graph_material_cache`、タイル単位キャッシュとは別枠）。
        """
        cached = graph_material_cache.get_accident_years_covered()
        if cached is not None:
            return cached
        value = await self._repository.get_accident_years_covered()
        graph_material_cache.set_accident_years_covered(value)
        return value

    async def get_edges_with_geometry(self, edge_ids: list[str]) -> dict[str, DirectedEdge]:
        """`LeanRoadGraph`として読み込んだ探索用グラフ（geometryプレースホルダのみ）の
        一部Edgeへ、実ジオメトリを後付けで取得する（改善計画T218、T12 Stage 0）。

        改善計画T391: 呼び出し元`RoadGraphEngine.trace_loop`はRouteGenerator.generate_loopsの
        8方位`asyncio.gather`から同時に呼ばれるため、`self._repository_lock`で直列化する
        （`__init__`のコメント参照）。
        """
        async with self._repository_lock:
            return await self._repository.get_edges_with_geometry(edge_ids)
