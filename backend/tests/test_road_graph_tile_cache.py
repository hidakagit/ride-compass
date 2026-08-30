"""road_graph_tile_cache.py（改善計画T387、road_graph_tilesのRedis cache-aside層）のテスト。

実Redisは使わず、使用するコマンド（mget/set/pipeline）だけを実装したFakeRedisで検証する
（docs/testing.md: 実I/Oを伴わない単体テストの原則）。
"""

import pytest

from app.infrastructure import road_graph_tile_cache


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
    monkeypatch.setattr(road_graph_tile_cache, "get_redis_client_or_none", lambda: fake)
    return fake


async def test_get_cached_subset_empty_tiles_returns_empty_set():
    assert await road_graph_tile_cache.get_cached_subset(12, []) == set()


async def test_mark_then_get_roundtrip():
    await road_graph_tile_cache.mark_fetched(12, [(10, 20), (11, 21)])
    result = await road_graph_tile_cache.get_cached_subset(12, [(10, 20), (11, 21), (99, 99)])
    assert result == {(10, 20), (11, 21)}


async def test_get_cached_subset_fails_open_on_redis_error(monkeypatch):
    monkeypatch.setattr(road_graph_tile_cache, "get_redis_client_or_none", lambda: BrokenRedis())
    result = await road_graph_tile_cache.get_cached_subset(12, [(1, 2)])
    assert result == set()


async def test_mark_fetched_swallows_redis_error(monkeypatch):
    monkeypatch.setattr(road_graph_tile_cache, "get_redis_client_or_none", lambda: BrokenRedis())
    # 例外を送出せず静かに失敗することだけを確認する（PostGIS側の正本には影響しない設計）。
    await road_graph_tile_cache.mark_fetched(12, [(1, 2)])


# --- split鮮度マーカー（改善計画T390） ---


async def test_get_split_fresh_subset_empty_tiles_returns_empty_set():
    assert await road_graph_tile_cache.get_split_fresh_subset(12, []) == set()


async def test_mark_split_fresh_then_get_roundtrip():
    await road_graph_tile_cache.mark_split_fresh(12, [(10, 20), (11, 21)])
    result = await road_graph_tile_cache.get_split_fresh_subset(12, [(10, 20), (11, 21), (99, 99)])
    assert result == {(10, 20), (11, 21)}


async def test_split_fresh_and_fetched_markers_use_independent_key_spaces():
    # 「取得済み」と「split鮮度確認済み」は別種のマーカーのため、片方だけ立てても
    # もう片方には影響しない（同じ(zoom,x,y)でも異なるキー空間を持つことの確認）。
    await road_graph_tile_cache.mark_fetched(12, [(10, 20)])
    assert await road_graph_tile_cache.get_split_fresh_subset(12, [(10, 20)]) == set()

    await road_graph_tile_cache.mark_split_fresh(12, [(10, 20)])
    assert await road_graph_tile_cache.get_cached_subset(12, [(10, 20)]) == {(10, 20)}
    assert await road_graph_tile_cache.get_split_fresh_subset(12, [(10, 20)]) == {(10, 20)}


async def test_invalidate_split_fresh_removes_marker():
    await road_graph_tile_cache.mark_split_fresh(12, [(10, 20), (11, 21)])
    await road_graph_tile_cache.invalidate_split_fresh(12, [(10, 20)])
    result = await road_graph_tile_cache.get_split_fresh_subset(12, [(10, 20), (11, 21)])
    assert result == {(11, 21)}


async def test_invalidate_split_fresh_on_never_marked_tile_is_noop():
    # 初回import（マーカー自体がまだ無い）でも無害であることを確認する。
    await road_graph_tile_cache.invalidate_split_fresh(12, [(1, 2)])


async def test_get_split_fresh_subset_fails_open_on_redis_error(monkeypatch):
    monkeypatch.setattr(road_graph_tile_cache, "get_redis_client_or_none", lambda: BrokenRedis())
    result = await road_graph_tile_cache.get_split_fresh_subset(12, [(1, 2)])
    assert result == set()


async def test_mark_split_fresh_swallows_redis_error(monkeypatch):
    monkeypatch.setattr(road_graph_tile_cache, "get_redis_client_or_none", lambda: BrokenRedis())
    await road_graph_tile_cache.mark_split_fresh(12, [(1, 2)])


async def test_invalidate_split_fresh_swallows_redis_error(monkeypatch):
    monkeypatch.setattr(road_graph_tile_cache, "get_redis_client_or_none", lambda: BrokenRedis())
    await road_graph_tile_cache.invalidate_split_fresh(12, [(1, 2)])
