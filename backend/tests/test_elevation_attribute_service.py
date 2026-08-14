import asyncio

from app.domain.graph import DirectedEdge, Node, RoadGraph
from app.services.elevation_attribute_service import ElevationAttributeService


class FakeElevationClient:
    def __init__(self, elevations_by_point: dict[tuple[float, float], float | None]):
        self._elevations_by_point = elevations_by_point
        self.call_count = 0

    async def get_elevation(self, client, point, refresh=False):
        self.call_count += 1
        return self._elevations_by_point.get((point.latitude, point.longitude))


def _make_graph(*edges: DirectedEdge) -> RoadGraph:
    node = Node(node_id="node-1", latitude=35.7, longitude=139.7)
    return RoadGraph(graph_version="v1", nodes={"node-1": node}, edges={e.edge_id: e for e in edges})


async def test_get_attributes_for_graph_computes_stats_per_edge():
    edge = DirectedEdge(
        edge_id="edge-1",
        from_node_id="node-1",
        to_node_id="node-1",
        geometry=[[35.700, 139.700], [35.701, 139.700]],
        distance_m=100.0,
    )
    graph = _make_graph(edge)
    client = FakeElevationClient({(35.700, 139.700): 10.0, (35.701, 139.700): 20.0})
    service = ElevationAttributeService(client, http_client=None)

    attributes = await service.get_attributes_for_graph(graph)

    assert set(attributes.keys()) == {"edge-1"}
    attr = attributes["edge-1"]
    assert attr.start_elevation_m == 10.0
    assert attr.end_elevation_m == 20.0
    assert attr.elevation_gain_m == 10.0
    assert attr.data_source == "gsi-dem"
    assert client.call_count == 2


async def test_get_attributes_for_graph_handles_multiple_edges_independently():
    edge1 = DirectedEdge(
        edge_id="edge-1",
        from_node_id="node-1",
        to_node_id="node-1",
        geometry=[[35.700, 139.700], [35.701, 139.700]],
        distance_m=100.0,
    )
    edge2 = DirectedEdge(
        edge_id="edge-2",
        from_node_id="node-1",
        to_node_id="node-1",
        geometry=[[35.701, 139.700], [35.702, 139.700]],
        distance_m=100.0,
    )
    graph = _make_graph(edge1, edge2)
    client = FakeElevationClient(
        {(35.700, 139.700): 10.0, (35.701, 139.700): 20.0, (35.702, 139.700): 15.0}
    )
    service = ElevationAttributeService(client, http_client=None)

    attributes = await service.get_attributes_for_graph(graph)

    assert set(attributes.keys()) == {"edge-1", "edge-2"}
    assert attributes["edge-1"].elevation_gain_m == 10.0
    assert attributes["edge-2"].elevation_loss_m == 5.0


async def test_get_attributes_for_graph_missing_elevation_yields_none_stats():
    edge = DirectedEdge(
        edge_id="edge-1",
        from_node_id="node-1",
        to_node_id="node-1",
        geometry=[[35.700, 139.700], [35.701, 139.700]],
        distance_m=100.0,
    )
    graph = _make_graph(edge)
    client = FakeElevationClient({})  # 全地点で取得失敗
    service = ElevationAttributeService(client, http_client=None)

    attributes = await service.get_attributes_for_graph(graph)

    assert attributes["edge-1"].elevation_gain_m is None
    assert attributes["edge-1"].start_elevation_m is None


async def test_get_attributes_for_graph_empty_graph_returns_empty_dict():
    graph = RoadGraph(graph_version="v1", nodes={}, edges={})
    client = FakeElevationClient({})
    service = ElevationAttributeService(client, http_client=None)

    attributes = await service.get_attributes_for_graph(graph)

    assert attributes == {}


class FakeElevationAttributeRepository:
    """road_graph_repository.RoadGraphRepositoryの標高属性まわりのみを模した簡易版
    （実PostGISは未検証、GraphServiceのFakeRoadGraphRepositoryと同じ位置づけ）。"""

    def __init__(self):
        self.attributes = {}
        self.save_call_count = 0
        self.get_call_count = 0

    async def get_elevation_attributes(self, edge_ids):
        self.get_call_count += 1
        return {eid: self.attributes[eid] for eid in edge_ids if eid in self.attributes}

    async def save_elevation_attributes(self, attributes):
        self.save_call_count += 1
        for attribute in attributes:
            self.attributes[attribute.edge_id] = attribute

    async def commit(self) -> None:
        # サービス層が保存のまとまりごとにcommitを呼ぶ規約（T6）。Fakeはno-op。
        pass


async def test_without_repository_always_calls_elevation_client():
    edge = DirectedEdge(
        edge_id="edge-1", from_node_id="node-1", to_node_id="node-1",
        geometry=[[35.700, 139.700], [35.701, 139.700]], distance_m=100.0,
    )
    graph = _make_graph(edge)
    client = FakeElevationClient({(35.700, 139.700): 10.0, (35.701, 139.700): 20.0})
    service = ElevationAttributeService(client, http_client=None)  # repository未指定

    await service.get_attributes_for_graph(graph)
    await service.get_attributes_for_graph(graph)

    assert client.call_count == 4  # 2点 × 2回、キャッシュされないため毎回問い合わせる


async def test_with_repository_cache_miss_fetches_and_persists():
    edge = DirectedEdge(
        edge_id="edge-1", from_node_id="node-1", to_node_id="node-1",
        geometry=[[35.700, 139.700], [35.701, 139.700]], distance_m=100.0,
    )
    graph = _make_graph(edge)
    client = FakeElevationClient({(35.700, 139.700): 10.0, (35.701, 139.700): 20.0})
    repository = FakeElevationAttributeRepository()
    service = ElevationAttributeService(client, http_client=None, repository=repository)

    attributes = await service.get_attributes_for_graph(graph)

    assert attributes["edge-1"].elevation_gain_m == 10.0
    assert client.call_count == 2
    assert repository.save_call_count == 1
    assert "edge-1" in repository.attributes


class ReentrancyDetectingRepository(FakeElevationAttributeRepository):
    """repositoryへの同時アクセス（再入）を検出するフェイク。

    実体のRoadGraphRepositoryはSQLAlchemyのAsyncSessionを内包しており、複数コルーチン
    から同時に使うとIllegalStateChangeErrorになる（RoadGraphEngine.evaluate_loopsが
    候補ごとにasyncio.gatherで並列に呼ぶ経路で、実PostGIS E2Eにて実際にクラッシュを
    確認した）。このフェイクはget/saveの実行中に別コルーチンが入ってきたら失敗を記録する。
    """

    def __init__(self):
        super().__init__()
        self._in_use = False
        self.concurrent_access_detected = False

    async def _guard(self):
        if self._in_use:
            self.concurrent_access_detected = True
        self._in_use = True
        await asyncio.sleep(0)  # 制御を手放し、並列呼び出しに割り込む機会を与える
        self._in_use = False

    async def get_elevation_attributes(self, edge_ids):
        await self._guard()
        return await super().get_elevation_attributes(edge_ids)

    async def save_elevation_attributes(self, attributes):
        await self._guard()
        await super().save_elevation_attributes(attributes)


async def test_concurrent_calls_serialize_repository_access():
    """8候補並列のevaluate_loopsを模して同時に呼んでも、repositoryアクセスが
    直列化されること（AsyncSessionの同時使用クラッシュの回帰テスト）。"""
    edges = [
        DirectedEdge(
            edge_id=f"edge-{i}", from_node_id="node-1", to_node_id="node-1",
            geometry=[[35.700 + i * 0.001, 139.700], [35.701 + i * 0.001, 139.700]], distance_m=100.0,
        )
        for i in range(4)
    ]
    client = FakeElevationClient({})
    repository = ReentrancyDetectingRepository()
    service = ElevationAttributeService(client, http_client=None, repository=repository)

    await asyncio.gather(*(service.get_attributes_for_graph(_make_graph(edge)) for edge in edges))

    assert not repository.concurrent_access_detected
    assert repository.get_call_count == 4
    assert repository.save_call_count == 4


async def test_with_repository_cache_hit_skips_elevation_client():
    edge = DirectedEdge(
        edge_id="edge-1", from_node_id="node-1", to_node_id="node-1",
        geometry=[[35.700, 139.700], [35.701, 139.700]], distance_m=100.0,
    )
    graph = _make_graph(edge)
    client = FakeElevationClient({(35.700, 139.700): 10.0, (35.701, 139.700): 20.0})
    repository = FakeElevationAttributeRepository()
    service = ElevationAttributeService(client, http_client=None, repository=repository)

    first = await service.get_attributes_for_graph(graph)
    second = await service.get_attributes_for_graph(graph)

    assert client.call_count == 2  # 2回目はキャッシュヒットでGSIに問い合わせない
    assert repository.save_call_count == 1  # 保存も1回だけ
    assert first["edge-1"].elevation_gain_m == second["edge-1"].elevation_gain_m


async def test_with_repository_partial_cache_only_fetches_missing_edges():
    edge1 = DirectedEdge(
        edge_id="edge-1", from_node_id="node-1", to_node_id="node-1",
        geometry=[[35.700, 139.700], [35.701, 139.700]], distance_m=100.0,
    )
    edge2 = DirectedEdge(
        edge_id="edge-2", from_node_id="node-1", to_node_id="node-1",
        geometry=[[35.701, 139.700], [35.702, 139.700]], distance_m=100.0,
    )
    graph = _make_graph(edge1, edge2)
    client = FakeElevationClient(
        {(35.700, 139.700): 10.0, (35.701, 139.700): 20.0, (35.702, 139.700): 15.0}
    )
    repository = FakeElevationAttributeRepository()
    # edge-1は既にキャッシュ済みとして事前投入しておく
    from app.domain.attributes import ElevationAttribute

    repository.attributes["edge-1"] = ElevationAttribute(
        edge_id="edge-1", elevation_gain_m=999.0, data_source="gsi-dem", calculated_at="t"
    )
    service = ElevationAttributeService(client, http_client=None, repository=repository)

    attributes = await service.get_attributes_for_graph(graph)

    assert attributes["edge-1"].elevation_gain_m == 999.0  # キャッシュ値がそのまま使われる
    assert attributes["edge-2"].elevation_loss_m == 5.0  # edge-2は新規計算
    assert client.call_count == 2  # edge-2の2点分のみ問い合わせ（edge-1分は問い合わせない）
