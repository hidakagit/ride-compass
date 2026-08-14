from app.domain.graph import RoadGraph, WaySpec
from app.domain.region import ROAD_GRAPH_TILE_ZOOM, BoundingBox, tile_bounds_lonlat, tiles_covering_bbox
from app.services.graph_service import GraphService

BBOX = BoundingBox(min_latitude=35.70, min_longitude=139.70, max_latitude=35.71, max_longitude=139.71)
# ROAD_GRAPH_TILE_ZOOM(=12)においてBBOXはちょうど1タイルに収まる（[(3637, 1612)]）。
# 単一タイルのキャッシュヒット/ミスを検証するテストではBBOXをそのまま使う。
BBOX_TILE = (3637, 1612)

# BBOXとは重ならない別タイルのbbox（単一タイルに収まるよう小さく取る）。
FAR_BBOX = BoundingBox(min_latitude=10.00, min_longitude=10.00, max_latitude=10.01, max_longitude=10.01)
FAR_BBOX_TILE = (2161, 1933)

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


class FakeOverpassClient:
    def __init__(self, result=None, results_by_call=None):
        """result: 全呼び出しで返す固定値。results_by_call: 呼び出し順に消費するリスト
        （タイルごとに異なる結果を返したいテスト、例えば一部タイルだけ取得失敗させる
        ケースや、タイルごとに異なるWay集合を返したいケースで使う）。
        両方渡した場合はresults_by_callを優先する。"""
        self.call_count = 0
        self._result = result
        self._results_by_call = results_by_call

    async def get_ways_and_nodes(self, http_client, bbox):
        if self._results_by_call is not None:
            result = self._results_by_call[self.call_count]
            self.call_count += 1
            return result
        self.call_count += 1
        return self._result


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
        self.surface_attributes = {}
        self.cached_tiles = set()
        self.save_graph_call_count = 0
        self.save_raw_ways_call_count = 0

    async def save_raw_ways(self, way_specs: list[WaySpec], node_coords: dict[int, tuple[float, float]]) -> None:
        self.save_raw_ways_call_count += 1
        for way in way_specs:
            if way.osm_way_id is None:
                continue
            self.raw_ways[way.osm_way_id] = way
            for node_id in way.node_ids:
                if node_id in node_coords:
                    self.raw_node_coords[node_id] = node_coords[node_id]

    async def get_way_specs_with_closure(
        self, bbox: BoundingBox
    ) -> tuple[list[WaySpec], dict[int, tuple[float, float]], set[int]]:
        primary_node_ids = {
            node_id
            for node_id, (lat, lon) in self.raw_node_coords.items()
            if bbox.min_latitude <= lat <= bbox.max_latitude and bbox.min_longitude <= lon <= bbox.max_longitude
        }
        if not primary_node_ids:
            return [], {}, set()

        primary_ways = {
            way_id: way for way_id, way in self.raw_ways.items() if set(way.node_ids) & primary_node_ids
        }
        all_referenced_node_ids = {node_id for way in primary_ways.values() for node_id in way.node_ids}
        neighbor_ways = {
            way_id: way for way_id, way in self.raw_ways.items() if set(way.node_ids) & all_referenced_node_ids
        }

        combined = {**primary_ways, **neighbor_ways}
        way_specs = list(combined.values())
        final_node_ids = {node_id for way in way_specs for node_id in way.node_ids}
        node_coords = {nid: self.raw_node_coords[nid] for nid in final_node_ids if nid in self.raw_node_coords}
        return way_specs, node_coords, set(primary_ways.keys())

    async def save_graph(self, graph: RoadGraph, way_ids_to_replace: set[int] | None = None) -> None:
        self.save_graph_call_count += 1
        if way_ids_to_replace:
            self.edges = {eid: e for eid, e in self.edges.items() if e.osm_way_id not in way_ids_to_replace}
        self.nodes.update(graph.nodes)
        for edge_id, edge in graph.edges.items():
            if way_ids_to_replace is not None and edge.osm_way_id not in way_ids_to_replace:
                continue
            self.edges[edge_id] = edge

    async def get_surface_attributes(self, edge_ids):
        return {eid: self.surface_attributes[eid] for eid in edge_ids if eid in self.surface_attributes}

    async def save_surface_attributes(self, attributes):
        for attribute in attributes:
            self.surface_attributes[attribute.edge_id] = attribute

    async def is_tile_cached(self, zoom, x, y):
        return (zoom, x, y) in self.cached_tiles

    async def mark_tile_cached(self, zoom, x, y):
        self.cached_tiles.add((zoom, x, y))


async def test_build_graph_for_bbox_returns_road_graph():
    ways = [{"id": 100, "tags": {"highway": "residential"}, "nodes": [1, 2]}]
    nodes = {1: (35.700, 139.700), 2: (35.701, 139.701)}
    overpass_client = FakeOverpassClient(result=(ways, nodes))
    service = GraphService(overpass_client, http_client=None)

    graph = await service.build_graph_for_bbox(BBOX)

    assert graph is not None
    assert len(graph.nodes) == 2
    assert len(graph.edges) == 2  # 双方向
    assert overpass_client.call_count == 1


async def test_build_graph_for_bbox_returns_none_on_overpass_failure():
    overpass_client = FakeOverpassClient(result=None)
    service = GraphService(overpass_client, http_client=None)

    graph = await service.build_graph_for_bbox(BBOX)

    assert graph is None


async def test_build_graph_with_surface_tags_returns_graph_and_way_surface_map():
    ways = [
        {"id": 100, "tags": {"highway": "residential", "surface": "asphalt"}, "nodes": [1, 2]},
        {"id": 101, "tags": {"highway": "track"}, "nodes": [2, 3]},  # surfaceタグ無し
    ]
    nodes = {1: (35.700, 139.700), 2: (35.701, 139.701), 3: (35.702, 139.702)}
    overpass_client = FakeOverpassClient(result=(ways, nodes))
    service = GraphService(overpass_client, http_client=None)

    result = await service.build_graph_with_surface_tags_for_bbox(BBOX)

    assert result is not None
    graph, surface_by_way_id = result
    assert len(graph.nodes) == 3
    assert surface_by_way_id == {100: "asphalt", 101: None}
    assert overpass_client.call_count == 1  # Overpassへの問い合わせは1回だけ


async def test_build_graph_with_surface_tags_returns_none_on_overpass_failure():
    overpass_client = FakeOverpassClient(result=None)
    service = GraphService(overpass_client, http_client=None)

    result = await service.build_graph_with_surface_tags_for_bbox(BBOX)

    assert result is None


async def test_without_repository_get_or_build_always_fetches_from_overpass():
    ways = [{"id": 100, "tags": {"highway": "residential", "surface": "asphalt"}, "nodes": [1, 2]}]
    nodes = {1: (35.700, 139.700), 2: (35.701, 139.701)}
    overpass_client = FakeOverpassClient(result=(ways, nodes))
    service = GraphService(overpass_client, http_client=None)  # repository未指定

    await service.get_or_build_graph_with_attributes(BBOX)
    await service.get_or_build_graph_with_attributes(BBOX)

    assert overpass_client.call_count == 2  # キャッシュされないため毎回Overpassへ


async def test_with_repository_cache_miss_fetches_and_persists():
    ways = [{"id": 100, "tags": {"highway": "residential", "surface": "asphalt"}, "nodes": [1, 2]}]
    nodes = {1: (35.700, 139.700), 2: (35.701, 139.701)}
    overpass_client = FakeOverpassClient(result=(ways, nodes))
    repository = FakeRoadGraphRepository()
    service = GraphService(overpass_client, http_client=None, repository=repository)

    result = await service.get_or_build_graph_with_attributes(BBOX)

    assert result is not None
    graph, surface_attributes = result
    assert len(graph.edges) == 2  # 双方向
    assert all(a.surface_type == "asphalt" for a in surface_attributes.values())
    assert overpass_client.call_count == 1
    assert repository.save_raw_ways_call_count == 1
    assert repository.save_graph_call_count == 1
    assert len(repository.edges) == 2
    assert len(repository.surface_attributes) == 2


async def test_with_repository_cache_hit_skips_overpass():
    ways = [{"id": 100, "tags": {"highway": "residential", "surface": "asphalt"}, "nodes": [1, 2]}]
    nodes = {1: (35.700, 139.700), 2: (35.701, 139.701)}
    overpass_client = FakeOverpassClient(result=(ways, nodes))
    repository = FakeRoadGraphRepository()
    service = GraphService(overpass_client, http_client=None, repository=repository)

    first = await service.get_or_build_graph_with_attributes(BBOX)
    second = await service.get_or_build_graph_with_attributes(BBOX)

    assert overpass_client.call_count == 1  # 2回目はキャッシュヒットでOverpassに問い合わせない
    assert set(first[0].edges.keys()) == set(second[0].edges.keys())
    assert first[1].keys() == second[1].keys()


async def test_with_repository_cache_miss_when_different_tile():
    ways = [{"id": 100, "tags": {"highway": "residential", "surface": "asphalt"}, "nodes": [1, 2]}]
    nodes = {1: (35.700, 139.700), 2: (35.701, 139.701)}
    overpass_client = FakeOverpassClient(result=(ways, nodes))
    repository = FakeRoadGraphRepository()
    service = GraphService(overpass_client, http_client=None, repository=repository)

    await service.get_or_build_graph_with_attributes(BBOX)
    await service.get_or_build_graph_with_attributes(FAR_BBOX)

    # 別タイルに属するbboxなのでどちらも未取得タイルとしてOverpassへ問い合わせが発生する
    assert overpass_client.call_count == 2
    assert repository.cached_tiles == {(ROAD_GRAPH_TILE_ZOOM, *BBOX_TILE), (ROAD_GRAPH_TILE_ZOOM, *FAR_BBOX_TILE)}


async def test_get_or_build_graph_returns_none_on_overpass_failure_with_repository():
    overpass_client = FakeOverpassClient(result=None)
    repository = FakeRoadGraphRepository()
    service = GraphService(overpass_client, http_client=None, repository=repository)

    result = await service.get_or_build_graph_with_attributes(BBOX)

    assert result is None
    # Overpass取得に失敗した場合はタイルをキャッシュ済みとしてマークしない
    # （次回のリクエストで再取得を試みられるようにするため）
    assert repository.cached_tiles == set()


async def test_with_repository_legitimately_empty_area_returns_empty_graph_not_none():
    # Overpassへの問い合わせ自体は成功するが、道路が1本も無い地域（海・公園等）を模す。
    overpass_client = FakeOverpassClient(result=([], {}))
    repository = FakeRoadGraphRepository()
    service = GraphService(overpass_client, http_client=None, repository=repository)

    first = await service.get_or_build_graph_with_attributes(BBOX)

    assert first is not None  # 取得失敗ではなく「道路が無いことを確認できた」なのでNoneにしない
    graph, surface_attributes = first
    assert graph.edges == {}
    assert surface_attributes == {}
    assert repository.cached_tiles == {(ROAD_GRAPH_TILE_ZOOM, *BBOX_TILE)}

    # タイルはキャッシュ済みなので、2回目はOverpassへ再問い合わせしない
    second = await service.get_or_build_graph_with_attributes(BBOX)

    assert overpass_client.call_count == 1
    assert second is not None
    assert second[0].edges == {}


async def test_with_repository_bbox_spanning_two_tiles_fetches_both_and_merges():
    # TWO_TILE_BBOX(緯度35.693-35.729, 経度139.702-139.790)の範囲内に収まる座標にする。
    ways = [{"id": 100, "tags": {"highway": "residential", "surface": "asphalt"}, "nodes": [1, 2]}]
    nodes = {1: (35.710, 139.750), 2: (35.711, 139.751)}
    overpass_client = FakeOverpassClient(result=(ways, nodes))
    repository = FakeRoadGraphRepository()
    service = GraphService(overpass_client, http_client=None, repository=repository)

    result = await service.get_or_build_graph_with_attributes(TWO_TILE_BBOX)

    assert result is not None
    # 2タイル分、それぞれ1回ずつOverpassへ問い合わせる
    assert overpass_client.call_count == 2
    assert repository.cached_tiles == {(ROAD_GRAPH_TILE_ZOOM, 3637, 1612), (ROAD_GRAPH_TILE_ZOOM, 3638, 1612)}


async def test_with_repository_bbox_spanning_two_tiles_only_fetches_uncached_tile():
    ways = [{"id": 100, "tags": {"highway": "residential", "surface": "asphalt"}, "nodes": [1, 2]}]
    nodes = {1: (35.710, 139.750), 2: (35.711, 139.751)}
    overpass_client = FakeOverpassClient(result=(ways, nodes))
    repository = FakeRoadGraphRepository()
    service = GraphService(overpass_client, http_client=None, repository=repository)

    # 片方のタイル(3637, 1612)だけ先に取得しておく（BBOXは(3637, 1612)にちょうど収まる）
    await service.get_or_build_graph_with_attributes(BBOX)
    assert overpass_client.call_count == 1

    # 2タイルにまたがるリクエストでは、未取得の(3638, 1612)分だけ追加でOverpassへ問い合わせる
    await service.get_or_build_graph_with_attributes(TWO_TILE_BBOX)

    assert overpass_client.call_count == 2


async def test_with_repository_one_tile_fetch_failure_returns_none_but_saves_the_other_tile():
    ways = [{"id": 100, "tags": {"highway": "residential", "surface": "asphalt"}, "nodes": [1, 2]}]
    nodes = {1: (35.710, 139.750), 2: (35.711, 139.751)}
    tile_order = tiles_covering_bbox(TWO_TILE_BBOX, ROAD_GRAPH_TILE_ZOOM)
    assert len(tile_order) == 2
    # 1タイル目は取得失敗、2タイル目は成功というシナリオ
    overpass_client = FakeOverpassClient(results_by_call=[None, (ways, nodes)])
    repository = FakeRoadGraphRepository()
    service = GraphService(overpass_client, http_client=None, repository=repository)

    result = await service.get_or_build_graph_with_attributes(TWO_TILE_BBOX)

    failed_tile, succeeded_tile = tile_order[0], tile_order[1]
    assert (ROAD_GRAPH_TILE_ZOOM, *failed_tile) not in repository.cached_tiles
    assert (ROAD_GRAPH_TILE_ZOOM, *succeeded_tile) in repository.cached_tiles
    # 一部タイルでも取得に失敗すると、要求bboxを正確にカバーできた保証が無いため
    # 全体としてNoneを返す（部分的なデータを「完全な結果」として誤って返さないため）。
    assert result is None

    # ただし成功したタイルの分は保存済みなので、再試行時はそのタイルを再取得しない。
    overpass_client_2 = FakeOverpassClient(results_by_call=[(ways, nodes)])
    service_2 = GraphService(overpass_client_2, http_client=None, repository=repository)
    result_2 = await service_2.get_or_build_graph_with_attributes(TWO_TILE_BBOX)

    assert overpass_client_2.call_count == 1  # 失敗した1タイル分だけ再取得
    assert result_2 is not None


async def test_way_split_is_consistent_regardless_of_which_tile_reveals_the_shared_node():
    """タイル境界依存の交差点分割不一致問題（docs/architecture.md参照）の回帰テスト。

    Way W(200)がタイルA/Bの境界をまたぎ、タイルA側のノード11で側道B(201)と交差点を
    共有する。BはタイルAの範囲にのみ存在するため、タイルB単体を見るとBは見えない。
    生データの分離（save_raw_ways）とclosureベースの分割計算（get_way_specs_with_closure）
    により、タイルAが先に取得済みであれば、タイルBだけを問い合わせた場合でも
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

    # タイルAへの問い合わせ: W・B双方が(少なくとも1ノードが)タイルA内にあるため両方マッチする。
    # Overpassは「マッチしたWayの完全なノード列」を返すため、Wのnode12(タイルB内)も含まれる。
    tile_a_response = (
        [way_w, way_b],
        {10: node10, 11: node11, 12: node12, 13: node13},
    )
    # タイルBへの問い合わせ: node12を持つWのみマッチする。Bはどのノードもタイル内に無いため
    # マッチしない（Overpassのbboxフィルタはノード単位）。
    tile_b_response = (
        [way_w],
        {10: node10, 11: node11, 12: node12},
    )

    # ケース1: タイルAを先に処理（WとBを同時に見て、node11が交差点だと正しく認識できる）
    repository_a_first = FakeRoadGraphRepository()
    service_a_first = GraphService(
        FakeOverpassClient(results_by_call=[tile_a_response]), http_client=None, repository=repository_a_first
    )
    await service_a_first.get_or_build_graph_with_attributes(tile_a_query_bbox)
    w_edges_from_tile_a = {eid: e for eid, e in repository_a_first.edges.items() if e.osm_way_id == 200}

    # ケース2: タイルAを先に取得済みにした上で、タイルBだけを新たに問い合わせる
    # （Bのraw dataは既にDBにあるが、タイルBの応答には含まれない = 従来の実装が壊れていた状況）。
    repository_b_after_a = FakeRoadGraphRepository()
    service_b_after_a = GraphService(
        FakeOverpassClient(results_by_call=[tile_a_response]), http_client=None, repository=repository_b_after_a
    )
    await service_b_after_a.get_or_build_graph_with_attributes(tile_a_query_bbox)

    service_b_only = GraphService(
        FakeOverpassClient(results_by_call=[tile_b_response]), http_client=None, repository=repository_b_after_a
    )
    await service_b_only.get_or_build_graph_with_attributes(tile_b_query_bbox)
    w_edges_from_tile_b_after_a = {eid: e for eid, e in repository_b_after_a.edges.items() if e.osm_way_id == 200}

    # どちらの経路でも、Wはnode11で2区間（10-11, 11-12）×双方向=4Edgeに分割されるはず
    # （node11が1区間の途中に埋もれた1本のEdgeにはならない）。
    assert len(w_edges_from_tile_a) == 4
    assert len(w_edges_from_tile_b_after_a) == 4
    assert {e.distance_m for e in w_edges_from_tile_a.values()} == {
        e.distance_m for e in w_edges_from_tile_b_after_a.values()
    }
