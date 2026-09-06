"""`api/cache_policy.py`（Cache-Controlの一元管理）のテスト。

対応表の網羅性を機械的に検証することで、新しいエンドポイントを追加したときの
「ポリシーの決め忘れ」と、リファクタで消えたパスの「死んだエントリ」の両方を落とす。
"""

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.api.cache_policy import (
    _ROUTE_POLICIES,
    CachePolicy,
    CachePolicyMiddleware,
    policy_for_path,
)
from app.main import app


def _api_routes():
    return [route for route in app.routes if isinstance(route, APIRoute)]


def test_every_route_has_a_cache_policy():
    # 新しいエンドポイントを追加したら_ROUTE_POLICIESへも1行足す、を機械的に強制する。
    missing = [route.path for route in _api_routes() if policy_for_path(route.path) is None]
    assert missing == [], f"cache_policy.pyの対応表に無いルート: {missing}"


def test_every_policy_entry_matches_a_real_route():
    # リファクタでパスが変わった際に、表へ古いエントリが残り続けるのを防ぐ。
    paths = [route.path for route in _api_routes()]
    dead = [prefix for prefix, _ in _ROUTE_POLICIES if not any(path.startswith(prefix) for path in paths)]
    assert dead == [], f"どの実ルートにも一致しない対応表のエントリ: {dead}"


def test_policy_for_path_prefers_the_longest_prefix():
    # 表への追記順に依存しないことの保証（/api/basemap/refreshは/api/basemap/より長い）。
    assert policy_for_path("/api/basemap/refresh").header() == "no-store"
    assert policy_for_path("/api/basemap/planet/14/1/2.pbf").header() == "public, max-age=600"


def test_policy_for_path_returns_none_for_unknown_path():
    assert policy_for_path("/api/does-not-exist") is None


def test_cache_policy_header_formats():
    assert CachePolicy(max_age_seconds=60).header() == "public, max-age=60"
    assert CachePolicy(max_age_seconds=60, immutable=True).header() == "public, max-age=60, immutable"
    assert CachePolicy(max_age_seconds=None).header() == "no-store"


@pytest.fixture
def middleware_client():
    """`/api/debug/`（no-store）・`/api/material-catalog`（max-age）・ハンドラ明示・
    エラー応答を1つのアプリで確かめるための、対応表だけを共有する最小アプリ。"""
    test_app = FastAPI()
    test_app.add_middleware(CachePolicyMiddleware)

    @test_app.get("/api/material-catalog")
    def catalog():
        return {"ok": True}

    @test_app.get("/api/debug/stats")
    def stats():
        return {"ok": True}

    @test_app.get("/api/material-catalog/explicit")
    def explicit():
        from fastapi import Response

        return Response(content="{}", media_type="application/json", headers={"Cache-Control": "max-age=1"})

    @test_app.get("/api/material-catalog/boom")
    def boom():
        from fastapi import HTTPException

        raise HTTPException(status_code=502, detail="boom")

    return TestClient(test_app)


def test_middleware_applies_policy_from_the_table(middleware_client):
    response = middleware_client.get("/api/material-catalog")
    assert response.headers["cache-control"] == "public, max-age=3600"


def test_middleware_applies_no_store(middleware_client):
    response = middleware_client.get("/api/debug/stats")
    assert response.headers["cache-control"] == "no-store"


def test_middleware_keeps_handler_supplied_header(middleware_client):
    # 同じパスでも内容の性質でポリシーが分かれるエンドポイント（jma_tile.py）のため、
    # ハンドラが自分で設定した値をミドルウェアが上書きしない。
    response = middleware_client.get("/api/material-catalog/explicit")
    assert response.headers["cache-control"] == "max-age=1"


def test_middleware_does_not_cache_error_responses(middleware_client):
    # 上流障害等の一時的な失敗をキャッシュさせると障害が実際の復旧より長く尾を引く。
    response = middleware_client.get("/api/material-catalog/boom")
    assert response.status_code == 502
    assert "cache-control" not in response.headers
