import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_jma_tile_client
from app.config import settings
from app.infrastructure import rate_limiter
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_rate_limiter():
    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


class FakeJmaTileClient:
    """改善計画T510: ルーターがレート制限より先にキャッシュを参照する構成
    （`get_cached`→ミスなら`enforce_rate_limit`→`fetch`）に合わせ、2つのメソッドを
    個別に差し替えられるフェイク。"""

    def __init__(self, cached_result=None, fetch_result=None):
        self._cached_result = cached_result
        self._fetch_result = fetch_result
        self.get_cached_calls = 0
        self.fetch_calls = 0
        self.requested_paths: list[str] = []

    async def get_cached(self, path):
        self.get_cached_calls += 1
        self.requested_paths.append(path)
        return self._cached_result

    async def fetch(self, path):
        self.fetch_calls += 1
        self.requested_paths.append(path)
        return self._fetch_result


def test_jma_tile_proxy_returns_cached_content_with_correct_media_type():
    fake = FakeJmaTileClient(cached_result=(b"\x89PNG", "image/png"))
    app.dependency_overrides[get_jma_tile_client] = lambda: fake

    try:
        response = client.get(
            "/api/jma-tile/bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/land/11/1818/805.png"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content == b"\x89PNG"
    assert fake.fetch_calls == 0


def test_jma_tile_proxy_returns_502_on_upstream_failure():
    fake = FakeJmaTileClient(cached_result=None, fetch_result=None)
    app.dependency_overrides[get_jma_tile_client] = lambda: fake

    try:
        response = client.get("/api/jma-tile/bosai/jmatile/data/risk/targetTimes.json")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502


def test_jma_tile_proxy_is_rate_limited_per_client_on_cache_miss():
    fake = FakeJmaTileClient(cached_result=None, fetch_result=(b"{}", "application/json"))
    app.dependency_overrides[get_jma_tile_client] = lambda: fake

    try:
        for _ in range(settings.jma_tile_rate_limit_per_minute - 1):
            rate_limiter.check_rate_limit("jma-tile:testclient", settings.jma_tile_rate_limit_per_minute)
        assert client.get("/api/jma-tile/bosai/jmatile/data/risk/targetTimes.json").status_code == 200
        response = client.get("/api/jma-tile/bosai/jmatile/data/risk/targetTimes.json")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429


def test_jma_tile_proxy_cache_hit_does_not_consume_rate_limit():
    """改善計画T510: キャッシュヒットはレート制限を一切消費しない（以前は
    enforce_rate_limitがキャッシュ参照より先に呼ばれており、既にキャッシュ済みの
    タイルへの往復パンだけで429になっていた——ユーザー報告の直接原因）。"""
    fake = FakeJmaTileClient(cached_result=(b"\x89PNG", "image/png"))
    app.dependency_overrides[get_jma_tile_client] = lambda: fake

    try:
        # レート制限の残り枠を1つだけ残した状態を直接作る（境界値テストは
        # rate_limiter.check_rate_limitを直接呼んで埋める方針、docs/testing.md参照）。
        for _ in range(settings.jma_tile_rate_limit_per_minute - 1):
            rate_limiter.check_rate_limit("jma-tile:testclient", settings.jma_tile_rate_limit_per_minute)
        path = "/api/jma-tile/bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/land/11/1818/805.png"
        # 残り枠1つの状態でキャッシュヒットのリクエストを2回行っても、どちらも枠を
        # 消費しないため両方とも200になる（消費していれば2回目が429になるはず）。
        first = client.get(path)
        second = client.get(path)
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 200
    assert second.status_code == 200
    assert fake.fetch_calls == 0


def test_jma_tile_proxy_forwards_query_string_to_client():
    fake = FakeJmaTileClient(cached_result=(b'{"type":"FeatureCollection"}', "application/json"))
    app.dependency_overrides[get_jma_tile_client] = lambda: fake

    try:
        response = client.get(
            "/api/jma-tile/bosai/jmatile/data/nowc/20260904120000/none/20260904120000/surf/liden/data.geojson",
            params={"id": "liden"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert fake.requested_paths == [
        "bosai/jmatile/data/nowc/20260904120000/none/20260904120000/surf/liden/data.geojson?id=liden"
    ]
