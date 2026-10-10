"""`scripts/ci_changes.py`の判定テスト（GitHubには触れない）。

履歴は一時的なgitリポジトリで作り、表（`RULES`）とbackendの本番への振り分け（`scripts/deploy_backend_gate.py`）は本物を当てる。

ここで見ないもの: 表の1行ずつの中身は宣言なので書き写さない。見るのは、変更の種類ごとに走るジョブの組が、CIの約束
（読まない変更で走らせない・読む変更で必ず走らせる）を守ることだけ。像を作って起こす確かめそのものは`ci.yml`のジョブが持つ。
"""

import subprocess
from pathlib import Path

import pytest

from tests.script_module import load_script

ci = load_script("ci_changes")

_FRONTEND_TESTS = {"frontend", "e2e", "e2e-scan", "api-contract"}
_BACKEND_TESTS = {"backend", "api-contract"}


def _commit(repo: Path, *names: str) -> str:
    for name in names:
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(f"{name}\n{len(names)}", encoding="utf-8")
    subprocess.run(["git", "add", *names], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", names[0]],
        cwd=repo,
        check=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize(
    ("changed", "expected"),
    [
        # 像の作り方だけの変更: テストとe2eは読まないので走らせず、像を作って起こす確かめとデプロイだけを走らせる。
        (["frontend/Dockerfile"], {"frontend-image", "deploy-frontend"}),
        (["frontend/src/app/page.tsx"], _FRONTEND_TESTS | {"frontend-image", "deploy-frontend"}),
        # srcの下の.mdは読む検査があるので、文書として飛ばさない。
        (["frontend/src/components/README.md"], _FRONTEND_TESTS | {"frontend-image", "deploy-frontend"}),
        # テストだけの変更は、本番の画面を変えないので出さない。
        (["frontend/e2e/home.spec.ts"], _FRONTEND_TESTS),
        (["backend/app/main.py"], _BACKEND_TESTS | {"backend-image", "deploy-backend"}),
        (["backend/requirements.txt"], _BACKEND_TESTS | {"backend-image", "deploy-backend"}),
        # 像に入らないもの。
        (["backend/tests/test_x.py"], _BACKEND_TESTS),
        # 像に入らないが、本番へ出す手順そのもの。
        ([".github/workflows/deploy-backend.yml"], {"deploy-backend"}),
        (["scripts/deploy_backend_gate.py"], {"backend", "deploy-backend"}),
        (["docs/architecture/tech-stack.md", "README.md", ".claude/rules/testing.md"], set()),
        (["tools/flow-gate/src/gate.js", ".github/workflows/claude-task.yml"], set()),
        # どの行にも当たらない（読むジョブが分からない）ファイルは全部を走らせる。
        (["Makefile"], set(ci.JOBS)),
        # 検査の定義そのものの変更も全部。
        ([".github/workflows/ci.yml"], set(ci.JOBS)),
    ],
)
def test_jobs_follow_what_each_job_reads(repo, changed, expected):
    base = _commit(repo, "seed")
    head = _commit(repo, *changed)

    run = ci.decide(head, dict.fromkeys(ci.JOBS, base))

    assert {job for job, on in run.items() if on} == expected


def test_job_without_a_base_runs(repo):
    head = _commit(repo, "docs/a.md")

    run = ci.decide(head, {**dict.fromkeys(ci.JOBS, head), "e2e": None, "backend": "0" * 40})

    assert {job for job, on in run.items() if on} == {"e2e", "backend"}


def test_each_job_compares_with_its_own_last_success():
    # 近い順: デプロイだけが落ちた実行 → 実行全体が成功した実行。
    found = ci.bases([("deploy-failed", frozenset({"backend", "e2e"})), ("all-passed", None)])

    assert found["e2e"] == "deploy-failed"
    assert found["deploy-frontend"] == "all-passed"


def test_stops_reading_runs_once_every_job_has_a_base():
    def runs():
        yield "all-passed", None
        raise AssertionError("相手が全部決まったあとに、さらに古い実行を読んだ")

    assert set(ci.bases(runs()).values()) == {"all-passed"}


@pytest.mark.parametrize(
    ("name", "key"),
    [("backend", "backend"), ("e2e-scan (mobile 1/3)", "e2e-scan"), ("deploy-frontend / deploy", "deploy-frontend")],
)
def test_job_key_from_run_job_name(name, key):
    assert ci.job_key(name) == key
