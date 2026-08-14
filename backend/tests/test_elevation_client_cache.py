import pytest

from app.domain.route import Coordinates
from app.infrastructure import cache_db
from app.infrastructure.elevation_client import ElevationClient


@pytest.fixture(autouse=True)
def use_temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cache_db, "DB_PATH", tmp_path / "test_cache.db")
    yield


class FakeResponse:
    def __init__(self, elevation):
        self._elevation = elevation

    def raise_for_status(self):
        pass

    def json(self):
        return {"elevation": self._elevation, "hsrc": "test"}


class FakeHttpClient:
    def __init__(self, elevation: float):
        self.call_count = 0
        self._elevation = elevation

    async def get(self, url, params=None):
        self.call_count += 1
        return FakeResponse(self._elevation)


async def test_get_elevation_reuses_cache_for_exact_same_point():
    client = ElevationClient()
    http_client = FakeHttpClient(elevation=42.0)
    point = Coordinates(latitude=35.111111, longitude=139.222222)

    first = await client.get_elevation(http_client, point)
    second = await client.get_elevation(http_client, point)

    assert first == 42.0
    assert second == 42.0
    assert http_client.call_count == 1


async def test_get_elevation_reuses_cache_for_point_within_rounding_precision():
    client = ElevationClient()
    http_client = FakeHttpClient(elevation=10.0)
    point_a = Coordinates(latitude=35.222211, longitude=139.333311)
    point_b = Coordinates(latitude=35.222212, longitude=139.333312)  # 丸めると同じキャッシュキー

    await client.get_elevation(http_client, point_a)
    await client.get_elevation(http_client, point_b)

    assert http_client.call_count == 1


async def test_get_elevation_fetches_again_for_distant_point():
    client = ElevationClient()
    http_client = FakeHttpClient(elevation=5.0)
    point_a = Coordinates(latitude=35.0, longitude=139.0)
    point_b = Coordinates(latitude=36.0, longitude=140.0)

    await client.get_elevation(http_client, point_a)
    await client.get_elevation(http_client, point_b)

    assert http_client.call_count == 2


async def test_get_elevation_persists_across_new_client_instances():
    point = Coordinates(latitude=35.4, longitude=139.4)
    await ElevationClient().get_elevation(FakeHttpClient(elevation=7.0), point)

    # 新しいElevationClientインスタンス（プロセス内メモリを持たない）でもSQLite経由でヒットする
    second_http_client = FakeHttpClient(elevation=999.0)
    result = await ElevationClient().get_elevation(second_http_client, point)

    assert result == 7.0
    assert second_http_client.call_count == 0


async def test_get_elevation_refresh_bypasses_cache_and_overwrites():
    client = ElevationClient()
    point = Coordinates(latitude=35.6, longitude=139.6)
    await client.get_elevation(FakeHttpClient(elevation=1.0), point)

    http_client = FakeHttpClient(elevation=2.0)
    result = await client.get_elevation(http_client, point, refresh=True)

    assert result == 2.0
    assert http_client.call_count == 1
    # 上書き後は通常呼び出しでも新しい値がキャッシュから返る
    assert await client.get_elevation(FakeHttpClient(elevation=999.0), point) == 2.0
