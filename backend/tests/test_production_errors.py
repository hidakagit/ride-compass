"""`scripts/production_errors.py`が、本番のbackendの記録にエラーがあれば・読めなければ失敗する。

backendは手元の小さなHTTPサーバーで代わりに応答する（網の境界）。応答の形は読む口のモデルから作る。

ここで見ないもの: 記録と読む口そのもの → `test_error_reports_route.py`
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from app.api.routers.error_reports import ErrorReportsResponse
from app.infrastructure.error_reports import ErrorReport
from tests.script_module import load_script

production_errors = load_script("production_errors")

REPORT = ErrorReport(
    at=datetime(2026, 10, 10, 1, 2, 3, tzinfo=UTC),
    source="frontend",
    kind="network",
    name="api:routes-generate",
    page="/",
    request_id=None,
)


@contextmanager
def _backend(response: ErrorReportsResponse, asked: list[str]) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlparse(self.path)
            asked.append(parse_qs(url.query)["since"][0])
            body = response.model_dump_json().encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def test_fails_and_prints_the_reports_when_any_error_was_recorded(capsys):
    asked: list[str] = []
    with _backend(ErrorReportsResponse(count=3, recent=[REPORT]), asked) as origin:
        code = production_errors.main(["production_errors.py", origin, "2026-10-10T00:00:00+00:00"])

    assert code == 1
    assert asked == ["2026-10-10T00:00:00+00:00"]
    out = capsys.readouterr().out
    assert "3 件" in out
    assert "api:routes-generate" in out


def test_passes_when_no_error_was_recorded():
    with _backend(ErrorReportsResponse(count=0, recent=[]), []) as origin:
        assert production_errors.main(["production_errors.py", origin]) == 0


def test_fails_when_the_backend_cannot_be_reached(capsys):
    with _backend(ErrorReportsResponse(count=0, recent=[]), []) as origin:
        pass

    assert production_errors.main(["production_errors.py", origin]) == 1
    assert "読めない" in capsys.readouterr().out
