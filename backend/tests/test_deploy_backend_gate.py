"""`scripts/deploy_backend_gate.py`の判定テスト（本番・ネットワークには触れない）。

履歴は一時的なgitリポジトリで作り、振り分けの一覧は本物（`DEPLOY_PATHS`・`NOT_DEPLOYED`）を当てる。
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "deploy_backend_gate", Path(__file__).resolve().parents[2] / "scripts" / "deploy_backend_gate.py"
)
gate = importlib.util.module_from_spec(_SPEC)
sys.modules["deploy_backend_gate"] = gate
_SPEC.loader.exec_module(gate)


@pytest.mark.parametrize(
    ("relation", "hits", "expected"),
    [
        ("unknown", [], True),
        ("same", ["backend/app/main.py"], False),
        ("older", ["backend/app/main.py"], False),
        ("diverged", [], True),
        ("newer", [], False),
        ("newer", ["backend/app/main.py"], True),
    ],
)
def test_decide(relation, hits, expected):
    assert gate.decide(relation, hits)[0] is expected


def _commit(repo: Path, *names: str) -> str:
    for name in names:
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(name, encoding="utf-8")
    subprocess.run(["git", "add", *names], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", names[0]],
        cwd=repo,
        check=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_relation_reads_ancestry(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    first = _commit(tmp_path, "a")
    second = _commit(tmp_path, "b")
    subprocess.run(["git", "checkout", "-q", "-b", "side", first], cwd=tmp_path, check=True)
    side = _commit(tmp_path, "c")
    monkeypatch.chdir(tmp_path)

    assert gate.commit_relation("", second) == "unknown"
    assert gate.commit_relation("0" * 40, second) == "unknown"
    assert gate.commit_relation(second, second) == "same"
    assert gate.commit_relation(second, first) == "older"
    assert gate.commit_relation(first, second) == "newer"
    assert gate.commit_relation(second, side) == "diverged"


def test_only_changes_that_reach_the_image_deploy(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    deployed = _commit(tmp_path, "README.md")
    # 外したものと対象の外（根から当てるので、下の階層にある同じ名前のディレクトリも外）だけが変わった。
    unchanged_image = _commit(
        tmp_path,
        "backend/tests/test_x.py",
        "backend/benchmarks/deep/bench.py",
        "backend/app/domain/map_display.py",
        "frontend/backend/app.py",
        "docs/a.md",
    )
    changed_image = _commit(tmp_path, "backend/app/main.py")
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.chdir(tmp_path / "backend")  # 当てる先は作業ディレクトリによらずリポジトリの根から

    assert gate.main(["gate", deployed, unchanged_image]) == 0
    assert gate.main(["gate", deployed, changed_image]) == 0
    assert output.read_text(encoding="utf-8").splitlines() == ["deploy=false", "deploy=true"]
