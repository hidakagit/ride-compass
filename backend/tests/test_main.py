import logging

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


def test_cors_allows_configured_origin():
    allowed_origin = settings.cors_allowed_origins_list[0]

    response = client.get("/health", headers={"Origin": allowed_origin})

    assert response.headers["access-control-allow-origin"] == allowed_origin


def test_cors_rejects_origin_not_in_allowlist():
    response = client.get("/health", headers={"Origin": "http://evil.example.com"})

    assert "access-control-allow-origin" not in response.headers


def test_cors_exposes_request_id_header_for_browser_js():
    # クロスオリジンではexpose_headersに載せない限りブラウザのJSからヘッダを読めない。
    allowed_origin = settings.cors_allowed_origins_list[0]

    response = client.get("/health", headers={"Origin": allowed_origin})

    assert "x-request-id" in response.headers.get("access-control-expose-headers", "").lower()


def test_router_is_included_health_endpoint_reachable():
    response = client.get("/health")

    assert response.status_code == 200


def test_httpx_logger_level_suppressed_to_warning():
    # root loggerのレベルはpytestのログキャプチャプラグインが上書きするため、
    # main.pyのimportが明示的にsetLevelするhttpxロガー単体を見る。
    assert logging.getLogger("httpx").level == logging.WARNING
