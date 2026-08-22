import pytest

from app.domain.route import Coordinates
from app.infrastructure import elevation_client, tile_cache
from app.infrastructure.elevation_client import DEM_TILE_SIZE, ElevationClient


@pytest.fixture(autouse=True)
def use_temp_tile_cache(tmp_path, monkeypatch):
    # 改善計画T10: 標高キャッシュはtile_cache（ファイル）＋プロセス内グリッドキャッシュの
    # 2段構成へ変わったため、両方をテストごとに隔離・クリアする
    # （_tile_grid_cacheはモジュールグローバルのため、前のテストの値が漏れないよう明示的に
    # クリアする。旧SQLite版のuse_temp_dbフィクスチャと同じ役割）。
    monkeypatch.setattr(tile_cache, "CACHE_DIR", tmp_path)
    elevation_client._tile_grid_cache.clear()
    yield
    elevation_client._tile_grid_cache.clear()


def _flat_tile_text(elevation: float) -> str:
    """全画素が同じ標高値のDEMタイル本文（テスト用の単純化。実タイルは256行×256列の
    カンマ区切り、単位m）を組み立てる。"""
    row = ",".join(f"{elevation:.2f}" for _ in range(DEM_TILE_SIZE))
    return "\n".join(row for _ in range(DEM_TILE_SIZE))


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        pass


class FakeHttpClient:
    def __init__(self, elevation: float | None = 42.0, status_code: int = 200):
        self.call_count = 0
        self._elevation = elevation
        self._status_code = status_code

    async def get(self, url, params=None):
        self.call_count += 1
        if self._status_code != 200:
            return FakeResponse("", status_code=self._status_code)
        return FakeResponse(_flat_tile_text(self._elevation))


async def test_get_elevation_reuses_cache_for_point_in_same_tile():
    client = ElevationClient()
    http_client = FakeHttpClient(elevation=42.0)
    point_a = Coordinates(latitude=35.681, longitude=139.767)
    point_b = Coordinates(latitude=35.68101, longitude=139.76701)  # 同じタイル内の近接点

    first = await client.get_elevation(http_client, point_a)
    second = await client.get_elevation(http_client, point_b)

    assert first == pytest.approx(42.0, abs=0.1)
    assert second == pytest.approx(42.0, abs=0.1)
    assert http_client.call_count == 1  # 同じタイルのため2回目は取得しない


async def test_get_elevation_fetches_again_for_distant_point_in_different_tile():
    client = ElevationClient()
    http_client = FakeHttpClient(elevation=5.0)
    point_a = Coordinates(latitude=35.0, longitude=139.0)
    point_b = Coordinates(latitude=36.0, longitude=140.0)

    await client.get_elevation(http_client, point_a)
    await client.get_elevation(http_client, point_b)

    assert http_client.call_count == 2


async def test_get_elevation_persists_via_tile_cache_file_across_new_process_state():
    point = Coordinates(latitude=35.4, longitude=139.4)
    await ElevationClient().get_elevation(FakeHttpClient(elevation=7.0), point)

    # プロセス内グリッドキャッシュ（_tile_grid_cache）をクリアしても、ファイルキャッシュ
    # （tile_cache、プロセス再起動をまたぐ想定の永続層）経由でヒットすることを確認する。
    elevation_client._tile_grid_cache.clear()

    second_http_client = FakeHttpClient(elevation=999.0)
    result = await ElevationClient().get_elevation(second_http_client, point)

    assert result == pytest.approx(7.0, abs=0.1)
    assert second_http_client.call_count == 0


async def test_get_elevation_refresh_bypasses_cache_and_overwrites():
    client = ElevationClient()
    point = Coordinates(latitude=35.6, longitude=139.6)
    await client.get_elevation(FakeHttpClient(elevation=1.0), point)

    http_client = FakeHttpClient(elevation=2.0)
    result = await client.get_elevation(http_client, point, refresh=True)

    assert result == pytest.approx(2.0, abs=0.1)
    assert http_client.call_count == 1
    # 上書き後は通常呼び出しでも新しい値がキャッシュから返る
    assert await client.get_elevation(FakeHttpClient(elevation=999.0), point) == pytest.approx(2.0, abs=0.1)


async def test_get_elevation_returns_none_for_404_tile():
    # GSIのDEMタイルがカバレッジ外（海上・データ未整備地域）で404を返すケース
    # （旧GSI点APIの「守備範囲外は"-----"」に相当）。
    client = ElevationClient()
    http_client = FakeHttpClient(status_code=404)
    point = Coordinates(latitude=25.0, longitude=125.0)

    result = await client.get_elevation(http_client, point)

    assert result is None


async def test_get_elevation_falls_back_through_dem_type_priority():
    # 2026-08-23の再検証で判明した実仕様: "dem"はDEM5A等の統合ではなく別データセットの
    # ため、dem5a/dem5b/dem5cが非対応（404）のタイルでのみ次の優先順位へフォールバック
    # する必要がある（DEM_TYPE_PRIORITY = dem5a→dem5b→dem5c→dem）。
    class TieredHttpClient:
        def __init__(self, available_type: str, elevation: float):
            self.available_type = available_type
            self.elevation = elevation
            self.requested_types: list[str] = []

        async def get(self, url, params=None):
            requested_type = url.split("/xyz/")[1].split("/")[0]
            self.requested_types.append(requested_type)
            if requested_type != self.available_type:
                return FakeResponse("", status_code=404)
            return FakeResponse(_flat_tile_text(self.elevation))

    client = ElevationClient()
    point = Coordinates(latitude=35.681, longitude=139.767)

    http_client = TieredHttpClient(available_type="dem5c", elevation=12.0)
    result = await client.get_elevation(http_client, point)

    assert result == pytest.approx(12.0, abs=0.1)
    assert http_client.requested_types == ["dem5a", "dem5b", "dem5c"]


async def test_get_elevation_returns_none_for_missing_pixel_marker():
    # DEMタイルの欠測画素は"e"（GSI仕様、2026-08-23実タイル取得で確認済み）。
    class AllMissingHttpClient:
        async def get(self, url, params=None):
            text = "\n".join(",".join("e" for _ in range(DEM_TILE_SIZE)) for _ in range(DEM_TILE_SIZE))
            return FakeResponse(text)

    client = ElevationClient()
    point = Coordinates(latitude=35.681, longitude=139.767)

    result = await client.get_elevation(AllMissingHttpClient(), point)

    assert result is None
