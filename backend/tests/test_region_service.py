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


class FakeRegionRepository:
    """RoadGraphRepositoryのRegionServiceが使う部分（カバレッジ判定と路面way取得）のフェイク。"""

    def __init__(self, covered: bool = True, ways=(), error: Exception | None = None):
        self._covered = covered
        self._ways = list(ways)
        self._error = error
        self.is_tile_cached_calls: list[tuple[int, int, int]] = []
        self.get_ways_call_count = 0

    async def is_tile_cached(self, zoom, x, y):
        if self._error is not None:
            raise self._error
        self.is_tile_cached_calls.append((zoom, x, y))
        return self._covered

    async def get_road_surface_ways_in_bbox(self, bbox):
        self.get_ways_call_count += 1
        return self._ways


POSTGIS_WAYS = [([[35.755, 139.735], [35.756, 139.736]], "asphalt")]


async def test_covered_tile_is_served_from_postgis_without_overpass():
    overpass_client = FakeOverpassClient(ways=[])
    repository = FakeRegionRepository(covered=True, ways=POSTGIS_WAYS)
    service = RegionService(overpass_client, http_client=None, repository=repository)

    tile_bytes = await service.get_road_surface_tile(Z, X, Y)

    assert isinstance(tile_bytes, bytes) and len(tile_bytes) > 0
    assert overpass_client.call_count == 0
    assert repository.get_ways_call_count == 1
    # カバレッジ判定はz12の祖先タイル（z14の x,y を2段丸めた値）で行う
    assert repository.is_tile_cached_calls == [(12, X >> 2, Y >> 2)]
    # PostGIS由来のタイルもファイルキャッシュへ保存される（2回目はDBへも行かない）
    await service.get_road_surface_tile(Z, X, Y)
    assert repository.get_ways_call_count == 1


async def test_uncovered_tile_falls_back_to_overpass_when_enabled():
    ways_data = [{"tags": {"surface": "asphalt"}, "coordinates": [[35.755, 139.735], [35.756, 139.736]]}]
    overpass_client = FakeOverpassClient(ways=ways_data)
    repository = FakeRegionRepository(covered=False)
    service = RegionService(overpass_client, http_client=None, repository=repository)

    tile_bytes = await service.get_road_surface_tile(Z, X, Y)

    assert isinstance(tile_bytes, bytes) and len(tile_bytes) > 0
    assert overpass_client.call_count == 1
    assert repository.get_ways_call_count == 0  # カバレッジ外ではway取得まで行かない


async def test_uncovered_tile_returns_empty_without_overpass_when_fallback_disabled():
    overpass_client = FakeOverpassClient(ways=[{"tags": {}, "coordinates": [[35.755, 139.735], [35.756, 139.736]]}])
    repository = FakeRegionRepository(covered=False)
    service = RegionService(
        overpass_client, http_client=None, repository=repository, overpass_fallback_enabled=False
    )

    tile_bytes = await service.get_road_surface_tile(Z, X, Y)

    assert isinstance(tile_bytes, bytes)
    assert overpass_client.call_count == 0
    # 空タイルはキャッシュされない（後からPBF取込された際に再生成できるようにする）ため、
    # 次のリクエストでも再度カバレッジ判定が走る
    await service.get_road_surface_tile(Z, X, Y)
    assert len(repository.is_tile_cached_calls) == 2
    assert overpass_client.call_count == 0


async def test_postgis_error_falls_back_to_overpass():
    ways_data = [{"tags": {"surface": "asphalt"}, "coordinates": [[35.755, 139.735], [35.756, 139.736]]}]
    overpass_client = FakeOverpassClient(ways=ways_data)
    repository = FakeRegionRepository(covered=True, ways=POSTGIS_WAYS, error=RuntimeError("db down"))
    service = RegionService(overpass_client, http_client=None, repository=repository)

    tile_bytes = await service.get_road_surface_tile(Z, X, Y)

    assert isinstance(tile_bytes, bytes) and len(tile_bytes) > 0
    assert overpass_client.call_count == 1  # DB障害時はOverpassへフォールバックして機能を維持する


async def test_encode_failure_returns_empty_tile_instead_of_raising(monkeypatch):
    """MVTエンコードが失敗（密集タイル・同時実行下でのメモリ圧迫等を想定）しても、
    素の例外をraiseせず空タイルへ安全に劣化すること（実機で素の500が返っていた不具合の回帰防止）。
    """
    overpass_client = FakeOverpassClient(ways=[{"tags": {}, "coordinates": [[35.755, 139.735], [35.756, 139.736]]}])
    service = RegionService(overpass_client, http_client=None)

    import app.services.region_service as region_service_module

    call_count = 0
    real_encode = region_service_module.encode_road_surface_tile

    def flaky_encode(z, x, y, ways):
        nonlocal call_count
        call_count += 1
        if ways:  # 実データを含む1回目の呼び出しだけ失敗させる
            raise ValueError("boom")
        return real_encode(z, x, y, ways)

    monkeypatch.setattr(region_service_module, "encode_road_surface_tile", flaky_encode)

    tile_bytes = await service.get_road_surface_tile(Z, X, Y)

    assert isinstance(tile_bytes, bytes)
    assert call_count == 2  # 失敗後、空wayで再度エンコードして復旧する
