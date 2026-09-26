"""`scripts/orchestration/github.py`のジョブのログ取得とCI待ちを、手元に立てたHTTPの偽のGitHubで確かめる。

網はプロセス境界なので、GitHubのAPIの代わりに手元のHTTPサーバーを立て、`API_ROOT`をそこへ向ける。ログの取得は
GitHubと同じく署名付きの別のURLへの302で返し、転送先は認証の見出しが付いていれば401を返す（GitHubのログの
置き場は、転送された認証の見出しを拒む）。時計（待ちの間隔）も差し替える。
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from orchestration import github  # noqa: E402

SHA = "0123456789abcdef0123456789abcdef01234567"


class FakeGitHub(BaseHTTPRequestHandler):
    runs: list[list[dict]] = []
    jobs: dict[int, list[dict]] = {}
    served: list[str] = []

    def log_message(self, *args) -> None:
        pass

    def send_json(self, body: object) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        type(self).served.append(self.path)
        if self.path.startswith("/repos/o/r/actions/runs?"):
            seq = type(self).runs
            self.send_json({"workflow_runs": seq.pop(0) if len(seq) > 1 else seq[0]})
        elif self.path.startswith("/repos/o/r/actions/runs/") and "/jobs" in self.path:
            run_id = int(self.path.split("/")[6])
            self.send_json({"jobs": type(self).jobs.get(run_id, [])})
        elif self.path.startswith("/repos/o/r/actions/jobs/") and self.path.endswith("/logs"):
            self.send_response(302)
            self.send_header("Location", f"/blob/{self.path.split('/')[6]}")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path.startswith("/blob/"):
            if self.headers.get("Authorization"):
                self.send_response(401)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            data = "".join(f"行{i}\n" for i in range(1, 101)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()


@pytest.fixture
def fake(monkeypatch):
    FakeGitHub.runs, FakeGitHub.jobs, FakeGitHub.served = [], {}, []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeGitHub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(github, "API_ROOT", f"http://127.0.0.1:{server.server_address[1]}")
    monkeypatch.setattr(github, "REPO", "o/r")
    monkeypatch.setattr(github, "_token_cache", ["secret"])
    yield FakeGitHub
    server.shutdown()
    server.server_close()
    thread.join()


def run(run_id: int, name: str, status: str, conclusion: str | None) -> dict:
    return {"id": run_id, "name": name, "head_sha": SHA, "status": status, "conclusion": conclusion,
            "run_number": run_id, "html_url": f"https://example.invalid/runs/{run_id}"}


def test_job_log_is_read_through_the_redirect_without_the_token(fake):
    text, error = github.job_log(7)

    assert error == ""
    assert text.splitlines()[-1] == "行100"
    assert "/blob/7" in fake.served


def test_failed_job_logs_return_the_tail_of_each_failed_job(fake):
    fake.runs = [[run(1, "CI", "completed", "failure"), run(2, "Docs Consistency", "completed", "success")]]
    fake.jobs = {1: [{"id": 7, "name": "backend", "status": "completed", "conclusion": "failure", "steps": []},
                     {"id": 8, "name": "frontend", "status": "completed", "conclusion": "success", "steps": []}]}

    logs, error = github.failed_job_logs(SHA, lines=3)

    assert error == ""
    assert [(entry["job"], entry["log"]) for entry in logs] == [("backend", "行98\n行99\n行100")]


def test_wait_for_ci_polls_until_every_workflow_finishes(fake):
    fake.runs = [[run(1, "CI", "in_progress", None)],
                 [run(1, "CI", "completed", "success"), run(2, "Docs Consistency", "completed", "success")]]
    naps: list[float] = []

    verdicts, error = github.wait_for_ci(SHA, timeout_s=600, interval_s=60, sleep=naps.append)

    assert error == ""
    assert [(v["name"], v["conclusion"]) for v in verdicts] == [("CI", "success"), ("Docs Consistency", "success")]
    assert naps == [60]


def test_wait_for_ci_refuses_a_short_sha_without_asking_github(fake):
    verdicts, error = github.wait_for_ci(SHA[:8], sleep=lambda s: None)

    assert verdicts == []
    assert "40桁" in error
    assert fake.served == []


def test_wait_for_ci_gives_up_at_the_timeout(fake):
    fake.runs = [[run(1, "CI", "in_progress", None)]]

    verdicts, error = github.wait_for_ci(SHA, timeout_s=120, interval_s=60, sleep=lambda s: None)

    assert "時間切れ" in error
    assert [v["status"] for v in verdicts] == ["in_progress"]
