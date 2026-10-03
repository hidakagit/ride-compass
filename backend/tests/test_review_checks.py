"""`scripts/review_checks.py`の差分の報告（`leftovers`・`change`）のテスト。

履歴は一時的なgitリポジトリで作り、置き場（GitHub）の読み取りだけを差し替える。
"""

import importlib.util
import json
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


def _config(**coordinator) -> str:
    return json.dumps({"repository": "o/tasks", "coordinator": {"stopLabel": "停止", **coordinator}})


def test_leftovers_names_what_still_points_at_removed_names(repo, monkeypatch, capsys):
    base = _commit(
        repo,
        {
            "docs/flow.md": "# 流れ\n\n## 司令塔と担当（自分の番を進める）\n\n手順。\n",
            "scripts/heavy.py": '"""重い処理（docs/flow.md「司令塔と担当」）。"""\n',
            "tools/flow-gate/flow.config.json": _config(dropMinutes=240),
            "tools/flow-gate/bin/slots.js": "export function recordPid() {}\n",
            "tools/flow-gate/src/status.js": "// 司令塔の見張り。\nexport function watchCoordinator() {}\nexport const A = 1;\n",
            "tools/flow-gate/bin/watch.js": 'import { watchCoordinator } from "../src/status.js";\n',
            "docs/records/old.md": "slots.js と司令塔の記録。\n",
        },
    )
    head = _commit(
        repo,
        {
            "docs/flow.md": "# 流れ\n\n## 担当（自分の番を進める）\n\nラベル「開発機が要る」で分ける。\n",
            "tools/flow-gate/flow.config.json": _config(devLabel="開発機が要る"),
            "tools/flow-gate/bin/slots.js": None,
            "tools/flow-gate/src/status.js": "export const A = 1;\n",
            "docs/how.md": "`bin/slots.js` で枠を取る。\n",
        },
    )
    tasks = (
        [{"name": "停止", "description": "司令塔は振り出さない"}],
        [
            {
                "number": 5,
                "title": "t",
                "body": "背景\n`dropMinutes` を延ばす\n",
                "comments": [{"url": "https://c/1", "body": "slots.js の鍵"}],
            }
        ],
    )
    monkeypatch.setattr(rc, "read_tasks_repo", lambda name: tasks if name == "o/tasks" else (None, None))

    out = _run(monkeypatch, capsys, "leftovers", "--base", base, "--head", head)

    assert "ファイル tools/flow-gate/bin/slots.js（探した語: slots.js）" in out
    assert "見出し docs/flow.md「司令塔と担当（自分の番を進める）」" in out
    assert "設定の項目 tools/flow-gate/flow.config.json: coordinator.dropMinutes" in out
    assert "定義 tools/flow-gate/src/status.js: watchCoordinator" in out
    assert "scripts/heavy.py:1: 「司令塔と担当」" in out
    assert "docs/how.md:1: 「slots.js」" in out
    assert "tools/flow-gate/bin/watch.js:1: 「watchCoordinator」" in out
    assert "置き場のラベル「停止」の説明: 「司令塔」" in out
    assert "置き場 #5 の本文 2行目: 「dropMinutes」" in out
    assert "置き場 #5 のコメント https://c/1 1行目: 「slots.js」" in out
    assert "- tools/flow-gate/src/status.js: // 司令塔の見張り。" in out
    assert "「開発機が要る」（tools/flow-gate/flow.config.json: coordinator.devLabel）" in out
    # 記録は維持しないので当てない。今も見出しにある語（「担当」）・残った定義（A）は名前に数えない。
    assert "docs/records" not in out
    assert "探した語: 司令塔と担当（自分の番を進める）・司令塔と担当・司令塔）" in out
    assert ": A（" not in out


def test_leftovers_names_private_constants_and_attributes_dropped_from_a_class(repo, monkeypatch, capsys):
    base = _commit(
        repo,
        {
            "config.py": (
                "_MARGIN_KM = 1\n\n"
                "class Settings:\n    kept: int = 1\n    gone_limit: int = 2\n\n"
                "    def f(self):\n        local_value: int = 3\n        return local_value\n\n"
                "class Dropped:\n    dropped_field: int = 4\n"
            ),
        },
    )
    head = _commit(
        repo,
        {
            "config.py": "class Settings:\n    kept: int = 1\n\n    def f(self):\n        return 3\n",
            "use.py": "settings.gone_limit\n_MARGIN_KM\ndropped_field\nlocal_value\n",
        },
    )
    monkeypatch.setattr(rc, "read_tasks_repo", lambda name: (None, None))

    out = _run(monkeypatch, capsys, "leftovers", "--base", base, "--head", head)

    assert "定義 config.py: _MARGIN_KM" in out
    assert "定義 config.py: gone_limit" in out
    assert "use.py:1: 「gone_limit」" in out
    assert "use.py:2: 「_MARGIN_KM」" in out
    # 消したクラスはクラスの名前で探すので属性を数えず、関数の中の変数も数えない。
    assert "定義 config.py: Dropped" in out
    assert "dropped_field" not in out
    assert "local_value" not in out


def test_leftovers_says_when_the_tasks_repository_could_not_be_read(repo, monkeypatch, capsys):
    base = _commit(repo, {"tools/flow-gate/flow.config.json": _config(), "a.py": "def gone():\n    pass\n"})
    head = _commit(repo, {"a.py": "x = 1\n", "b.py": "gone()\n"})
    monkeypatch.setattr(rc, "read_tasks_repo", lambda name: (None, None))

    out = _run(monkeypatch, capsys, "leftovers", "--base", base, "--head", head)

    assert "b.py:1: 「gone」" in out
    assert "置き場のラベル・開いた issueを読めなかった" in out
    assert "置き場（o/tasks）に無いラベル" not in out


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
