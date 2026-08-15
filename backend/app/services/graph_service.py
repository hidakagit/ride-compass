import logging

import httpx

from app.domain.attributes import surface_by_edge_id
from app.domain.graph import RoadGraph, WaySpec, build_road_graph
from app.domain.osm_adapter import osm_ways_to_way_specs
from app.domain.region import ROAD_GRAPH_TILE_ZOOM, BoundingBox, tile_bounds_lonlat, tiles_covering_bbox
from app.infrastructure.overpass_client import OverpassClient
from app.infrastructure.road_graph_repository import RoadGraphRepository

logger = logging.getLogger("ridecompass.graph")


class GraphService:
    """指定bboxのOSM道路データからRoad Graph（Node/Directed Edge）を構築する。

    OSM Adapter（domain/osm_adapter.py）を介して、OverpassClientが返すOSM生データを
    データソース非依存の`WaySpec`へ変換してからbuild_road_graphへ渡す（仕様書2・47章の
    「OSM Adapter/Importer → Road Graph」の分離、Phase 2）。

    既存のルート探索（RoutingService/RouteGenerator）・地図表示（RegionService）とは
    独立しており、どちらからも参照されない。

    `repository`（infrastructure/road_graph_repository.RoadGraphRepository）を渡すと、
    `get_or_build_graph_with_attributes`がPostGISをread-throughキャッシュとして使う。
    渡さない場合（既定）は、Phase 1-5と同じ「毎回Overpassから構築する」挙動のまま
    （既存の`build_graph_with_surface_tags_for_bbox`の呼び出し方・挙動には一切影響しない）。

    `repository`指定時の`get_or_build_graph_with_attributes`は、タイル取得時に
    交差点分割（build_road_graph）を行わない。生のOSM Way/Nodeデータだけをタイル単位で
    永続化し、実際の分割計算はDB上の既知の生データ全体から近傍Wayを含めて都度行う
    （タイル境界依存の交差点分割不一致問題への根本対応。詳細はdocs/architecture.md参照）。
    ただし生データが前回のsplit以降変わっていなければ、その分割計算・永続化を丸ごと省略して
    既存のroad_edges/road_nodesを直接読む（`RoadGraphRepository.is_split_up_to_date`参照）。
    """

    def __init__(
        self,
        overpass_client: OverpassClient,
        http_client: httpx.AsyncClient,
        repository: RoadGraphRepository | None = None,
        overpass_fallback_enabled: bool = True,
    ):
        self._overpass_client = overpass_client
        self._http_client = http_client
        self._repository = repository
        # PBF取込範囲外のタイルをOverpassへ問い合わせて補完するか（docs/osm-pbf-import.md
        # Phase 3）。Falseなら未取込タイルを含むリクエストは「データ未整備」としてNoneを
        # 返す（Overpassへは行かない）。`repository`未指定時はこのフラグに関わらず常に
        # Overpassから構築する（DBなし構成ではOverpassが唯一のデータソースのため）。
        self._overpass_fallback_enabled = overpass_fallback_enabled

    async def build_graph_with_surface_tags_for_bbox(
        self, bbox: BoundingBox
    ) -> tuple[RoadGraph, dict[int, str | None]] | None:
        """RoadGraphと、同じOverpass取得結果由来のosm_way_id→surfaceタグを同時に返す。

        Edge単位のsurface導出（domain/attributes.py: surface_by_edge_id）は
        Road Graph構築に使ったのと同じWay情報を必要とするため、Overpassへの
        再問い合わせを避けるためにこのメソッドを設けている（1回の取得結果を共有する）。
        """
        built = await self._build(bbox)
        if built is None:
            return None
        graph, way_specs = built
        surface_by_way_id = {w.osm_way_id: w.surface for w in way_specs if w.osm_way_id is not None}
        return graph, surface_by_way_id

    async def get_or_build_graph_with_attributes(
        self, bbox: BoundingBox
    ) -> tuple[RoadGraph, dict[str, str | None]] | None:
        """PostGISキャッシュ（`repository`）があれば優先的に使い、無ければOverpassから
        生データを取得してキャッシュへ保存する（`repository`が未設定なら常にOverpassから
        直接構築する、Phase1-5と同じ挙動）。

        `repository`指定時は、まず要求bboxを`domain/region.py: ROAD_GRAPH_TILE_ZOOM`の
        XYZタイル群に分解し、タイルごとに「生データを取得済みか」を`is_tile_cached`で
        正確に判定する（地域路面レイヤー/RegionServiceと同じ「タイル単位で厳密に
        キャッシュする」考え方）。未取得のタイルだけをOverpassへ順に問い合わせて
        （公開Overpassインスタンスへの配慮として並列化しない）**生のOSM Way/Nodeデータを
        そのまま**永続化する（この時点ではEdgeへの分割は行わない）。

        全タイルの生データ取得を保証した後、まず`is_split_up_to_date`で「対象bboxの生データが
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
        if self._repository is None:
            return await self._fetch_graph_with_surface_attributes(bbox)

        any_tile_fetch_failed = False
        for x, y in tiles_covering_bbox(bbox, ROAD_GRAPH_TILE_ZOOM):
            if await self._repository.is_tile_cached(ROAD_GRAPH_TILE_ZOOM, x, y):
                continue

            if not self._overpass_fallback_enabled:
                # 取込範囲外＋フォールバック無効。データ未整備として即Noneを返す
                # （ログ方針: 常時WARNING。PBF取込漏れ・想定外の範囲へのリクエストを
                # 運用で気づけるようにする。docs/osm-pbf-import.md Phase 3）。
                logger.warning(
                    "Road Graphタイルが取込範囲外（Overpassフォールバック無効） z=%d x=%d y=%d "
                    "bbox=(%.2f,%.2f,%.2f,%.2f)",
                    ROAD_GRAPH_TILE_ZOOM, x, y,
                    bbox.min_latitude, bbox.min_longitude, bbox.max_latitude, bbox.max_longitude,
                )
                return None

            tile_bbox = tile_bounds_lonlat(ROAD_GRAPH_TILE_ZOOM, x, y)
            result = await self._overpass_client.get_ways_and_nodes(self._http_client, tile_bbox)
            if result is None:
                # Overpass取得に失敗した場合はマークしない（次回リクエストで再取得を試みる。
                # RegionServiceのroad-surfaceタイルキャッシュと同じ方針）。この場合、
                # 対象範囲を完全にはカバーできていないため、最終的にNoneを返す
                # （道路が無い空の地域と取得失敗を区別するため。下記参照）。
                any_tile_fetch_failed = True
                continue

            raw_ways, node_coords = result
            way_specs = osm_ways_to_way_specs(raw_ways)
            await self._repository.save_raw_ways(way_specs, node_coords)
            await self._repository.mark_tile_cached(ROAD_GRAPH_TILE_ZOOM, x, y)
            # 「生データ保存＋取得済みマーク」をタイル単位の1コミットで確定する
            # （repositoryはcommitしない規約。road_graph_repository.pyのdocstring参照。
            # 同一トランザクションなので、途中で落ちてもマークだけ残る・データだけ残るという
            # 中途半端な状態にならない）。
            await self._repository.commit()

        if any_tile_fetch_failed:
            return None

        # 生データ（osm_raw_ways）が前回のsplit以降変わっていなければ、closure再計算・
        # Edge全量再UPSERTを省略してroad_edges/road_nodesを直接読む（実測で全体の
        # 85〜90%を占めるsave_graphのコストを丸ごと避けられる。docs/osm-pbf-import.md参照）。
        if await self._repository.is_split_up_to_date(bbox):
            graph = await self._repository.get_graph_in_bbox(bbox)
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

    async def get_stop_poi_counts(self, edge_ids: list[str]) -> dict[str, int]:
        """指定edge_idそれぞれの停止密度評価用カウント（信号・横断歩道・一時停止・踏切、
        静的道路属性P1）を返す。`get_or_build_graph_with_attributes`の3経路分岐とは独立した
        呼び出しにしている（`repository`が無ければ`{}`を返すだけで済み、Overpassフォールバック
        経路には新属性を実装しないというADR方針とも自然に整合するため。docs/decisions/
        pre-static-attributes-gate.md）。
        """
        if self._repository is None:
            return {}
        return await self._repository.get_stop_poi_counts(edge_ids)

    async def _fetch_graph_with_surface_attributes(
        self, bbox: BoundingBox
    ) -> tuple[RoadGraph, dict[str, str | None]] | None:
        built = await self.build_graph_with_surface_tags_for_bbox(bbox)
        if built is None:
            return None
        graph, surface_by_way_id = built
        return graph, surface_by_edge_id(graph, surface_by_way_id)

    async def _build(self, bbox: BoundingBox) -> tuple[RoadGraph, list[WaySpec]] | None:
        result = await self._overpass_client.get_ways_and_nodes(self._http_client, bbox)
        if result is None:
            return None
        raw_ways, nodes = result
        way_specs = osm_ways_to_way_specs(raw_ways)
        graph = build_road_graph(way_specs, nodes)
        return graph, way_specs
