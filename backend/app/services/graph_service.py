import logging

from app.domain.attributes import EdgeAttributeCounts, ElevationAttribute, SearchMaterials, surface_by_edge_id
from app.domain.graph import DirectedEdge, RoadGraph, build_road_graph
from app.domain.region import ROAD_GRAPH_TILE_ZOOM, BoundingBox, tile_bounds_lonlat, tiles_covering_bbox
from app.infrastructure import graph_material_cache
from app.infrastructure.road_graph_repository import RoadGraphRepository

logger = logging.getLogger("ridecompass.graph")


class GraphService:
    """指定bboxのRoad Graph（Node/Directed Edge）をPostGIS（`repository`）経由で取得する。

    既存のルート探索（RoutingService/RouteGenerator）から使われる。地図表示（RegionService）も
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

    async def get_or_build_graph_with_attributes(
        self, bbox: BoundingBox, *, lean: bool = False
    ) -> tuple[RoadGraph, dict[str, str | None]] | None:
        """PostGIS（`repository`）のみを参照してRoad Graphを返す。

        `lean=True`（改善計画T218、T12 Stage 0）: 「生データがsplit以降変わっていない」
        省略パス（下記）でのみ効く指定で、Edgeのgeometry（形状点列）を取得しない軽量版
        （`RoadGraphRepository.get_graph_topology_in_bbox`）を使う。探索フェーズ
        （経路選択、`RoadGraphEngine.prepare`）はgeometryを必要としない
        （domain/evaluation.py: compute_wind_penaltyがbearing_degを直接使う設計）ため、
        この引数で切り替える。地図表示（RegionServiceのタイル配信）は実ジオメトリが必要な
        ため、既定の`lean=False`のまま呼ぶ。生データ変更を検知し再構築が必要な場合
        （下記のフォールバック経路）は`lean`に関わらず常にbuild_road_graph経由のフル
        グラフを返す（この経路自体が既に低頻度・重い処理のため、リーン化の対象外）。

        まず要求bboxを`domain/region.py: ROAD_GRAPH_TILE_ZOOM`のXYZタイル群に分解し、
        タイルごとに「生データを取得済みか」を`is_tile_cached`で正確に判定する
        （地域路面レイヤー/RegionServiceと同じ「タイル単位で厳密にキャッシュする」考え方）。
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
        for x, y in tiles_covering_bbox(bbox, ROAD_GRAPH_TILE_ZOOM):
            if await self._repository.is_tile_cached(ROAD_GRAPH_TILE_ZOOM, x, y):
                continue

            # 取込範囲外。データ未整備として即Noneを返す（Overpassへは問い合わせない。
            # 改善計画T22でOverpassフォールバックを撤去済み。ログ方針: 常時WARNING。
            # PBF取込漏れ・想定外の範囲へのリクエストを運用で気づけるようにする）。
            logger.warning(
                "Road Graphタイルが取込範囲外 z=%d x=%d y=%d bbox=(%.2f,%.2f,%.2f,%.2f)",
                ROAD_GRAPH_TILE_ZOOM, x, y,
                bbox.min_latitude, bbox.min_longitude, bbox.max_latitude, bbox.max_longitude,
            )
            return None

        # 生データ（osm_raw_ways）が前回のsplit以降変わっていなければ、closure再計算・
        # Edge全量再UPSERTを省略してroad_edges/road_nodesを直接読む（実測で全体の
        # 85〜90%を占めるsave_graphのコストを丸ごと避けられる。docs/osm-pbf-import.md参照）。
        if await self._repository.is_split_up_to_date(bbox):
            graph = await (
                self._repository.get_graph_topology_in_bbox(bbox)
                if lean
                else self._repository.get_graph_in_bbox(bbox)
            )
            if graph is None:
                # 道路が1本も無い地域を確認できた（取得に失敗したのではない）。空グラフを返す。
                return RoadGraph(graph_version="cached-empty", nodes={}, edges={}), {}
            surface_attributes = await self._repository.get_surface_attributes(list(graph.edges.keys()))
            return graph, surface_attributes

        # 必要なタイルの生データは全て取得済み（元々キャッシュ済み、または今回の取得に成功）。
        way_specs, node_coords, primary_way_ids = await self._repository.get_way_specs_with_closure(bbox)
        if not way_specs:
            # 道路が1本も無い地域を確認できた（取得に失敗したのではない）。空グラフを返す。
            return RoadGraph(graph_version="cached-empty", nodes={}, edges={}), {}

        graph = build_road_graph(way_specs, node_coords)
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
        primary_graph = RoadGraph(graph_version=graph.graph_version, nodes=primary_nodes, edges=primary_edges)
        primary_surface_attributes = surface_by_edge_id(primary_graph, surface_by_way_id)

        await self._repository.save_graph(primary_graph, way_ids_to_replace=primary_way_ids)
        # 「分割結果の保存」を1コミットで確定する（上記と同じ規約。surfaceは
        # road_edges.osm_way_id経由でosm_raw_ways.surfaceから導出するため、Edge単位の
        # 保存は不要、改善計画T9）。
        await self._repository.commit()

        return primary_graph, primary_surface_attributes

    async def get_search_materials_for_bbox(self, bbox: BoundingBox) -> SearchMaterials | None:
        """探索フェーズ（`RoadGraphEngine.prepare`）向けに、Road Graphのトポロジ＋材料
        （surface/edge_attribute_counts/way_tags/elevation_attributes/designated_edge_ids）を
        まとめて返す（改善計画T219、T12 Stage 1）。

        `get_or_build_graph_with_attributes(lean=True)`は1回のリクエストのbbox全体で
        素材を都度取得するため、同じエリアへ2回目以降のリクエストが来ても毎回DBへ
        問い合わせていた。本メソッドはbboxをz12タイル（`ROAD_GRAPH_TILE_ZOOM`）に分解し、
        タイル単位でプロセス内メモリキャッシュ（`infrastructure/graph_material_cache.py`）を
        経由することで、既にキャッシュ済みのタイルだけで完結するリクエストはDBへ
        一切アクセスしない（無効化方針はキャッシュモジュールのdocstring参照）。

        対象bboxのデータが前回のsplit以降変わっている稀なケース（`is_split_up_to_date`が
        False）は、既存の`get_or_build_graph_with_attributes`（フルグラフ構築・保存を含む
        重い経路）と個別の材料取得メソッドをそのまま呼ぶ（この経路自体が低頻度・重い処理の
        ため、タイルキャッシュの対象外のまま。ロジックを二重に持たない）。
        """
        for x, y in tiles_covering_bbox(bbox, ROAD_GRAPH_TILE_ZOOM):
            if await self._repository.is_tile_cached(ROAD_GRAPH_TILE_ZOOM, x, y):
                continue
            logger.warning(
                "Road Graphタイルが取込範囲外 z=%d x=%d y=%d bbox=(%.2f,%.2f,%.2f,%.2f)",
                ROAD_GRAPH_TILE_ZOOM, x, y,
                bbox.min_latitude, bbox.min_longitude, bbox.max_latitude, bbox.max_longitude,
            )
            return None

        if not await self._repository.is_split_up_to_date(bbox):
            return await self._build_search_materials_uncached(bbox)

        return await self._build_search_materials_from_tile_cache(bbox)

    async def _build_search_materials_uncached(self, bbox: BoundingBox) -> SearchMaterials | None:
        built = await self.get_or_build_graph_with_attributes(bbox, lean=True)
        if built is None:
            return None
        graph, surface_attributes = built
        edge_ids = list(graph.edges.keys())
        return SearchMaterials(
            graph=graph,
            surface_attributes=surface_attributes,
            edge_attribute_counts=await self.get_edge_attribute_counts(edge_ids),
            way_tags=await self.get_way_tags(edge_ids),
            elevation_attributes=await self.get_elevation_attributes(edge_ids),
            designated_edge_ids=await self.get_designated_edge_ids(edge_ids),
        )

    async def _build_search_materials_from_tile_cache(self, bbox: BoundingBox) -> SearchMaterials:
        combined_nodes: dict = {}
        combined_edges: dict = {}
        combined_surface: dict = {}
        combined_counts: dict = {}
        combined_way_tags: dict = {}
        combined_elevation: dict = {}
        combined_designated: set = set()

        for x, y in tiles_covering_bbox(bbox, ROAD_GRAPH_TILE_ZOOM):
            tile = await self._get_or_build_tile_materials(x, y)
            combined_nodes.update(tile.graph.nodes)
            combined_edges.update(tile.graph.edges)
            combined_surface.update(tile.surface_attributes)
            combined_counts.update(tile.edge_attribute_counts)
            combined_way_tags.update(tile.way_tags)
            combined_elevation.update(tile.elevation_attributes)
            combined_designated |= tile.designated_edge_ids

        graph = RoadGraph(graph_version="tile-cache", nodes=combined_nodes, edges=combined_edges)
        return SearchMaterials(
            graph=graph,
            surface_attributes=combined_surface,
            edge_attribute_counts=combined_counts,
            way_tags=combined_way_tags,
            elevation_attributes=combined_elevation,
            designated_edge_ids=combined_designated,
        )

    async def _get_or_build_tile_materials(self, x: int, y: int) -> SearchMaterials:
        cached = graph_material_cache.get_tile_materials(ROAD_GRAPH_TILE_ZOOM, x, y)
        if cached is not None:
            return cached

        tile_bbox = tile_bounds_lonlat(ROAD_GRAPH_TILE_ZOOM, x, y)
        graph = await self._repository.get_graph_topology_in_bbox(tile_bbox)
        if graph is None:
            # このタイルに道路が1本も無い（取得失敗ではない）。空の結果もキャッシュする
            # （毎回このタイルを無駄に再問い合わせしないため）。
            graph = RoadGraph(graph_version="tile-cache-empty", nodes={}, edges={})

        edge_ids = list(graph.edges.keys())
        materials = SearchMaterials(
            graph=graph,
            surface_attributes=await self._repository.get_surface_attributes(edge_ids),
            edge_attribute_counts=await self._repository.get_edge_attribute_counts(edge_ids),
            way_tags=await self._repository.get_way_tags(edge_ids),
            elevation_attributes=await self._repository.get_elevation_attributes(edge_ids),
            designated_edge_ids=await self._repository.get_designated_edge_ids(edge_ids),
        )
        graph_material_cache.set_tile_materials(ROAD_GRAPH_TILE_ZOOM, x, y, materials)
        return materials

    async def get_way_tags(self, edge_ids: list[str]) -> dict[str, dict[str, str]]:
        """指定edge_idそれぞれの許可リストタグ（静的道路属性P0）を返す（静的道路属性P1残り、
        車ストレス・自転車インフラ評価の入力）。
        """
        return await self._repository.get_way_tags(edge_ids)

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
        """`lean=True`で読み込んだ探索用グラフ（geometryプレースホルダのみ）の一部Edgeへ、
        実ジオメトリを後付けで取得する（改善計画T218、T12 Stage 0）。
        """
        return await self._repository.get_edges_with_geometry(edge_ids)

    async def get_edge_attribute_counts(self, edge_ids: list[str]) -> dict[str, EdgeAttributeCounts]:
        """事故・停止・交差点の事前集計（`edge_attribute_counts`、改善計画T144→T218で
        読み取り配線）を返す。
        """
        return await self._repository.get_edge_attribute_counts(edge_ids)

    async def get_elevation_attributes(self, edge_ids: list[str]) -> dict[str, ElevationAttribute]:
        """指定edge_idそれぞれの事前計算済み標高属性（average_grade等）を返す
        （改善計画T218a、T12 Stage 0.5）。`elevation_attributes`テーブルの単純なキー参照
        のみで、未計算のEdgeへその場でGSIへ問い合わせることはしない（探索フェーズは
        `app.batch.precompute_elevation_attributes`で事前計算済みの値を読むだけに留め、
        リクエスト単位のレイテンシに外部API呼び出しを持ち込まない設計）。
        """
        return await self._repository.get_elevation_attributes(edge_ids)

    async def get_designated_edge_ids(self, edge_ids: list[str]) -> set[str]:
        """指定edge_idのうちKSJ N10/N12に該当するものの集合を返す（外部静的データソース
        T51）。
        """
        return await self._repository.get_designated_edge_ids(edge_ids)
