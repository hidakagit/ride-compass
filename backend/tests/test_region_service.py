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
    """RoadGraphRepositoryのRegionServiceが使う部分（カバレッジ判定込みMVT生成）のフェイク。"""

    def __init__(self, covered: bool = True, tile: bytes = b"fake-mvt-tile", error: Exception | None = None):
        self._covered = covered
        self._tile = tile
        self._error = error
        self.mvt_calls: list[tuple[int, int, int, tuple[int, int, int]]] = []

    async def get_road_surface_tile_mvt(self, z, x, y, bbox, coverage_tile):
        if self._error is not None:
            raise self._error
        self.mvt_calls.append((z, x, y, coverage_tile))
        if not self._covered:
            return None  # カバレッジ外（実装と同じくNoneで表現）
        return self._tile


async def test_covered_tile_is_served_from_postgis_without_overpass():
    overpass_client = FakeOverpassClient(ways=[])
    repository = FakeRegionRepository(covered=True)
    service = RegionService(overpass_client, http_client=None, repository=repository)

    tile_bytes = await service.get_road_surface_tile(Z, X, Y)

    # PostGIS（ST_AsMVT）が生成したバイト列がそのまま返る（Python側で再エンコードしない）
    assert tile_bytes == b"fake-mvt-tile"
    assert overpass_client.call_count == 0
    # カバレッジ判定はz12の祖先タイル（z14の x,y を2段丸めた値）で行う（MVT生成と同一クエリ）
    assert repository.mvt_calls == [(Z, X, Y, (12, X >> 2, Y >> 2))]
    # PostGIS由来のタイルもファイルキャッシュへ保存される（2回目はDBへも行かない）
    await service.get_road_surface_tile(Z, X, Y)
    assert len(repository.mvt_calls) == 1


async def test_covered_tile_with_no_roads_caches_empty_mvt():
    """カバレッジ内で道路0本（ST_AsMVTがNULL→空バイト列）のタイルもキャッシュされ、
    2回目以降DBへ行かないこと（「データが無いことを確認済み」はキャッシュしてよい。
    カバレッジ外の空タイルをキャッシュしないのとは区別する）。"""
    repository = FakeRegionRepository(covered=True, tile=b"")
    service = RegionService(FakeOverpassClient(ways=[]), http_client=None, repository=repository)

    tile_bytes = await service.get_road_surface_tile(Z, X, Y)

    assert tile_bytes == b""
    await service.get_road_surface_tile(Z, X, Y)
    assert len(repository.mvt_calls) == 1


async def test_uncovered_tile_falls_back_to_overpass_when_enabled():
    ways_data = [{"tags": {"surface": "asphalt"}, "coordinates": [[35.755, 139.735], [35.756, 139.736]]}]
    overpass_client = FakeOverpassClient(ways=ways_data)
    repository = FakeRegionRepository(covered=False)
    service = RegionService(overpass_client, http_client=None, repository=repository)

    tile_bytes = await service.get_road_surface_tile(Z, X, Y)

    assert isinstance(tile_bytes, bytes) and len(tile_bytes) > 0
    assert overpass_client.call_count == 1
    # カバレッジ判定はMVT生成と同一クエリ（1往復）。カバレッジ外はNoneが返りフォールバックへ
    assert len(repository.mvt_calls) == 1


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
    # 次のリクエストでも再度カバレッジ判定（＝MVTクエリ）が走る
    await service.get_road_surface_tile(Z, X, Y)
    assert len(repository.mvt_calls) == 2
    assert overpass_client.call_count == 0


async def test_postgis_error_falls_back_to_overpass():
    ways_data = [{"tags": {"surface": "asphalt"}, "coordinates": [[35.755, 139.735], [35.756, 139.736]]}]
    overpass_client = FakeOverpassClient(ways=ways_data)
    repository = FakeRegionRepository(covered=True, error=RuntimeError("db down"))
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
