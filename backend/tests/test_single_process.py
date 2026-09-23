"""`infrastructure/single_process.py`——ワーカーを複数にした起動を止める。

ワーカーは親の`sys.argv`を受け継ぐため、ここではワーカーの中から見える`argv`と環境変数を
そのまま渡して判定を見る。
"""

from pathlib import Path

import pytest

from app.infrastructure.single_process import require_single_worker, uvicorn_worker_count

_UVICORN = "/usr/local/bin/uvicorn"


@pytest.mark.parametrize(
    ("argv", "environ", "expected"),
    [
        pytest.param([_UVICORN, "app.main:app", "--port", "8000"], {}, 1, id="指定なし"),
        pytest.param([_UVICORN, "app.main:app", "--workers", "2"], {}, 2, id="引数で2"),
        pytest.param([_UVICORN, "app.main:app", "--workers=4"], {}, 4, id="等号つき"),
        pytest.param([_UVICORN, "app.main:app"], {"WEB_CONCURRENCY": "3"}, 3, id="環境変数"),
        pytest.param(
            [_UVICORN, "app.main:app", "--workers", "1"], {"WEB_CONCURRENCY": "3"}, 1, id="引数が環境変数に勝つ"
        ),
        pytest.param([_UVICORN, "app.main:app", "--reload", "--workers", "2"], {}, 1, id="reloadはワーカー指定を無視"),
        pytest.param(
            ["/usr/lib/python3/site-packages/uvicorn/__main__.py", "app.main:app", "--workers", "2"],
            {},
            2,
            id="python -m uvicorn",
        ),
        pytest.param(
            [str(Path("venv") / "Scripts" / "uvicorn.exe"), "app.main:app", "--workers", "2"], {}, 2, id="拡張子つき"
        ),
        pytest.param(["/usr/bin/pytest", "-q", "--workers", "2"], {"WEB_CONCURRENCY": "3"}, 1, id="uvicorn以外"),
    ],
)
def test_worker_count_follows_how_uvicorn_reads_its_arguments(argv, environ, expected):
    assert uvicorn_worker_count(argv, environ) == expected


def test_more_than_one_worker_stops_the_startup():
    with pytest.raises(RuntimeError, match="workers=2"):
        require_single_worker([_UVICORN, "app.main:app", "--workers", "2"], {})


def test_a_single_worker_starts():
    require_single_worker([_UVICORN, "app.main:app"], {})
