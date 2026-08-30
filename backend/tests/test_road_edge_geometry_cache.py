"""road_edge_geometry_cache.py（改善計画T390、get_edges_with_geometryのRedis
cache-aside層）のテスト。

実Redisは使わず、使用するコマンド（mget/set/delete/pipeline）だけを実装したFakeRedisで
検証する（test_road_graph_tile_cache.pyと同じ方針、docs/testing.md参照）。
"""

import pytest

from app.domain.graph import DirectedEdge
from app.infrastructure import road_edge_geometry_cache


def _edge(edge_id: str, distance_m: float = 10.0) -> DirectedEdge:
    return DirectedEdge(
        edge_id=edge_id,
        from_node_id=f"{edge_id}-from",
        to_node_id=f"{edge_id}-to",
        geometry=[[35.0, 139.0], [35.001, 139.001]],
        distance_m=distance_m,
        osm_way_id=1,
        highway="residential",
        bearing_deg=45.0,
    )


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def mget(self, keys):
        return [self.store.get(key) for key in keys]

    def pipeline(self, transaction=False):
        return FakePipeline(self)

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def delete(self, *keys):
        deleted = 0
        for key in keys:
            if self.store.pop(key, None) is not None:
                deleted += 1
        return deleted


class FakePipeline:
    def __init__(self, redis: FakeRedis):
        self._redis = redis
        self._ops = []

    def set(self, key, value, ex=None):
        self._ops.append((key, value))
        return self

    async def execute(self):
        for key, value in self._ops:
            self._redis.store[key] = value


class BrokenRedis:
    """疎通不能をシミュレートするフェイク（fail-open検証用）。"""

    async def mget(self, keys):
        raise ConnectionError("boom")

    def pipeline(self, transaction=False):
        raise ConnectionError("boom")

    async def delete(self, *keys):
        raise ConnectionError("boom")


@pytest.fixture(autouse=True)
def _reset_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(road_edge_geometry_cache, "get_redis_client_or_none", lambda: fake)
    return fake


async def test_get_cached_edges_empty_ids_returns_empty_dict():
    assert await road_edge_geometry_cache.get_cached_edges([]) == {}


async def test_cache_then_get_roundtrip_preserves_all_fields():
    edge = _edge("way-1-seg0-fwd")
    await road_edge_geometry_cache.cache_edges({edge.edge_id: edge})

    result = await road_edge_geometry_cache.get_cached_edges([edge.edge_id, "unknown-edge"])

    assert set(result.keys()) == {edge.edge_id}
    assert result[edge.edge_id] == edge


async def test_get_cached_edges_only_returns_hits():
    edge = _edge("way-1-seg0-fwd")
    await road_edge_geometry_cache.cache_edges({edge.edge_id: edge})

    result = await road_edge_geometry_cache.get_cached_edges(["way-1-seg0-fwd", "way-2-seg0-fwd"])

    assert list(result.keys()) == ["way-1-seg0-fwd"]


async def test_invalidate_edges_removes_cached_entry():
    edge = _edge("way-1-seg0-fwd")
    await road_edge_geometry_cache.cache_edges({edge.edge_id: edge})

    await road_edge_geometry_cache.invalidate_edges([edge.edge_id])

    assert await road_edge_geometry_cache.get_cached_edges([edge.edge_id]) == {}


async def test_invalidate_edges_on_never_cached_edge_is_noop():
    # save_graphは再split後の新edge_ids全件を無条件で無効化するため、
    # 一度もキャッシュされていないedge_idが混ざっても安全であること。
    await road_edge_geometry_cache.invalidate_edges(["never-cached"])


async def test_get_cached_edges_fails_open_on_redis_error(monkeypatch):
    monkeypatch.setattr(road_edge_geometry_cache, "get_redis_client_or_none", lambda: BrokenRedis())
    result = await road_edge_geometry_cache.get_cached_edges(["way-1-seg0-fwd"])
    assert result == {}


async def test_cache_edges_swallows_redis_error(monkeypatch):
    monkeypatch.setattr(road_edge_geometry_cache, "get_redis_client_or_none", lambda: BrokenRedis())
    edge = _edge("way-1-seg0-fwd")
    await road_edge_geometry_cache.cache_edges({edge.edge_id: edge})


async def test_invalidate_edges_swallows_redis_error(monkeypatch):
    monkeypatch.setattr(road_edge_geometry_cache, "get_redis_client_or_none", lambda: BrokenRedis())
    await road_edge_geometry_cache.invalidate_edges(["way-1-seg0-fwd"])


async def test_get_cached_edges_ignores_malformed_cached_value():
    # スキーマ変更等で旧形式の値が残っていた場合はパース失敗を握りつぶし、
    # 呼び出し元がPostGISへフォールバックできるようにする。
    client = road_edge_geometry_cache.get_redis_client_or_none()
    await client.set(road_edge_geometry_cache._key("way-1-seg0-fwd"), "not-json", ex=60)

    result = await road_edge_geometry_cache.get_cached_edges(["way-1-seg0-fwd"])

    assert result == {}
