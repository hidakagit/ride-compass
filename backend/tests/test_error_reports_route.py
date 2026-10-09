"""本番で起きたエラーが記録され、読む口（`GET /api/debug/errors`）から読める。

定期の見張り（`scripts/production_errors.py`）はこの読む口の件数で知らせるので、記録から漏れたエラーは知らせが来ない。

ここで見ないもの: 報告の口のレート制限 → 共有の`enforce_rate_limit`（`test_rate_limiter.py`）
"""

import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.api.dependencies import get_place_search_service
from app.infrastructure import error_reports
from app.infrastructure.error_reports import KEEP_REPORTS, TRIM_BYTES, ErrorReport
from app.main import app

client = TestClient(app)


def _read(since: datetime) -> dict:
    response = client.get("/api/debug/errors", params={"since": since.isoformat()})
    assert response.status_code == 200
    return response.json()


def _post_client_error(body: dict | str):
    content = body if isinstance(body, str) else json.dumps(body)
    return client.post("/api/client-errors", content=content, headers={"Content-Type": "text/plain;charset=UTF-8"})


def test_backend_error_log_is_recorded_without_its_message():
    started = datetime.now(UTC)
    try:
        raise ValueError("lat=35.6812 lon=139.7671")
    except ValueError:
        logging.getLogger("ridecompass.test").exception("生成に失敗した")

    body = _read(started)

    assert body["count"] == 1
    [report] = body["recent"]
    assert (report["source"], report["kind"], report["name"]) == ("backend", "ridecompass.test", "ValueError")
    assert "35.68" not in json.dumps(report)


def test_warning_log_is_not_recorded():
    started = datetime.now(UTC)
    logging.getLogger("ridecompass.test").warning("外部APIの失敗")

    assert _read(started)["count"] == 0


def test_unhandled_exception_in_a_request_is_recorded_with_its_request_id():
    class _BrokenService:
        async def search(self, query, near):
            raise RuntimeError("壊れた")

    started = datetime.now(UTC)
    app.dependency_overrides[get_place_search_service] = _BrokenService
    try:
        response = TestClient(app, raise_server_exceptions=False).get(
            "/api/place-search", params={"q": "駅", "latitude": 35.68, "longitude": 139.76}
        )
    finally:
        app.dependency_overrides.pop(get_place_search_service)

    assert response.status_code == 500
    reports = _read(started)["recent"]
    assert {report["name"] for report in reports} == {"RuntimeError"}
    assert {report["request_id"] for report in reports} == {response.headers["X-Request-ID"]}


def test_client_error_sent_as_text_plain_is_recorded():
    started = datetime.now(UTC)

    response = _post_client_error({"kind": "network", "name": "api:routes-generate", "page": "/"})

    assert response.status_code == 204
    [report] = _read(started)["recent"]
    assert (report["source"], report["kind"], report["name"], report["page"]) == (
        "frontend",
        "network",
        "api:routes-generate",
        "/",
    )


def test_client_error_that_could_carry_user_input_is_rejected_and_not_recorded():
    started = datetime.now(UTC)
    bodies = [
        {"kind": "exception", "name": "TypeError", "page": "/?lat=35.68"},
        {"kind": "exception", "name": "Cannot read properties of undefined", "page": "/"},
        {"kind": "exception", "name": "TypeError", "page": "/", "message": "35.68,139.76"},
        {"kind": "console", "name": "TypeError", "page": "/"},
        "not json",
    ]

    statuses = [_post_client_error(body).status_code for body in bodies]

    assert statuses == [422] * len(bodies)
    assert _read(started)["count"] == 0


def test_reports_written_before_a_restart_are_read_and_older_ones_are_left_out(error_reports_path):
    now = datetime.now(UTC)
    written = [
        ErrorReport(at=now - timedelta(hours=2), source="backend", kind="old", name="-", page=None, request_id=None),
        ErrorReport(at=now - timedelta(minutes=5), source="frontend", kind="render", name="Error", page="/", request_id=None),
    ]
    error_reports_path.write_text("".join(report.model_dump_json() + "\n" for report in written), encoding="utf-8")

    body = _read(now - timedelta(hours=1))

    assert body["count"] == 1
    assert body["recent"][0]["kind"] == "render"


def test_file_is_cut_back_to_the_newest_reports_once_it_grows_too_large(error_reports_path):
    old = ErrorReport(at=datetime.now(UTC), source="backend", kind="old", name="-", page=None, request_id=None)
    line = old.model_dump_json() + "\n"
    error_reports_path.write_text(line * (TRIM_BYTES // len(line) + 1), encoding="utf-8")

    error_reports.record(old.model_copy(update={"kind": "newest"}))

    lines = error_reports_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == KEEP_REPORTS
    assert json.loads(lines[-1])["kind"] == "newest"
