"""`api/routers/gsi_tile.py`——地理院の色別標高図の中継と、標高タイル（Terrain-RGB）の配信。

確かめるのは、取得の結果（中身・整備区域外・失敗）がどの応答になるかと、整備区域外の404をブラウザにも
覚えさせること、回数制限（429）、標高タイルのズームと座標の範囲（422）。取得の口（`get_gsi_tile_client`）は応答を差し替える。

ここで見ないもの:
- 配信元への取得・ディスクへの記憶・整備区域外の見分け → `test_gsi_tile_client.py`
- 標高タイルの書式の変換 → `test_gsi_dem_png.py`
- 回数制限の数え方そのもの → `test_rate_limiter.py`
"""

import pytest
from fastapi.testclient import TestClient

from app.api.cache_policy import GSI_TILE_NOT_FOUND
from app.api.dependencies import get_gsi_tile_client
from app.config import settings
from app.infrastructure import rate_limiter
from app.infrastructure.gsi_tile_client import GSI_TILE_NOT_FOUND as NOT_FOUND_SENTINEL
from app.main import app

client = TestClient(app)

RELIEF_TILE = "/api/gsi-relief-tile/xyz/relief/12/3637/1612.png"
TERRAIN_TILE = "/api/gsi-terrain-tile/13/7276/3225.png"


class FakeGsiTileClient:
    def __init__(self, result):
        self._result = result

    async def get(self, path):
        return self._result


def _answer(monkeypatch, result):
    monkeypatch.setitem(app.dependency_overrides, get_gsi_tile_client, lambda: FakeGsiTileClient(result))


def test_gsi_relief_tile_proxy_returns_content_with_correct_media_type(monkeypatch):
    _answer(monkeypatch, (b"\x89PNG", "image/png"))

    response = client.get(RELIEF_TILE)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content == b"\x89PNG"


@pytest.mark.parametrize("path", [RELIEF_TILE, TERRAIN_TILE])
def test_an_upstream_failure_is_502(monkeypatch, path):
    _answer(monkeypatch, None)

    assert client.get(path).status_code == 502


@pytest.mark.parametrize("path", [RELIEF_TILE, TERRAIN_TILE])
def test_整備区域外は404で返し_ブラウザへもキャッシュさせる(monkeypatch, path):
    """整備区域外（珍しくない正常系）は上流障害の502にしない。

    `raster-dem`は整備区域外のタイルも視界へ入るたび要求する。サーバー側は同じ事実をプロセス内に
    持って上流へ問い合わせ直さないが、それだけではブラウザからの要求は減らない——沿岸部を連続して
    パンする利用者は404だけでレート制限に達しうる。恒久404はブラウザにも伝える。
    """
    _answer(monkeypatch, NOT_FOUND_SENTINEL)

    response = client.get(path)

    assert response.status_code == 404
    assert response.headers["cache-control"] == GSI_TILE_NOT_FOUND.header()


def test_gsi_relief_tile_proxy_is_rate_limited_per_client(monkeypatch):
    _answer(monkeypatch, (b"x", "image/png"))

    for _ in range(settings.gsi_tile_rate_limit_per_minute - 1):
        rate_limiter.check_rate_limit("gsi-relief-tile:testclient", settings.gsi_tile_rate_limit_per_minute)
    assert client.get(RELIEF_TILE).status_code == 200

    assert client.get(RELIEF_TILE).status_code == 429


def test_標高タイルは配信元がデータを持たないズームを拒む(monkeypatch):
    # 配信元はz14までしか実データを持たない。範囲外をそのまま上流へ投げない。
    _answer(monkeypatch, (b"", "image/png"))

    assert client.get("/api/gsi-terrain-tile/16/58211/25802.png").status_code == 422
    assert client.get(f"/api/gsi-terrain-tile/14/{2**14}/6450.png").status_code == 422
