"""`api/routers/basemap.py`——基礎地図の中継と、タイルのファイルキャッシュの全消去。

確かめるのは、取得の結果（中身・配信元に無い・失敗）がどの応答になるかと、中継の回数制限（429）、全消去の口。
取得の口（`get_basemap_client`）は応答を差し替える。

ここで見ないもの:
- 配信元への取得・キャッシュの読み書き・「配信元に無い」の見分け → `test_basemap_client.py`
- 回数制限の数え方そのもの → `test_rate_limiter.py`
- 管理の口の認証 → `test_admin_route_authorization.py`
"""

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_basemap_client
from app.config import settings
from app.infrastructure import rate_limiter, tile_cache
from app.infrastructure.basemap_client import BASEMAP_NOT_FOUND
from app.main import app
from tests.admin_auth import ADMIN_PASSWORD, ADMIN_USERNAME

client = TestClient(app)

REFRESH_PATH = "/api/admin/basemap/refresh"


class FakeBasemapClient:
    def __init__(self, result):
        self._result = result

    async def get(self, path):
        return self._result


def _answer(monkeypatch, result):
    monkeypatch.setitem(app.dependency_overrides, get_basemap_client, lambda: FakeBasemapClient(result))


def test_basemap_proxy_returns_cached_content_with_correct_media_type(monkeypatch):
    _answer(monkeypatch, (b'{"version":8}', "application/json"))

    response = client.get("/api/basemap/styles/liberty")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.content == b'{"version":8}'


@pytest.mark.parametrize(("result", "status"), [
    (None, 502),
    # 配信元に無い部品は上流障害ではない。502で返すと、本当の障害が埋もれる。
    (BASEMAP_NOT_FOUND, 404),
])
def test_basemap_proxy_tells_a_missing_part_apart_from_an_upstream_failure(monkeypatch, result, status):
    _answer(monkeypatch, result)

    assert client.get("/api/basemap/fonts/NotoSans/40000-40255.pbf").status_code == status


def test_basemap_proxy_is_rate_limited_per_client(monkeypatch):
    _answer(monkeypatch, (b"x", "application/json"))

    for _ in range(settings.basemap_rate_limit_per_minute - 1):
        rate_limiter.check_rate_limit("basemap:testclient", settings.basemap_rate_limit_per_minute)
    assert client.get("/api/basemap/styles/liberty").status_code == 200

    assert client.get("/api/basemap/styles/liberty").status_code == 429


def test_basemap_refresh_clears_tile_cache(admin_credentials):
    tile_cache.set("styles/liberty", b"cached", "application/json")

    response = client.post(REFRESH_PATH, auth=(ADMIN_USERNAME, ADMIN_PASSWORD))

    assert response.status_code == 200
    assert tile_cache.get("styles/liberty") is None
