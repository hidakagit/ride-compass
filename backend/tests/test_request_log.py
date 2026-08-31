"""リクエストIDミドルウェア・アクセスサマリログ(infrastructure/request_log.py)の回帰テスト。

docs/logging.mdの方針のうち「全レスポンスにX-Request-IDが付く」「クライアント指定の
X-Request-IDを引き継ぐ」「アクセスサマリのレベルはステータス・経路で変わる」
「未処理例外はスタックトレース付きERRORで残る」を守る。
"""

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app as main_app
from app.infrastructure.request_log import request_log_middleware, unhandled_exception_handler


def test_response_has_generated_request_id():
    client = TestClient(main_app)
    response = client.get("/health")
    assert response.status_code == 200
    request_id = response.headers.get("X-Request-ID")
    assert request_id
    assert len(request_id) == 12


def test_incoming_request_id_is_propagated():
    client = TestClient(main_app)
    response = client.get("/health", headers={"X-Request-ID": "my-debug-id-1"})
    assert response.headers["X-Request-ID"] == "my-debug-id-1"


def test_access_log_line_with_request_id(caplog):
    caplog.set_level(logging.INFO, logger="ridecompass.access")
    client = TestClient(main_app)
    client.get("/health", headers={"X-Request-ID": "req-for-log-1"})

    records = [r for r in caplog.records if r.name == "ridecompass.access"]
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.INFO
    message = record.getMessage()
    assert "GET /health -> 200" in message
    assert "ms client=" in message


def test_request_id_filter_injects_contextvar():
    # main.pyのフォーマット文字列%(request_id)sが参照する属性をfilterが全レコードへ注入する
    from app.infrastructure.request_log import RequestIdLogFilter, request_id_var

    record = logging.LogRecord("any", logging.INFO, __file__, 1, "msg", None, None)
    token = request_id_var.set("ctx-req-42")
    try:
        assert RequestIdLogFilter().filter(record) is True
        assert record.request_id == "ctx-req-42"
    finally:
        request_id_var.reset(token)


def test_access_level_policy():
    # タイル系(高頻度)のGET成功はDEBUG、通常エンドポイントの成功はINFO、
    # 4xxはWARNING(ただし429は別途record_rate_limit_rejectionが出すためDEBUG)、5xxはERROR。
    # タイル系プレフィックス配下でも状態を変える操作(POSTのキャッシュ全消去)はINFOで残す。
    from app.infrastructure.request_log import _access_level

    assert _access_level("GET", "/api/basemap/tiles/1", 200) == logging.DEBUG
    assert _access_level("GET", "/api/region/road-surface-tiles/14/1/1.pbf", 200) == logging.DEBUG
    assert _access_level("POST", "/api/basemap/refresh", 200) == logging.INFO
    assert _access_level("POST", "/api/routes/generate", 200) == logging.INFO
    assert _access_level("POST", "/api/routes/generate", 400) == logging.WARNING
    assert _access_level("POST", "/api/routes/generate", 429) == logging.DEBUG
    assert _access_level("GET", "/api/basemap/tiles/1", 502) == logging.ERROR


def test_unhandled_exception_logged_as_error_with_traceback(caplog):
    caplog.set_level(logging.ERROR, logger="ridecompass.access")

    test_app = FastAPI()
    test_app.middleware("http")(request_log_middleware)

    @test_app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    client = TestClient(test_app)
    with pytest.raises(RuntimeError):
        client.get("/boom")

    errors = [r for r in caplog.records if r.name == "ridecompass.access" and r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "GET /boom -> unhandled exception" in errors[0].getMessage()
    assert errors[0].exc_info is not None


# 改善計画T464: 未処理例外(500)発生時もX-Request-IDヘッダが付くことの回帰テスト。
# request_log_middlewareは例外を再送出するだけで実際の500レスポンスを持たないため
# （StarletteのServerErrorMiddlewareが外側で生成する）、unhandled_exception_handlerを
# FastAPIのExceptionハンドラとして登録することでヘッダを付与する（main.py参照）。
# TestClientはデフォルトでraise_server_exceptions=Trueのため、実際のHTTPレスポンスを
# 得るにはFalseを指定する必要がある。
def test_unhandled_exception_response_has_request_id_header():
    test_app = FastAPI()
    test_app.middleware("http")(request_log_middleware)
    test_app.add_exception_handler(Exception, unhandled_exception_handler)

    @test_app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    client = TestClient(test_app, raise_server_exceptions=False)
    response = client.get("/boom", headers={"X-Request-ID": "req-for-500-1"})

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "req-for-500-1"
