import pytest

from app.domain.attributes import EdgeAttributeCounts
from app.domain.graph import RoadGraph, WaySpec
from app.domain.osm_adapter import osm_ways_to_way_specs
from app.domain.region import ROAD_GRAPH_TILE_ZOOM, BoundingBox, tile_bounds_lonlat
from app.infrastructure import graph_material_cache
from app.services.graph_service import GraphService


@pytest.fixture(autouse=True)
def _clear_graph_material_cache():
    # 改善計画T219: get_search_materials_for_bboxのタイルキャッシュはプロセス内メモリの
    # モジュールグローバル（graph_material_cache）のため、テスト間で漏れないよう
    # 明示的にクリアする（他のプロセス内メモリキャッシュのテストと同じ規約、
    # test_elevation_client_cache.pyのuse_temp_tile_cache参照）。
    graph_material_cache.clear()
    yield
    graph_material_cache.clear()

BBOX = BoundingBox(min_latitude=35.70, min_longitude=139.70, max_latitude=35.71, max_longitude=139.71)
# ROAD_GRAPH_TILE_ZOOM(=12)においてBBOXはちょうど1タイルに収まる（[(3637, 1612)]）。
# 単一タイルのキャッシュヒット/ミスを検証するテストではBBOXをそのまま使う。
BBOX_TILE = (3637, 1612)

# BBOXのタイル(3637, 1612)と、その隣接タイル(3638, 1612)の両方にまたがるbbox
# （タイル境界を中心付近で構築し、2タイルにきれいに分かれることを事前に確認済み）。
_TILE_A = tile_bounds_lonlat(ROAD_GRAPH_TILE_ZOOM, 3637, 1612)
_TILE_B = tile_bounds_lonlat(ROAD_GRAPH_TILE_ZOOM, 3638, 1612)
TWO_TILE_BBOX = BoundingBox(
    min_latitude=_TILE_A.min_latitude + (_TILE_A.max_latitude - _TILE_A.min_latitude) * 0.25,
    min_longitude=_TILE_A.min_longitude + (_TILE_A.max_longitude - _TILE_A.min_longitude) * 0.5,
    max_latitude=_TILE_A.min_latitude + (_TILE_A.max_latitude - _TILE_A.min_latitude) * 0.75,
    max_longitude=_TILE_B.min_longitude + (_TILE_B.max_longitude - _TILE_B.min_longitude) * 0.5,
)


def _point_in_tile(tile_bbox: BoundingBox, lat_frac: float, lon_frac: float) -> tuple[float, float]:
    lat = tile_bbox.min_latitude + (tile_bbox.max_latitude - tile_bbox.min_latitude) * lat_frac
    lon = tile_bbox.min_longitude + (tile_bbox.max_longitude - tile_bbox.min_longitude) * lon_frac
    return lat, lon


class FakeRoadGraphRepository:
    """road_graph_repository.RoadGraphRepositoryの簡易インメモリ版（実PostGISへの
    接続確認ができない開発環境のため、キャッシュ利用側のオーケストレーションロジック
    ・closure（近傍Way探索）ロジックのみをここで検証する。実SQL/PostGISへのマッピング
    自体は未検証、docs/architecture.md「タイル境界依存の交差点分割不一致問題」参照）。
    """

    def __init__(self):
        self.raw_ways: dict[int, WaySpec] = {}
        self.raw_node_coords: dict[int, tuple[float, float]] = {}
        self.nodes = {}
        self.edges = {}
        self.cached_tiles = set()
        self.save_graph_call_count = 0
        self.save_raw_ways_call_count = 0
        self.get_way_specs_with_closure_call_count = 0
        # updated_at/split_at相当。実DBのタイムスタンプの代わりに単調増加クロックを使う
        # （is_split_up_to_dateのFake版が「split >= touch」で鮮度判定できれば十分なため）。
        self._clock = 0
        self._raw_way_touched_at: dict[int, int] = {}
        self._way_split_at: dict[int, int] = {}
        # 改善計画T219: get_search_materials_for_bboxのタイルキャッシュ経路用。
        self.edge_attribute_counts: dict = {}
        self.way_tags: dict = {}
        self.elevation_attributes: dict = {}
        self.designated_edge_ids: set = set()
        self._accident_years_covered = 0
        self.get_graph_topology_in_bbox_call_count = 0
        self.get_edge_attribute_counts_call_count = 0
        self.get_way_tags_call_count = 0
        self.get_elevation_attributes_call_count = 0
        self.get_designated_edge_ids_call_count = 0
        self.get_accident_years_covered_call_count = 0

    async def commit(self) -> None:
        # 実装はサービス層が操作のまとまりごとにcommitを呼ぶ規約（T6）。Fakeは即時反映の
        # インメモリ辞書のためno-op（呼ばれること自体はオーケストレーションの一部として許容）。
        pass

    def _primary_way_ids_in_bbox(self, bbox: BoundingBox) -> set[int]:
        primary_node_ids = {
            node_id
            for node_id, (lat, lon) in self.raw_node_coords.items()
            if bbox.min_latitude <= lat <= bbox.max_latitude and bbox.min_longitude <= lon <= bbox.max_longitude
        }
        if not primary_node_ids:
            return set()
        return {way_id for way_id, way in self.raw_ways.items() if set(way.node_ids) & primary_node_ids}

    async def save_raw_ways(self, way_specs: list[WaySpec], node_coords: dict[int, tuple[float, float]]) -> None:
        self.save_raw_ways_call_count += 1
        self._clock += 1
        now = self._clock
        for way in way_specs:
            if way.osm_way_id is None:
                continue
            existing = self.raw_ways.get(way.osm_way_id)
            # 実装のchange_detection_columns（node_ids/highway/surface/direction）と同じ
            # 比較対象。内容が同一な再保存ではtouched_atを進めない（Finding Aの再現）。
            content_changed = existing is None or (
                existing.node_ids,
                existing.highway,
                existing.surface,
                existing.direction,
            ) != (way.node_ids, way.highway, way.surface, way.direction)
            self.raw_ways[way.osm_way_id] = way
            for node_id in way.node_ids:
                if node_id in node_coords:
                    self.raw_node_coords[node_id] = node_coords[node_id]
            if content_changed:
                self._raw_way_touched_at[way.osm_way_id] = now

    async def get_way_specs_with_closure(
        self, bbox: BoundingBox
    ) -> tuple[list[WaySpec], dict[int, tuple[float, float]], set[int]]:
        self.get_way_specs_with_closure_call_count += 1
        primary_way_ids = self._primary_way_ids_in_bbox(bbox)
        if not primary_way_ids:
            return [], {}, set()

        primary_ways = {way_id: self.raw_ways[way_id] for way_id in primary_way_ids}
        all_referenced_node_ids = {node_id for way in primary_ways.values() for node_id in way.node_ids}
        neighbor_ways = {
            way_id: way for way_id, way in self.raw_ways.items() if set(way.node_ids) & all_referenced_node_ids
        }

        combined = {**primary_ways, **neighbor_ways}
        way_specs = list(combined.values())
        final_node_ids = {node_id for way in way_specs for node_id in way.node_ids}
        node_coords = {nid: self.raw_node_coords[nid] for nid in final_node_ids if nid in self.raw_node_coords}
        return way_specs, node_coords, set(primary_ways.keys())

    async def is_split_up_to_date(self, bbox: BoundingBox) -> bool:
        primary_way_ids = self._primary_way_ids_in_bbox(bbox)
        for way_id in primary_way_ids:
            touched_at = self._raw_way_touched_at.get(way_id, 0)
            split_at = self._way_split_at.get(way_id, -1)
            if split_at < touched_at:
                return False
        return True

    async def get_graph_in_bbox(self, bbox: BoundingBox) -> RoadGraph | None:
        # 実装（ST_Intersects(Edge.geom, envelope)）の簡易近似: Edgeのジオメトリ上の
        # いずれかの点がbbox内にあればマッチしたとみなす。
        matched_edges = {
            edge_id: edge
            for edge_id, edge in self.edges.items()
            if any(
                bbox.min_latitude <= lat <= bbox.max_latitude and bbox.min_longitude <= lon <= bbox.max_longitude
                for lat, lon in edge.geometry
            )
        }
        if not matched_edges:
            return None
        node_ids = {e.from_node_id for e in matched_edges.values()} | {e.to_node_id for e in matched_edges.values()}
        matched_nodes = {nid: self.nodes[nid] for nid in node_ids if nid in self.nodes}
        return RoadGraph(graph_version="cached", nodes=matched_nodes, edges=matched_edges)

    async def save_graph(self, graph: RoadGraph, way_ids_to_replace: set[int] | None = None) -> None:
        self.save_graph_call_count += 1
        self._clock += 1
        now = self._clock
        if way_ids_to_replace:
            self.edges = {eid: e for eid, e in self.edges.items() if e.osm_way_id not in way_ids_to_replace}
            for way_id in way_ids_to_replace:
                self._way_split_at[way_id] = now
        self.nodes.update(graph.nodes)
        for edge_id, edge in graph.edges.items():
            if way_ids_to_replace is not None and edge.osm_way_id not in way_ids_to_replace:
                continue
            self.edges[edge_id] = edge

    async def get_surface_attributes(self, edge_ids):
        # 実装（road_edges LEFT JOIN osm_raw_ways ON osm_way_id）と同じ導出をインメモリで
        # 再現する: edge_idがedgesに無ければ結果に含めず、osm_way_idが無い/raw_waysに
        # 無ければsurface=None（改善計画T9、専用テーブルは持たない）。
        result = {}
        for edge_id in edge_ids:
            edge = self.edges.get(edge_id)
            if edge is None:
                continue
            way = self.raw_ways.get(edge.osm_way_id) if edge.osm_way_id is not None else None
            result[edge_id] = way.surface if way is not None else None
        return result

    async def is_tile_cached(self, zoom, x, y):
        return (zoom, x, y) in self.cached_tiles

    async def mark_tile_cached(self, zoom, x, y):
        self.cached_tiles.add((zoom, x, y))

    # --- 改善計画T219: get_search_materials_for_bboxのタイルキャッシュ経路が使うメソッド群。
    # get_graph_topology_in_bboxはgeometryの有無を除けばget_graph_in_bboxと同じ結果でよい
    # （このFakeのgeometryは常にジオメトリ込みだが、呼び出し元の材料キャッシュはgeometryを
    # 見ないため実害無し）。呼び出し回数を計測し、タイルキャッシュのヒット確認に使う。

    async def get_graph_topology_in_bbox(self, bbox: BoundingBox) -> RoadGraph | None:
        self.get_graph_topology_in_bbox_call_count += 1
        return await self.get_graph_in_bbox(bbox)

    async def get_edge_attribute_counts(self, edge_ids):
        self.get_edge_attribute_counts_call_count += 1
        return {edge_id: self.edge_attribute_counts[edge_id] for edge_id in edge_ids if edge_id in self.edge_attribute_counts}

    async def get_way_tags(self, edge_ids):
        self.get_way_tags_call_count += 1
        return {edge_id: self.way_tags[edge_id] for edge_id in edge_ids if edge_id in self.way_tags}

    async def get_elevation_attributes(self, edge_ids):
        self.get_elevation_attributes_call_count += 1
        return {edge_id: self.elevation_attributes[edge_id] for edge_id in edge_ids if edge_id in self.elevation_attributes}

    async def get_designated_edge_ids(self, edge_ids):
        self.get_designated_edge_ids_call_count += 1
        return {edge_id for edge_id in edge_ids if edge_id in self.designated_edge_ids}

    async def get_accident_years_covered(self) -> int:
        self.get_accident_years_covered_call_count += 1
        return self._accident_years_covered


async def _seed_tile(
    repository: FakeRoadGraphRepository, zoom: int, x: int, y: int, ways: list[dict], nodes: dict
) -> None:
    """PBF取込バッチ（app/batch/import_pbf.py）が行うのと同じ手順で、生データを
    repositoryへ直接投入する（GraphServiceは改善計画T22でOverpassフォールバックを撤去済みで、
    repositoryモードでは自ら生データを取得・永続化しない読み出し専用になったため、
    テストのセットアップ側でこの投入を肩代わりする）。"""
    way_specs = osm_ways_to_way_specs(ways)
    await repository.save_raw_ways(way_specs, nodes)
    await repository.mark_tile_cached(zoom, x, y)
    await repository.commit()


async def test_with_repository_uncached_tile_returns_none():
    """未取込タイルを含むリクエストは即Noneを返す（改善計画T22でOverpassフォールバックを
    撤去済み、改善計画T222でDBなし構成自体も撤去済み）。"""
    repository = FakeRoadGraphRepository()
    service = GraphService(repository=repository)

    result = await service.get_or_build_graph_with_attributes(BBOX)

    assert result is None


async def test_with_repository_cached_tile_computes_split_on_first_read():
    ways = [{"id": 100, "tags": {"highway": "residential", "surface": "asphalt"}, "nodes": [1, 2]}]
    nodes = {1: (35.700, 139.700), 2: (35.701, 139.701)}
    repository = FakeRoadGraphRepository()
    await _seed_tile(repository, ROAD_GRAPH_TILE_ZOOM, *BBOX_TILE, ways, nodes)
    service = GraphService(repository=repository)

    result = await service.get_or_build_graph_with_attributes(BBOX)

    assert result is not None
    graph, surface_attributes = result
    assert len(graph.edges) == 2  # 双方向
    assert all(v == "asphalt" for v in surface_attributes.values())
    assert repository.save_graph_call_count == 1
    assert repository.get_way_specs_with_closure_call_count == 1
    assert len(surface_attributes) == 2


async def test_with_repository_second_read_uses_fast_path_when_split_up_to_date():
    """生データ不変時の省略パス: 2回目の呼び出しはclosure再計算・save_graphを行わず、
    is_split_up_to_date→get_graph_in_bboxで直接読み出す。"""
    ways = [{"id": 100, "tags": {"highway": "residential", "surface": "asphalt"}, "nodes": [1, 2]}]
    nodes = {1: (35.700, 139.700), 2: (35.701, 139.701)}
    repository = FakeRoadGraphRepository()
    await _seed_tile(repository, ROAD_GRAPH_TILE_ZOOM, *BBOX_TILE, ways, nodes)
    service = GraphService(repository=repository)

    first = await service.get_or_build_graph_with_attributes(BBOX)
    second = await service.get_or_build_graph_with_attributes(BBOX)

    assert repository.get_way_specs_with_closure_call_count == 1  # 省略パスでclosureは1回だけ
    assert repository.save_graph_call_count == 1  # 省略パスでsaveも1回だけ
    assert first is not None and second is not None
    assert set(first[0].edges.keys()) == set(second[0].edges.keys())
    assert first[1].keys() == second[1].keys()


async def test_with_repository_falls_back_to_slow_path_when_raw_way_content_actually_changes():
    """Wayの内容（surfaceタグ）が実際に変わっていれば、is_split_up_to_dateがFalseを返し
    低速パス（closure再計算＋save_graph）が再実行される（Finding B: road_edges直読みが
    stale化を正しく検知できることの確認）。"""
    ways = [{"id": 100, "tags": {"highway": "residential", "surface": "asphalt"}, "nodes": [1, 2]}]
    nodes = {1: (35.700, 139.700), 2: (35.701, 139.701)}
    repository = FakeRoadGraphRepository()
    await _seed_tile(repository, ROAD_GRAPH_TILE_ZOOM, *BBOX_TILE, ways, nodes)
    service = GraphService(repository=repository)

    await service.get_or_build_graph_with_attributes(BBOX)
    assert repository.get_way_specs_with_closure_call_count == 1
    assert repository.save_graph_call_count == 1

    # Wayのsurfaceタグが変わった状況を、save_raw_waysの直接呼び出しでシミュレートする
    # （実際には別バッチでの再取込等で起こりうる。タイルは既にキャッシュ済みのため、
    # 通常のGraphServiceの読み出しフローからは再度save_raw_waysは呼ばれない）。
    await repository.save_raw_ways(
        [WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential", surface="gravel", direction="both")],
        nodes,
    )

    second = await service.get_or_build_graph_with_attributes(BBOX)

    assert repository.get_way_specs_with_closure_call_count == 2  # 変更を検知して低速パス再実行
    assert repository.save_graph_call_count == 2
    assert second is not None
    assert all(v == "gravel" for v in second[1].values())


async def test_with_repository_semantically_identical_resave_does_not_trigger_slow_path():
    """内容が同一な再保存（隣接タイル取込の重複でwayが再送されるケースを模す）では
    is_split_up_to_dateがFalseへ倒れず、低速パスが再発火しないこと（Finding Aの回帰）。"""
    ways = [{"id": 100, "tags": {"highway": "residential", "surface": "asphalt"}, "nodes": [1, 2]}]
    nodes = {1: (35.700, 139.700), 2: (35.701, 139.701)}
    repository = FakeRoadGraphRepository()
    await _seed_tile(repository, ROAD_GRAPH_TILE_ZOOM, *BBOX_TILE, ways, nodes)
    service = GraphService(repository=repository)

    await service.get_or_build_graph_with_attributes(BBOX)
    assert repository.get_way_specs_with_closure_call_count == 1
    assert repository.save_graph_call_count == 1

    # 内容が完全に同一なWayを再保存（隣接タイルの取込で同じWayが再送されるケース）。
    await repository.save_raw_ways(
        [WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential", surface="asphalt", direction="both")],
        nodes,
    )

    second = await service.get_or_build_graph_with_attributes(BBOX)

    assert repository.get_way_specs_with_closure_call_count == 1  # 低速パスは再発火しない
    assert repository.save_graph_call_count == 1
    assert second is not None


async def test_with_repository_bbox_spanning_two_tiles_reads_and_merges_both():
    ways = [{"id": 100, "tags": {"highway": "residential", "surface": "asphalt"}, "nodes": [1, 2]}]
    nodes = {1: (35.710, 139.750), 2: (35.711, 139.751)}
    repository = FakeRoadGraphRepository()
    await _seed_tile(repository, ROAD_GRAPH_TILE_ZOOM, 3637, 1612, ways, nodes)
    await _seed_tile(repository, ROAD_GRAPH_TILE_ZOOM, 3638, 1612, ways, nodes)
    service = GraphService(repository=repository)

    result = await service.get_or_build_graph_with_attributes(TWO_TILE_BBOX)

    assert result is not None


async def test_with_repository_bbox_spanning_two_tiles_returns_none_until_both_cached():
    ways = [{"id": 100, "tags": {"highway": "residential", "surface": "asphalt"}, "nodes": [1, 2]}]
    nodes = {1: (35.710, 139.750), 2: (35.711, 139.751)}
    repository = FakeRoadGraphRepository()
    await _seed_tile(repository, ROAD_GRAPH_TILE_ZOOM, 3637, 1612, ways, nodes)  # 片方のタイルのみ取込済み
    service = GraphService(repository=repository)

    result = await service.get_or_build_graph_with_attributes(TWO_TILE_BBOX)

    assert result is None  # 未取込タイルが1つでもあれば全体としてNone

    await _seed_tile(repository, ROAD_GRAPH_TILE_ZOOM, 3638, 1612, ways, nodes)  # 残りも取込済みにする
    result_2 = await service.get_or_build_graph_with_attributes(TWO_TILE_BBOX)

    assert result_2 is not None


async def test_with_repository_legitimately_empty_area_returns_empty_graph_not_none():
    # 道路が1本も無い地域（海・公園等）を模す。生データが無くてもタイルマーク自体はある
    # （PBF取込バッチはway 0件の地域もタイルとしてマークする）。
    repository = FakeRoadGraphRepository()
    await repository.mark_tile_cached(ROAD_GRAPH_TILE_ZOOM, *BBOX_TILE)
    service = GraphService(repository=repository)

    first = await service.get_or_build_graph_with_attributes(BBOX)

    assert first is not None  # 取込漏れではなく「道路が無いことを確認できた」なのでNoneにしない
    graph, surface_attributes = first
    assert graph.edges == {}
    assert surface_attributes == {}

    second = await service.get_or_build_graph_with_attributes(BBOX)

    assert second is not None
    assert second[0].edges == {}
    # 道路が無い地域は対象Wayが0件のためis_split_up_to_dateが自明にTrue（fresh）となり、
    # 1回目の呼び出しからclosure再計算自体が発生しない。
    assert repository.get_way_specs_with_closure_call_count == 0


async def test_way_split_is_consistent_regardless_of_which_tile_reveals_the_shared_node():
    """タイル境界依存の交差点分割不一致問題（docs/architecture.md参照）の回帰テスト。

    Way W(200)がタイルA/Bの境界をまたぎ、タイルA側のノード11で側道B(201)と交差点を
    共有する。BはタイルAの範囲にのみ存在するため、タイルB単体を見るとBは見えない。
    生データの分離（save_raw_ways）とclosureベースの分割計算（get_way_specs_with_closure）
    により、タイルAが先に取込済みであれば、タイルBだけを新たに取込んだ場合でも
    Wの分割結果（ノード11で2区間に割れること）がタイルAを直接見たときと一致することを確認する。
    """
    tile_a_bbox = tile_bounds_lonlat(ROAD_GRAPH_TILE_ZOOM, 3637, 1612)
    tile_b_bbox = tile_bounds_lonlat(ROAD_GRAPH_TILE_ZOOM, 3638, 1612)
    # 境界ちょうどだと浮動小数点誤差で隣タイルへこぼれ、tiles_covering_bboxが2タイル分
    # 返してしまうことがあるため、問い合わせに使うbboxは少し内側にずらす
    # （tile_bounds_lonlat自体はノード配置の基準としてそのまま使う）。
    eps = 1e-6
    tile_a_query_bbox = BoundingBox(
        min_latitude=tile_a_bbox.min_latitude + eps,
        min_longitude=tile_a_bbox.min_longitude + eps,
        max_latitude=tile_a_bbox.max_latitude - eps,
        max_longitude=tile_a_bbox.max_longitude - eps,
    )
    tile_b_query_bbox = BoundingBox(
        min_latitude=tile_b_bbox.min_latitude + eps,
        min_longitude=tile_b_bbox.min_longitude + eps,
        max_latitude=tile_b_bbox.max_latitude - eps,
        max_longitude=tile_b_bbox.max_longitude - eps,
    )

    node10 = _point_in_tile(tile_a_bbox, 0.5, 0.1)
    node11 = _point_in_tile(tile_a_bbox, 0.5, 0.9)  # タイルA内、境界付近
    node12 = _point_in_tile(tile_b_bbox, 0.5, 0.1)  # タイルB内
    node13 = _point_in_tile(tile_a_bbox, 0.2, 0.9)  # 側道の端点、タイルA内

    way_w = {"id": 200, "tags": {"highway": "residential"}, "nodes": [10, 11, 12]}
    way_b = {"id": 201, "tags": {"highway": "residential"}, "nodes": [11, 13]}

    # タイルAの取込データ: W・B双方が(少なくとも1ノードが)タイルA内にあるため両方含まれる
    # （PBF取込・Overpass取得いずれも「マッチしたWayの完全なノード列」を保持するため、
    # Wのnode12(タイルB内)も含む）。
    tile_a_ways = [way_w, way_b]
    tile_a_nodes = {10: node10, 11: node11, 12: node12, 13: node13}
    # タイルBの取込データ: node12を持つWayのみ含む。Bはどのノードもタイル内に無いため
    # 含まれない（bboxフィルタはノード単位）。
    tile_b_ways = [way_w]
    tile_b_nodes = {10: node10, 11: node11, 12: node12}

    # ケース1: タイルAをまとめて取込済みにする（WとBを同時に見て、node11が交差点だと正しく認識できる）
    repository_a_first = FakeRoadGraphRepository()
    await _seed_tile(repository_a_first, ROAD_GRAPH_TILE_ZOOM, 3637, 1612, tile_a_ways, tile_a_nodes)
    service_a_first = GraphService(repository=repository_a_first)
    await service_a_first.get_or_build_graph_with_attributes(tile_a_query_bbox)
    w_edges_from_tile_a = {eid: e for eid, e in repository_a_first.edges.items() if e.osm_way_id == 200}

    # ケース2: タイルAを先に取込済みにした上で、タイルBは別バッチでway_wのみ再送される
    # （Bのraw dataは既にDBにあるが、タイルBの取込データには含まれない = 従来の実装が
    # 壊れていた状況の再現）。
    repository_b_after_a = FakeRoadGraphRepository()
    await _seed_tile(repository_b_after_a, ROAD_GRAPH_TILE_ZOOM, 3637, 1612, tile_a_ways, tile_a_nodes)
    service_b_after_a = GraphService(repository=repository_b_after_a)
    await service_b_after_a.get_or_build_graph_with_attributes(tile_a_query_bbox)

    await _seed_tile(repository_b_after_a, ROAD_GRAPH_TILE_ZOOM, 3638, 1612, tile_b_ways, tile_b_nodes)
    service_b_only = GraphService(repository=repository_b_after_a)
    await service_b_only.get_or_build_graph_with_attributes(tile_b_query_bbox)
    w_edges_from_tile_b_after_a = {eid: e for eid, e in repository_b_after_a.edges.items() if e.osm_way_id == 200}

    # どちらの経路でも、Wはnode11で2区間（10-11, 11-12）×双方向=4Edgeに分割されるはず
    # （node11が1区間の途中に埋もれた1本のEdgeにはならない）。
    assert len(w_edges_from_tile_a) == 4
    assert len(w_edges_from_tile_b_after_a) == 4
    assert {e.distance_m for e in w_edges_from_tile_a.values()} == {
        e.distance_m for e in w_edges_from_tile_b_after_a.values()
    }


# --- 改善計画T219（T12 Stage 1）: get_search_materials_for_bboxのタイルキャッシュ経路 ---


async def _seeded_service_with_materials() -> tuple[GraphService, FakeRoadGraphRepository]:
    ways = [{"id": 100, "tags": {"highway": "residential", "surface": "asphalt"}, "nodes": [1, 2]}]
    nodes = {1: (35.700, 139.700), 2: (35.701, 139.701)}
    repository = FakeRoadGraphRepository()
    await _seed_tile(repository, ROAD_GRAPH_TILE_ZOOM, *BBOX_TILE, ways, nodes)
    repository.edge_attribute_counts = {
        "way-100-seg0-fwd": EdgeAttributeCounts(accident_count=1.0, stop_count=2, intersection_count=3),
    }
    repository.way_tags = {"way-100-seg0-fwd": {"highway": "residential"}}
    repository.designated_edge_ids = {"way-100-seg0-fwd"}
    service = GraphService(repository=repository)
    return service, repository


async def test_get_search_materials_for_bbox_returns_none_for_uncached_tile():
    repository = FakeRoadGraphRepository()  # タイル未取込
    service = GraphService(repository=repository)

    assert await service.get_search_materials_for_bbox(BBOX) is None


async def test_get_search_materials_for_bbox_builds_materials_on_first_call():
    service, _ = await _seeded_service_with_materials()

    materials = await service.get_search_materials_for_bbox(BBOX)

    assert materials is not None
    edge_id = next(iter(materials.graph.edges))
    assert materials.surface_attributes[edge_id] == "asphalt"
    counts = materials.edge_attribute_counts[edge_id]
    assert (counts.accident_count, counts.stop_count, counts.intersection_count) == (1.0, 2, 3)
    assert materials.way_tags[edge_id] == {"highway": "residential"}
    assert edge_id in materials.designated_edge_ids


async def test_get_search_materials_for_bbox_second_call_uses_tile_cache_without_db_access():
    service, repository = await _seeded_service_with_materials()

    # 1回目は生データがまだ「split済み」と認識されていないため、既存の低速経路
    # （closure再計算＋save_graph、タイルキャッシュの対象外。材料も個別に非キャッシュで
    # 取得される）を通る（test_with_repository_cached_tile_computes_split_on_first_read
    # と同じ前提）。
    first = await service.get_search_materials_for_bbox(BBOX)
    assert repository.get_graph_topology_in_bbox_call_count == 0
    assert repository.get_edge_attribute_counts_call_count == 1

    # 2回目はis_split_up_to_date=Trueとなりタイルキャッシュ経路を通る。この時点では
    # まだタイルキャッシュが空のため、材料取得の各メソッドがもう1回呼ばれてタイル単位で
    # キャッシュされる（1回目の非キャッシュ取得とは独立のため呼び出し回数は2に増える）。
    second = await service.get_search_materials_for_bbox(BBOX)
    assert repository.get_graph_topology_in_bbox_call_count == 1
    assert repository.get_edge_attribute_counts_call_count == 2
    assert repository.get_way_tags_call_count == 2
    assert repository.get_elevation_attributes_call_count == 2
    assert repository.get_designated_edge_ids_call_count == 2

    # 3回目はタイルキャッシュがヒットするため、DBへ一切アクセスしない
    # （改善計画T219の完了条件: 同一エリア2回目以降はDBへ一切アクセスしない）。
    third = await service.get_search_materials_for_bbox(BBOX)
    assert repository.get_graph_topology_in_bbox_call_count == 1
    assert repository.get_edge_attribute_counts_call_count == 2
    assert repository.get_way_tags_call_count == 2
    assert repository.get_elevation_attributes_call_count == 2
    assert repository.get_designated_edge_ids_call_count == 2

    assert first is not None and second is not None and third is not None
    assert set(second.graph.edges.keys()) == set(third.graph.edges.keys())


async def test_get_search_materials_for_bbox_accident_years_covered_is_cached_globally():
    service, repository = await _seeded_service_with_materials()
    repository._accident_years_covered = 5

    first = await service.get_accident_years_covered()
    second = await service.get_accident_years_covered()

    assert (first, second) == (5, 5)
    assert repository.get_accident_years_covered_call_count == 1


async def test_get_search_materials_for_bbox_two_tile_bbox_merges_both_tiles_and_caches_independently():
    ways = [
        {"id": 100, "tags": {"highway": "residential", "surface": "asphalt"}, "nodes": [1, 2]},
        {"id": 200, "tags": {"highway": "residential", "surface": "gravel"}, "nodes": [3, 4]},
    ]
    nodes = {
        1: _point_in_tile(tile_bounds_lonlat(ROAD_GRAPH_TILE_ZOOM, 3637, 1612), 0.4, 0.4),
        2: _point_in_tile(tile_bounds_lonlat(ROAD_GRAPH_TILE_ZOOM, 3637, 1612), 0.6, 0.6),
        3: _point_in_tile(tile_bounds_lonlat(ROAD_GRAPH_TILE_ZOOM, 3638, 1612), 0.4, 0.4),
        4: _point_in_tile(tile_bounds_lonlat(ROAD_GRAPH_TILE_ZOOM, 3638, 1612), 0.6, 0.6),
    }
    repository = FakeRoadGraphRepository()
    await _seed_tile(repository, ROAD_GRAPH_TILE_ZOOM, 3637, 1612, [ways[0]], {1: nodes[1], 2: nodes[2]})
    await _seed_tile(repository, ROAD_GRAPH_TILE_ZOOM, 3638, 1612, [ways[1]], {3: nodes[3], 4: nodes[4]})
    service = GraphService(repository=repository)

    # 1回目は低速経路（closure再計算＋save_graph）を通り、タイルキャッシュには乗らない。
    await service.get_search_materials_for_bbox(TWO_TILE_BBOX)
    assert repository.get_graph_topology_in_bbox_call_count == 0

    # 2回目でis_split_up_to_date=Trueとなりタイルキャッシュ経路（2タイルぶん）を通る。
    materials = await service.get_search_materials_for_bbox(TWO_TILE_BBOX)
    assert materials is not None
    surfaces = set(materials.surface_attributes.values())
    assert surfaces == {"asphalt", "gravel"}
    assert repository.get_graph_topology_in_bbox_call_count == 2  # 2タイルぶん

    # 3回目は両タイルともキャッシュ済みのため、呼び出し回数は増えない。
    await service.get_search_materials_for_bbox(TWO_TILE_BBOX)
    assert repository.get_graph_topology_in_bbox_call_count == 2
