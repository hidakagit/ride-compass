"""リクエストID・アクセスサマリログ(infrastructure/request_log.py)のテスト。

docs/conventions/logging.mdの方針のうち「全レスポンスにX-Request-IDが付く」「クライアント指定の
X-Request-IDを引き継ぐ」「アクセスサマリのレベルはステータス・経路で変わる」
「未処理例外はスタックトレース付きERRORで残る」を守る。ログ行の時刻がJSTで、
オフセットを名乗ることも併せて検査する（書式はこのモジュールが1つだけ持つ）。

ここで見ないもの: IDの形式の確かめ方・発行の仕方 → `asgi_correlation_id`の持ち物
"""

import calendar
import logging

import pytest
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app as main_app
from app.infrastructure.request_log import (
    access_level,
    format_log_lines,
    request_log_middleware,
    unhandled_exception_handler,
)

CLIENT_REQUEST_ID = "0f8fad5bd9cb469fa16570867728950e"


def test_response_has_generated_request_id():
    client = TestClient(main_app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")


def test_incoming_request_id_is_propagated():
    client = TestClient(main_app)
    response = client.get("/health", headers={"X-Request-ID": CLIENT_REQUEST_ID})
    assert response.headers["X-Request-ID"] == CLIENT_REQUEST_ID


def test_access_log_line_carries_the_request_id(caplog):
    """アクセスログの行にも応答と同じIDが載る。載らないと、利用者の手元のIDで行を探せない。"""
    caplog.set_level(logging.INFO, logger="ridecompass.access")
    format_log_lines(caplog.handler)
    client = TestClient(main_app)
    client.get("/health", headers={"X-Request-ID": CLIENT_REQUEST_ID})

    records = [r for r in caplog.records if r.name == "ridecompass.access"]
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.INFO
    line = caplog.handler.format(record)
    assert f"[req:{CLIENT_REQUEST_ID}]" in line
    assert "GET /health -> 200" in line
    assert "ms client=" in line


@pytest.mark.parametrize(
    ("method", "path", "status_code", "level"),
    [
        # タイル系(高頻度)のGET成功はDEBUG、通常エンドポイントの成功はINFO。
        ("GET", "/api/basemap/tiles/1", 200, logging.DEBUG),
        ("GET", "/api/axis-catalog", 200, logging.INFO),
        # 4xxはWARNING(ただし429は別途record_rate_limit_rejectionが出すためDEBUG)、5xxはERROR。
        ("POST", "/api/routes/generate", 400, logging.WARNING),
        ("POST", "/api/routes/generate", 429, logging.DEBUG),
        ("GET", "/api/basemap/tiles/1", 502, logging.ERROR),
    ],
)
def test_access_level_policy(method, path, status_code, level):
    assert access_level(method, path, status_code) == level


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
    test_app.add_middleware(CorrelationIdMiddleware)
    test_app.add_exception_handler(Exception, unhandled_exception_handler)

    @test_app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    client = TestClient(test_app, raise_server_exceptions=False)
    response = client.get("/boom", headers={"X-Request-ID": CLIENT_REQUEST_ID})

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == CLIENT_REQUEST_ID


def _formatted_line(created_utc: tuple[int, int, int, int, int, int], msecs: float) -> str:
    """UTCの壁時計を与えて、1レコードを整形した行を返す。"""
    record = logging.LogRecord("ridecompass.test", logging.INFO, "/x", 1, "本文", (), None)
    record.created = calendar.timegm((*created_utc, 0, 0, 0)) + msecs / 1000
    record.msecs = msecs
    handler = logging.Handler()
    format_log_lines(handler)
    handler.filter(record)
    return handler.format(record)


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
