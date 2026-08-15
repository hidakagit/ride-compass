import pytest

from app.infrastructure import tile_cache
from app.services.accident_service import AccidentService


@pytest.fixture(autouse=True)
def use_temp_tile_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(tile_cache, "CACHE_DIR", tmp_path / "tile_cache")
    yield


Z, X, Y = 14, 14551, 6447


class FakeAccidentRepository:
    """AccidentTileQueryのフェイク（MVT生成、カバレッジ判定は無い）。"""

    def __init__(self, tile: bytes = b"fake-accident-tile", error: Exception | None = None):
        self._tile = tile
        self._error = error
        self.mvt_calls: list[tuple[int, int, int]] = []

    async def get_accident_tile_mvt(self, z, x, y, bbox):
        if self._error is not None:
            raise self._error
        self.mvt_calls.append((z, x, y))
        return self._tile


async def test_tile_is_served_from_postgis_and_cached():
    repository = FakeAccidentRepository(tile=b"fake-accident-tile")
    service = AccidentService(repository=repository)

    tile_bytes = await service.get_accident_tile(Z, X, Y)

    assert tile_bytes == b"fake-accident-tile"
    await service.get_accident_tile(Z, X, Y)
    # 2回目はファイルキャッシュから返るためDBへは1回しか行かない
    assert len(repository.mvt_calls) == 1


async def test_empty_tile_from_postgis_is_also_cached():
    """対象0件（ST_AsMVTがNULL→空バイト列）のタイルもキャッシュされる。road_surfaceの
    「データが無いことを確認済み」タイルと同じ扱い（accident_pointsにカバレッジ外という
    概念が無いため、road_surfaceの「カバレッジ外はキャッシュしない」区別は不要）。"""
    repository = FakeAccidentRepository(tile=b"")
    service = AccidentService(repository=repository)

    tile_bytes = await service.get_accident_tile(Z, X, Y)

    assert tile_bytes == b""
    await service.get_accident_tile(Z, X, Y)
    assert len(repository.mvt_calls) == 1


async def test_postgis_error_returns_empty_mvt():
    repository = FakeAccidentRepository(error=RuntimeError("db down"))
    service = AccidentService(repository=repository)

    tile_bytes = await service.get_accident_tile(Z, X, Y)

    assert isinstance(tile_bytes, bytes)


async def test_no_repository_returns_empty_mvt():
    # road_graph_use_repository無効（DBなし構成）ではrepository自体が注入されない
    service = AccidentService()

    tile_bytes = await service.get_accident_tile(Z, X, Y)

    assert isinstance(tile_bytes, bytes)
