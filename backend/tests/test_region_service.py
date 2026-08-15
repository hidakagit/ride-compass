import pytest

from app.infrastructure import tile_cache
from app.services.region_service import RegionService


@pytest.fixture(autouse=True)
def use_temp_tile_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(tile_cache, "CACHE_DIR", tmp_path / "tile_cache")
    yield


Z, X, Y = 14, 14551, 6447


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


async def test_covered_tile_is_served_from_postgis():
    repository = FakeRegionRepository(covered=True)
    service = RegionService(repository=repository)

    tile_bytes = await service.get_road_surface_tile(Z, X, Y)

    # PostGIS（ST_AsMVT）が生成したバイト列がそのまま返る（Python側で再エンコードしない）
    assert tile_bytes == b"fake-mvt-tile"
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
    service = RegionService(repository=repository)

    tile_bytes = await service.get_road_surface_tile(Z, X, Y)

    assert tile_bytes == b""
    await service.get_road_surface_tile(Z, X, Y)
    assert len(repository.mvt_calls) == 1


async def test_uncovered_tile_returns_empty_mvt_without_caching():
    repository = FakeRegionRepository(covered=False)
    service = RegionService(repository=repository)

    tile_bytes = await service.get_road_surface_tile(Z, X, Y)

    assert isinstance(tile_bytes, bytes)
    # 空タイルはキャッシュされない（後からPBF取込された際に再生成できるようにする）ため、
    # 次のリクエストでも再度カバレッジ判定（＝MVTクエリ）が走る
    await service.get_road_surface_tile(Z, X, Y)
    assert len(repository.mvt_calls) == 2


async def test_postgis_error_returns_empty_mvt():
    repository = FakeRegionRepository(covered=True, error=RuntimeError("db down"))
    service = RegionService(repository=repository)

    tile_bytes = await service.get_road_surface_tile(Z, X, Y)

    # DB障害時も空タイルへ安全側に倒す（Overpassフォールバックは改善計画T22で撤去済み）
    assert isinstance(tile_bytes, bytes)


async def test_no_repository_returns_empty_mvt():
    # road_graph_use_repository無効（DBなし構成）ではrepository自体が注入されず、
    # 路面レイヤーは常に空タイルになる
    service = RegionService()

    tile_bytes = await service.get_road_surface_tile(Z, X, Y)

    assert isinstance(tile_bytes, bytes)
