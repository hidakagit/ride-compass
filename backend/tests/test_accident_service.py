import pytest

from app.infrastructure import tile_cache
from app.infrastructure.vector_tile import encode_empty_accident_tile
from app.services import derived_data_revision_service
from app.services.accident_service import AccidentService, _tile_cache_path


@pytest.fixture(autouse=True)
def use_temp_tile_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(tile_cache, "CACHE_DIR", tmp_path / "tile_cache")
    yield


@pytest.fixture
def known_derived_data_revision(monkeypatch):
    """世代が読めている状態を既定にする。

    読めていないあいだタイルはディスクへ残らないため、キャッシュの挙動を見るテストは
    この前提を明示する必要がある。
    """
    monkeypatch.setattr(derived_data_revision_service, "current_revision", lambda: 1)
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


async def test_tile_is_served_from_postgis_and_cached(known_derived_data_revision):
    repository = FakeAccidentRepository(tile=b"fake-accident-tile")
    service = AccidentService(repository=repository)

    tile_bytes = (await service.get_accident_tile(Z, X, Y)).content

    assert tile_bytes == b"fake-accident-tile"
    await service.get_accident_tile(Z, X, Y)
    # 2回目はファイルキャッシュから返るためDBへは1回しか行かない
    assert len(repository.mvt_calls) == 1


async def test_empty_tile_from_postgis_is_also_cached(known_derived_data_revision):
    """対象0件のタイルもキャッシュする。「データが無いことを確認済み」だからで、
    取れなかった場合とは区別される。"""
    repository = FakeAccidentRepository(tile=b"")
    service = AccidentService(repository=repository)

    tile_bytes = (await service.get_accident_tile(Z, X, Y)).content

    assert tile_bytes == b""
    await service.get_accident_tile(Z, X, Y)
    assert len(repository.mvt_calls) == 1


async def test_postgis_error_returns_empty_mvt_that_browsers_must_not_keep():
    repository = FakeAccidentRepository(error=ConnectionRefusedError("db down"))
    service = AccidentService(repository=repository)

    response = await service.get_accident_tile(Z, X, Y)

    assert response.content == encode_empty_accident_tile()
    # 一時的な失敗のため、ブラウザへ長期キャッシュさせない（回復後に空白が残る）
    assert response.cacheable is False
    # ディスクにも残さない（次のリクエストで作り直せるように）
    assert tile_cache.get(_tile_cache_path(Z, X, Y)) is None


async def test_no_repository_returns_empty_mvt():
    # road_graph_use_repository無効（DBなし構成）ではrepository自体が注入されない
    service = AccidentService()

    response = await service.get_accident_tile(Z, X, Y)

    assert response.content == encode_empty_accident_tile()
