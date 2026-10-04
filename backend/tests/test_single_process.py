"""`infrastructure/single_process.py`——ワーカーが複数になる起動を止める（`require_single_worker`）。

入力は起動したプロセスの`argv`と環境変数で、どちらも値として与える。

ここで見ないもの:
- lifespanの最初でこれを呼ぶこと → `main.py`（結線のみ）
"""

import pytest

from app.infrastructure.single_process import require_single_worker

# 本番のコンテナが起動するコマンド（`backend/Dockerfile`の`CMD`）と同じ形。
PRODUCTION_ARGV = [
    "/usr/local/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000",
    "--proxy-headers", "--forwarded-allow-ips=*", "--no-access-log",
]


@pytest.mark.parametrize(
    ("argv", "environ"),
    [
        pytest.param(PRODUCTION_ARGV, {}, id="production-command"),
        pytest.param([*PRODUCTION_ARGV, "--workers", "1"], {}, id="one-worker"),
        pytest.param(["/usr/local/bin/uvicorn", "app.main:app", "--reload", "--workers", "4"], {}, id="reload"),
        pytest.param(["/usr/local/bin/uvicorn", "app.main:app", "--reload"], {"WEB_CONCURRENCY": "4"},
                     id="reload-with-env"),
        pytest.param([*PRODUCTION_ARGV, "--workers", "1"], {"WEB_CONCURRENCY": "4"}, id="flag-wins-over-env"),
        pytest.param(["/usr/local/bin/pytest", "--workers", "4"], {"WEB_CONCURRENCY": "4"}, id="not-uvicorn"),
        pytest.param(["/srv/other/__main__.py", "--workers", "4"], {}, id="another-package-run-with-m"),
        pytest.param([], {"WEB_CONCURRENCY": "4"}, id="no-argv"),
    ],
)
def test_a_single_process_start_is_allowed(argv, environ):
    require_single_worker(argv, environ)


@pytest.mark.parametrize(
    ("argv", "environ", "workers"),
    [
        pytest.param([*PRODUCTION_ARGV, "--workers", "2"], {}, 2, id="workers-flag"),
        pytest.param(PRODUCTION_ARGV, {"WEB_CONCURRENCY": "3"}, 3, id="web-concurrency"),
        pytest.param(["/usr/lib/python3/site-packages/uvicorn/__main__.py", "app.main:app", "--workers", "2"], {}, 2,
                     id="python-m-uvicorn"),
        pytest.param(["C:/venv/Scripts/uvicorn.exe", "app.main:app", "--workers", "2"], {}, 2, id="windows-launcher"),
    ],
)
def test_a_start_with_several_workers_is_stopped(argv, environ, workers):
    with pytest.raises(RuntimeError, match=f"workers={workers}"):
        require_single_worker(argv, environ)
