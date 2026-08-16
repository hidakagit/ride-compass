import asyncio
import time

import pytest

from app.infrastructure import tile_cache
from app.infrastructure.road_graph_repository import RoadGraphRepository
from app.services import region_service as region_service_module
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
        self.poi_mvt_calls: list[tuple[int, int, int, tuple[int, int, int]]] = []

    async def get_road_surface_tile_mvt(self, z, x, y, bbox, coverage_tile):
        if self._error is not None:
            raise self._error
        self.mvt_calls.append((z, x, y, coverage_tile))
        if not self._covered:
            return None  # カバレッジ外（実装と同じくNoneで表現）
        return self._tile

    async def get_poi_tile_mvt(self, z, x, y, bbox, coverage_tile):
        if self._error is not None:
            raise self._error
        self.poi_mvt_calls.append((z, x, y, coverage_tile))
        if not self._covered:
            return None
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


# 改善計画T54: 停止要因POI・交差点密度レイヤー。get_road_surface_tileと同じ_get_tile経由の
# 契約（カバレッジ判定・キャッシュ・エラー処理）を共有するため、代表的なケースのみ確認する
# （全パターンの再検証はget_road_surface_tile側のテストで既に担保済み）。


async def test_poi_tile_covered_is_served_from_postgis_and_cached_independently_of_road_tile():
    repository = FakeRegionRepository(covered=True, tile=b"fake-poi-tile")
    service = RegionService(repository=repository)

    tile_bytes = await service.get_poi_tile(Z, X, Y)

    assert tile_bytes == b"fake-poi-tile"
    assert repository.poi_mvt_calls == [(Z, X, Y, (12, X >> 2, Y >> 2))]
    assert repository.mvt_calls == []  # 路面タイル側のクエリは呼ばれない

    # road_surface/poiは別キャッシュパス・別ファイルキャッシュエントリのため、路面タイルを
    # 先に取得していても互いのキャッシュヒットに影響しない
    await service.get_road_surface_tile(Z, X, Y)
    await service.get_poi_tile(Z, X, Y)
    assert len(repository.poi_mvt_calls) == 1
    assert len(repository.mvt_calls) == 1


async def test_poi_tile_uncovered_returns_empty_mvt_without_caching():
    repository = FakeRegionRepository(covered=False)
    service = RegionService(repository=repository)

    tile_bytes = await service.get_poi_tile(Z, X, Y)

    assert isinstance(tile_bytes, bytes)
    await service.get_poi_tile(Z, X, Y)
    assert len(repository.poi_mvt_calls) == 2


async def test_poi_tile_no_repository_returns_empty_mvt():
    service = RegionService()

    tile_bytes = await service.get_poi_tile(Z, X, Y)

    assert isinstance(tile_bytes, bytes)


# 改善計画T59: ルート生成した地点でしか道路グラフ（road_nodes/road_edges）が構築されず、
# 地図を眺めるだけの利用（ルート生成を経ない）では道路情報・交通ストレス・自転車インフラ・
# 交差点密度レイヤーが永遠に空のままだった問題への対応。カバレッジ内タイルの応答時、
# z12祖先タイル単位でバックグラウンド構築を起動する（_maybe_trigger_graph_build）。


class _FakeRealRoadGraphRepository(RoadGraphRepository):
    """isinstance(repository, RoadGraphRepository)による発火判定をテストするための
    なりすまし。実DBセッションは使わない（__init__をオーバーライドしてsuper().__init__を
    呼ばない。tile_query.get_road_surface_tile_mvt等への委譲も直接オーバーライドで避ける）。"""

    def __init__(self, tile: bytes = b"fake-mvt-tile"):
        self._tile = tile

    async def get_road_surface_tile_mvt(self, z, x, y, bbox, coverage_tile):
        return self._tile

    async def get_poi_tile_mvt(self, z, x, y, bbox, coverage_tile):
        return self._tile


@pytest.fixture(autouse=True)
def _clear_graph_build_state():
    """_building_graph_tiles/_last_build_checkはプロセス内メモリのみのモジュールグローバル
    （region_service.pyのコメント参照、rate_limiter.pyと同じ割り切り）のため、
    テスト間で汚染しないよう毎回クリアする。"""
    region_service_module._building_graph_tiles.clear()
    region_service_module._last_build_check.clear()
    yield
    region_service_module._building_graph_tiles.clear()
    region_service_module._last_build_check.clear()


async def test_covered_tile_with_real_repository_triggers_background_graph_build(monkeypatch):
    """実リポジトリ（isinstance判定）なら、カバレッジ内タイルの応答時にz12祖先タイル分の
    道路グラフ構築がバックグラウンドで起動される。"""
    calls: list[tuple[int, int, int]] = []
    build_started = asyncio.Event()

    async def fake_build(ancestor_tile, checked_at):
        calls.append(ancestor_tile)
        build_started.set()

    monkeypatch.setattr(region_service_module, "_build_graph_for_tile_background", fake_build)

    repository = _FakeRealRoadGraphRepository()
    service = RegionService(repository=repository)

    await service.get_road_surface_tile(Z, X, Y)
    await asyncio.wait_for(build_started.wait(), timeout=1.0)

    assert calls == [(12, X >> 2, Y >> 2)]


async def test_covered_tile_with_fake_repository_does_not_trigger_background_build(monkeypatch):
    """FakeRegionRepositoryはRoadGraphRepositoryを継承しないダックタイピングのため
    isinstance判定に弾かれ、構築トリガーが発火しない（ユニットテストが実DBへ触れないため）。"""
    calls: list[tuple[int, int, int]] = []

    async def fake_build(ancestor_tile, checked_at):
        calls.append(ancestor_tile)

    monkeypatch.setattr(region_service_module, "_build_graph_for_tile_background", fake_build)

    repository = FakeRegionRepository(covered=True)
    service = RegionService(repository=repository)

    await service.get_road_surface_tile(Z, X, Y)
    await asyncio.sleep(0)

    assert calls == []


async def test_graph_build_trigger_dedupes_concurrent_requests_for_same_tile(monkeypatch):
    """同じz12祖先タイルへ路面・POI両方のタイルリクエストが短時間に来ても、構築は1回しか
    起動しない（ビューポート内の多数のz13-15タイルリクエストによる重複起動防止）。"""
    calls: list[tuple[int, int, int]] = []
    release = asyncio.Event()

    async def fake_build(ancestor_tile, checked_at):
        calls.append(ancestor_tile)
        await release.wait()

    monkeypatch.setattr(region_service_module, "_build_graph_for_tile_background", fake_build)

    repository = _FakeRealRoadGraphRepository()
    service = RegionService(repository=repository)

    await service.get_road_surface_tile(Z, X, Y)
    await service.get_poi_tile(Z, X, Y)  # 同じz12祖先を指す別タイル種別からのリクエスト
    await asyncio.sleep(0)

    release.set()
    await asyncio.sleep(0)

    assert calls == [(12, X >> 2, Y >> 2)]


async def test_graph_build_trigger_skips_recently_checked_tile(monkeypatch):
    """直近_GRAPH_CHECK_TTL_SECONDS以内に確認済みのz12タイルは、次のタイルリクエストで
    再チェックしない（既に最新のタイルを眺めるたびに短命DBセッションを開き続けない対策）。"""
    calls: list[tuple[int, int, int]] = []

    async def fake_build(ancestor_tile, checked_at):
        calls.append(ancestor_tile)

    monkeypatch.setattr(region_service_module, "_build_graph_for_tile_background", fake_build)
    ancestor = (12, X >> 2, Y >> 2)
    region_service_module._last_build_check[ancestor] = time.monotonic()

    repository = _FakeRealRoadGraphRepository()
    service = RegionService(repository=repository)

    await service.get_road_surface_tile(Z, X, Y)
    await asyncio.sleep(0)

    assert calls == []
