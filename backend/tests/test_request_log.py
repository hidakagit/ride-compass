"""リクエストIDミドルウェア・アクセスサマリログ(infrastructure/request_log.py)のテスト。

docs/conventions/logging.mdの方針のうち「全レスポンスにX-Request-IDが付く」「クライアント指定の
X-Request-IDを引き継ぐ」「アクセスサマリのレベルはステータス・経路で変わる」
「未処理例外はスタックトレース付きERRORで残る」を守る。ログ行の時刻がJSTで、
オフセットを名乗ることも併せて検査する（書式はこのモジュールが1つだけ持つ）。
"""

import calendar
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app as main_app
from app.infrastructure.request_log import (
    LOG_FORMAT,
    JstLogFormatter,
    RequestIdLogFilter,
    request_log_middleware,
    unhandled_exception_handler,
)


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
    assert _access_level("POST", "/api/admin/basemap/refresh", 200) == logging.INFO
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


# 未処理例外(500)でもX-Request-IDヘッダが付く。TestClientは既定で
# raise_server_exceptions=Trueのため、実際のHTTPレスポンスを得るにはFalseを指定する。
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


def _formatted_line(created_utc: tuple[int, int, int, int, int, int], msecs: float) -> str:
    """UTCの壁時計を与えて、1レコードを整形した行を返す。"""
    record = logging.LogRecord("ridecompass.test", logging.INFO, "/x", 1, "本文", (), None)
    record.created = calendar.timegm((*created_utc, 0, 0, 0)) + msecs / 1000
    record.msecs = msecs
    RequestIdLogFilter().filter(record)
    return JstLogFormatter(LOG_FORMAT).format(record)


def test_log_time_is_written_in_jst():
    """コンテナのTZ（UTC）ではなくJSTの壁時計で書く。

    ずれたままだと、ブラウザ側のデバッグログ（利用者のローカル時刻）が示す時刻で
    backendのログを探したとき、9時間離れた窓を見て「該当ログなし」と読んでしまう。
    """
    line = _formatted_line((2026, 9, 18, 0, 0, 30), 840)

    assert line.startswith("2026-09-18 09:00:30,840")


def test_log_time_names_its_offset():
    """行が自分の時間帯を名乗る。ずれていること自体より、読み手が気づけないことが問題。"""
    line = _formatted_line((2026, 9, 18, 0, 0, 30), 840)

    assert "+0900" in line
