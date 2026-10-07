"""`scripts/review_checks.py`の差分の報告（`change`）と総量（`metrics`）のテスト。

履歴は一時的なgitリポジトリで作る。

ここで見ないもの: `docs`はCI（Docs Consistency）が本物のリポジトリへ毎回流す。`trigger`と、`size`の表・発火は
周期レビューで人が読む出力で、ここでは通さない。`size`の「閾値の見直し」は、緩んだ閾値に誰も気づかなくなるので通す。
"""

import argparse
import sys
from pathlib import Path

import pytest

from tests.git_repo import git
from tests.script_module import load_script

rc = load_script("review_checks")


def _commit(repo: Path, files: dict[str, str | None]) -> str:
    for name, text in files.items():
        path = repo / name
        if text is None:
            git(repo, "rm", "-q", name)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        git(repo, "add", name)
    git(repo, "commit", "-q", "-m", "c")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q", "-b", "master")
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
            "backend/app/batch/source_profile.yaml": "y\n" * 3,
            "frontend/src/types/generated/api.d.ts": "g\n" * 7,
            "frontend/package-lock.json": "{}\n",
        },
    )
    head = _commit(repo, {"app/moved_from.py": None, "app/moved_to.py": "m\n" * 10 + "n\n"})

    out = _run(monkeypatch, capsys, "change", "--base", base, "--head", head)

    # 移したファイルは移す前と後の差だけを数える（+1）。ワークフローは総量と同じく実装、コードでないファイルは設定。
    assert "増減: 実装 +16/−2・テスト +4/−0・文書 +3/−0・設定 +3/−0・生成物 +8/−0" in out
    assert "規模: S（実装＋テスト 22行。" in out


@pytest.mark.parametrize(("lines", "label"), [(200, "S"), (201, "M"), (1000, "M"), (1001, "L")])
def test_change_counts_the_working_tree_with_untracked_files(repo, monkeypatch, capsys, lines, label):
    base = _commit(repo, {"README.md": "x\n"})
    git(repo, "checkout", "-q", "-b", "work")
    (repo / "app.py").write_text("a\n" * lines, encoding="utf-8")

    out = _run(monkeypatch, capsys, "change", "--base", base)

    assert f"増減: 実装 +{lines:,}/−0・テスト +0/−0・文書 +0/−0" in out
    assert f"規模: {label}（" in out


def test_metrics_counts_everything_outside_the_product_places_as_tooling(repo, capsys):
    _commit(repo, {"backend/app/a.py": "a\n", "frontend/src/b.ts": "b\n"})
    git(repo, "tag", "-a", "periodic-review/001", "-m", "r")
    (repo / "stop-dev.bat").write_bytes("rem 止める\r\n".encode("cp932") * 2)
    git(repo, "add", "stop-dev.bat")
    _commit(
        repo,
        {
            "tools/flow-gate/src/gate.js": "g\n" * 3,
            "tools/flow-gate/test/fake-github.js": "f\n" * 4,
            ".github/workflows/claude-task.yml": "c\n" * 5,
            ".github/workflows/ci.yml": "w\n" * 6,
            ".github/dependabot.yml": "d\n" * 7,
            "frontend/scripts/capture.mjs": "s\n" * 8,
            "frontend/src/testing/maplibre.ts": "m\n" * 9,
        },
    )

    assert rc.cmd_metrics(argparse.Namespace()) == 0
    out = capsys.readouterr().out

    assert "| 実装 | 26 | 2 | +24 |" in out
    assert "| うち製品 | 2 | 2 | +0 |" in out
    assert "| うちタスク管理 | 8 | 0 | +8 |" in out
    assert "| うち道具 | 16 | 0 | +16 |" in out
    assert "| テスト | 13 | 0 | +13 |" in out


_DECLARED_PREFIXES = sorted(
    {prefix for name, value in vars(rc).items() if name.endswith("_PREFIXES") for prefix in value}
)


@pytest.mark.parametrize("prefix", _DECLARED_PREFIXES)
def test_each_declared_place_holds_a_tracked_file(prefix):
    """置き場を改名・撤去すると、その置き場で分けていたファイルが黙って別の種別へ落ちる。"""
    assert any(f.startswith(prefix) for f in rc.tracked_files()), f"{prefix} に当たる追跡ファイルが無い"


def test_size_lists_thresholds_looser_than_the_growth_from_the_current_lines(repo, monkeypatch, capsys):
    # 縮んだファイルの閾値が、今の行数から増える側の発火（+15%）で付け直す値より緩ければ見直しに出す。
    _commit(repo, {"app/shrunk.py": "a\n" * 400, "app/kept.py": "b\n" * 400})
    thresholds = repo / "size_thresholds.json"
    thresholds.write_text('{"thresholds": {"app/shrunk.py": 800, "app/kept.py": 500}}', encoding="utf-8")
    monkeypatch.setattr(rc, "SIZE_THRESHOLDS", thresholds)

    assert rc.cmd_size(argparse.Namespace(top=5)) == 0
    out = capsys.readouterr().out

    assert "閾値の見直し（今の行数+15%を100行に切り上げた値より緩い・削除済み） 1件: app/shrunk.py（800→500）" in out
