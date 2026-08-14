import pytest

from app.infrastructure import tile_cache
from app.services.region_service import RegionService


@pytest.fixture(autouse=True)
def use_temp_tile_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(tile_cache, "CACHE_DIR", tmp_path / "tile_cache")
    yield


class FakeOverpassClient:
    def __init__(self, ways=()):
        self.call_count = 0
        self._ways = list(ways) if ways is not None else None

    async def get_roads(self, http_client, bbox):
        self.call_count += 1
        return self._ways


Z, X, Y = 14, 14551, 6447


async def test_get_road_surface_tile_returns_mvt_bytes():
    ways_data = [{"tags": {"surface": "asphalt"}, "coordinates": [[35.755, 139.735], [35.756, 139.736]]}]
    overpass_client = FakeOverpassClient(ways=ways_data)
    service = RegionService(overpass_client, http_client=None)

    tile_bytes = await service.get_road_surface_tile(Z, X, Y)

    assert isinstance(tile_bytes, bytes)
    assert len(tile_bytes) > 0
    assert overpass_client.call_count == 1


async def test_get_road_surface_tile_reuses_cache_on_second_call():
    overpass_client = FakeOverpassClient(ways=[{"tags": {}, "coordinates": [[35.755, 139.735], [35.756, 139.736]]}])
    service = RegionService(overpass_client, http_client=None)

    first = await service.get_road_surface_tile(Z, X, Y)
    second = await service.get_road_surface_tile(Z, X, Y)

    assert overpass_client.call_count == 1  # 2回目はキャッシュヒットで問い合わせなし
    assert first == second


async def test_get_road_surface_tile_skips_caching_on_fetch_failure():
    overpass_client = FakeOverpassClient(ways=None)
    service = RegionService(overpass_client, http_client=None)

    await service.get_road_surface_tile(Z, X, Y)

    # 失敗時はキャッシュに保存しないため、次回も再取得を試みる
    await service.get_road_surface_tile(Z, X, Y)
    assert overpass_client.call_count == 2
