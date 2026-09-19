import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_gsi_tile_client
from app.config import settings
from app.infrastructure import rate_limiter
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_rate_limiter():
    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


class FakeGsiTileClient:
    def __init__(self, result):
        self._result = result

    async def get(self, path):
        return self._result


def test_gsi_relief_tile_proxy_returns_content_with_correct_media_type():
    app.dependency_overrides[get_gsi_tile_client] = lambda: FakeGsiTileClient((b"\x89PNG", "image/png"))

    try:
        response = client.get("/api/gsi-relief-tile/xyz/relief/12/3637/1612.png")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content == b"\x89PNG"


def test_gsi_relief_tile_proxy_returns_502_on_upstream_failure():
    app.dependency_overrides[get_gsi_tile_client] = lambda: FakeGsiTileClient(None)

    try:
        response = client.get("/api/gsi-relief-tile/xyz/relief/12/3637/1612.png")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502


def test_gsi_relief_tile_proxy_returns_404_when_tile_not_found_upstream():
    # 改善計画T605: 整備区域外（404、珍しくない正常系）は502ではなく404を返す。
    from app.infrastructure.gsi_tile_client import GSI_TILE_NOT_FOUND

    app.dependency_overrides[get_gsi_tile_client] = lambda: FakeGsiTileClient(GSI_TILE_NOT_FOUND)

    try:
        response = client.get("/api/gsi-relief-tile/xyz/relief/12/3637/1612.png")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


def test_整備区域外の404はブラウザへもキャッシュさせる():
    """`raster-dem`は整備区域外のタイルも視界へ入るたび要求する。

    サーバー側は同じ事実をプロセス内に持って上流へ問い合わせ直さないが、それだけでは
    ブラウザからの要求は減らない——沿岸部を連続してパンする利用者は404だけでレート制限に
    達しうる。恒久404はブラウザにも伝える。
    """
    from app.api.cache_policy import GSI_TILE_NOT_FOUND
    from app.infrastructure.gsi_tile_client import GSI_TILE_NOT_FOUND as NOT_FOUND_SENTINEL

    app.dependency_overrides[get_gsi_tile_client] = lambda: FakeGsiTileClient(NOT_FOUND_SENTINEL)

    try:
        relief = client.get("/api/gsi-relief-tile/xyz/relief/12/3637/1612.png")
        terrain = client.get("/api/gsi-terrain-tile/13/7276/3225.png")
    finally:
        app.dependency_overrides.clear()

    for response in (relief, terrain):
        assert response.status_code == 404
        assert response.headers["cache-control"] == GSI_TILE_NOT_FOUND.header()


def test_gsi_relief_tile_proxy_is_rate_limited_per_client():
    app.dependency_overrides[get_gsi_tile_client] = lambda: FakeGsiTileClient((b"x", "image/png"))

    try:
        for _ in range(settings.gsi_tile_rate_limit_per_minute - 1):
            rate_limiter.check_rate_limit("gsi-relief-tile:testclient", settings.gsi_tile_rate_limit_per_minute)
        assert client.get("/api/gsi-relief-tile/xyz/relief/12/3637/1612.png").status_code == 200
        response = client.get("/api/gsi-relief-tile/xyz/relief/12/3637/1612.png")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429


def test_標高タイルはTerrainRGBへ変換して返す():
    # 配信元のエンコード（センチメートル・2の補数）のまま返すと、MapLibreはそれを標高として
    # 読めない。変換が経路を通っていることを、値を復号して確かめる。
    from app.domain.terrain_rgb import decode_terrain_rgb_meters
    from tests.test_terrain_rgb import gsi_tile

    app.dependency_overrides[get_gsi_tile_client] = lambda: FakeGsiTileClient((gsi_tile([[1_234]]), "image/png"))

    try:
        response = client.get("/api/gsi-terrain-tile/13/7276/3225.png")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert decode_terrain_rgb_meters(response.content)[0][0] == pytest.approx(12.3, abs=0.05)


def test_標高タイルは整備区域外を404で返す():
    from app.infrastructure.gsi_tile_client import GSI_TILE_NOT_FOUND

    app.dependency_overrides[get_gsi_tile_client] = lambda: FakeGsiTileClient(GSI_TILE_NOT_FOUND)

    try:
        response = client.get("/api/gsi-terrain-tile/13/7276/3225.png")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


def test_標高タイルは上流障害を502で返す():
    app.dependency_overrides[get_gsi_tile_client] = lambda: FakeGsiTileClient(None)

    try:
        response = client.get("/api/gsi-terrain-tile/13/7276/3225.png")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502


def test_標高タイルは配信元がデータを持たないズームを拒む():
    # 配信元はz14までしか実データを持たない。範囲外をそのまま上流へ投げない。
    app.dependency_overrides[get_gsi_tile_client] = lambda: FakeGsiTileClient((b"", "image/png"))

    try:
        response = client.get("/api/gsi-terrain-tile/16/58211/25802.png")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
