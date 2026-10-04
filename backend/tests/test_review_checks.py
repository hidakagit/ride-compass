"""`scripts/review_checks.py`の差分の報告（`change`）と総量（`metrics`）のテスト。

履歴は一時的なgitリポジトリで作る。

ここで見ないもの: `docs`はCI（Docs Consistency）が本物のリポジトリへ毎回流す。`size`・`trigger`は周期レビューで
人が読む出力で、ここでは通さない。
"""

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "review_checks", Path(__file__).resolve().parents[2] / "scripts" / "review_checks.py"
)
rc = importlib.util.module_from_spec(_SPEC)
sys.modules["review_checks"] = rc
_SPEC.loader.exec_module(rc)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _commit(repo: Path, files: dict[str, str | None]) -> str:
    for name, text in files.items():
        path = repo / name
        if text is None:
            _git(repo, "rm", "-q", name)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", "c")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q", "-b", "master")
    monkeypatch.setattr(rc, "REPO_ROOT", tmp_path)
    return tmp_path


def _run(monkeypatch, capsys, *argv: str) -> str:
    monkeypatch.setattr(sys, "argv", ["review_checks.py", *argv])
    assert rc.main() == 0
    return capsys.readouterr().out


def test_change_splits_lines_by_kind_and_labels_the_size(repo, monkeypatch, capsys):
    base = _commit(repo, {"app/old.py": "a\nb\nc\n", "README.md": "x\n"})
    _commit(
        repo,
        {
            "app/old.py": "a\n",
            "app/moved_from.py": "m\n" * 10,
            "backend/tests/test_x.py": "t\n" * 4,
            "docs/a.md": "d\n" * 3,
            ".github/workflows/ci.yml": "w\n" * 5,
            "frontend/src/types/generated/api.d.ts": "g\n" * 7,
            "frontend/package-lock.json": "{}\n",
        },
    )
    head = _commit(repo, {"app/moved_from.py": None, "app/moved_to.py": "m\n" * 10 + "n\n"})

    out = _run(monkeypatch, capsys, "change", "--base", base, "--head", head)

    # 移したファイルは移す前と後の差だけを数える（+1）。
    assert "増減: 実装 +11/−2・テスト +4/−0・文書 +3/−0・設定 +5/−0・生成物 +8/−0" in out
    assert "規模: S（実装＋テスト 17行。" in out


@pytest.mark.parametrize(("lines", "label"), [(200, "S"), (201, "M"), (1000, "M"), (1001, "L")])
def test_change_counts_the_working_tree_with_untracked_files(repo, monkeypatch, capsys, lines, label):
    base = _commit(repo, {"README.md": "x\n"})
    _git(repo, "checkout", "-q", "-b", "work")
    (repo / "app.py").write_text("a\n" * lines, encoding="utf-8")

    out = _run(monkeypatch, capsys, "change", "--base", base)

    assert f"増減: 実装 +{lines:,}/−0・テスト +0/−0・文書 +0/−0" in out
    assert f"規模: {label}（" in out


def test_metrics_counts_task_tools_and_workflows_apart_from_product(repo, capsys):
    _commit(repo, {"backend/app/a.py": "a\n"})
    _git(repo, "tag", "-a", "periodic-review/001", "-m", "r")
    (repo / "stop-dev.bat").write_bytes("rem 止める\r\n".encode("cp932") * 2)
    _git(repo, "add", "stop-dev.bat")
    _commit(
        repo,
        {
            "tools/flow-gate/src/gate.js": "g\n" * 3,
            "tools/flow-gate/test/fake-github.js": "f\n" * 4,
            ".github/workflows/claude-task.yml": "c\n" * 5,
            ".github/workflows/ci.yml": "w\n" * 6,
            ".github/dependabot.yml": "d\n" * 7,
        },
    )

    assert rc.cmd_metrics(argparse.Namespace()) == 0
    out = capsys.readouterr().out

    assert "| 実装 | 17 | 1 | +16 |" in out
    assert "| うち製品 | 1 | 1 | +0 |" in out
    assert "| うちタスク管理 | 8 | 0 | +8 |" in out
    assert "| うち道具 | 8 | 0 | +8 |" in out
    assert "| テスト | 4 | 0 | +4 |" in out
