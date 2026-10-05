"""`scripts/break_tests.py`のテスト。

一時の git リポジトリに backend の形（`backend/calc.py` とそのテスト）を作り、git と pytest は本物を通す。

ここで見ないもの: frontend の側を回すこと（vitest は frontend の依存が要る。読む報告の形は `vitest_failures` で見る）と、
道具の実行口（`main`）。
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "break_tests", Path(__file__).resolve().parents[2] / "scripts" / "break_tests.py"
)
bt = importlib.util.module_from_spec(_SPEC)
sys.modules["break_tests"] = bt
_SPEC.loader.exec_module(bt)

_CALC = 'def sign(x):\n    return "neg" if x < 0 else "pos"\n'
_NEGATIVE = 'from calc import sign\n\n\ndef test_negative():\n    assert sign(-1) == "neg"\n'
_BOTH = _NEGATIVE + '\n\ndef test_positive():\n    assert sign(1) == "pos"\n'


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo, check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout.strip()


def _commit(repo: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
        _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", "c")


@pytest.fixture
def repo(tmp_path):
    """前の版（HEAD~1）は正負の両方を見るテスト、今の版（HEAD）は負だけを見るテストを持つ。"""
    _git(tmp_path, "init", "-q", "-b", "master")
    _commit(tmp_path, {"backend/calc.py": _CALC, "backend/tests/test_calc.py": _BOTH})
    _commit(tmp_path, {"backend/tests/test_calc.py": _NEGATIVE})
    return tmp_path


def _entry(before: str, after: str, **overrides) -> dict:
    return {"name": "壊れ方", "file": "backend/calc.py", "before": before, "after": after,
            "tests": ["backend/tests/test_calc.py"], **overrides}


def _run(repo: Path, entries: list[dict], ref: str | None = None) -> int:
    return bt.run(repo, bt.load(repo, entries), ref)


def test_names_the_failed_tests_and_restores_the_implementation(repo, capsys):
    code = _run(repo, [_entry("x < 0", "x > 0")])

    out = capsys.readouterr().out
    assert code == 0
    assert "backend/tests/test_calc.py > test_negative" in out
    assert "落ちなかった件: なし" in out
    assert (repo / "backend/calc.py").read_text(encoding="utf-8") == _CALC
    assert _git(repo, "status", "--short") == ""


def test_a_breakage_no_test_catches_is_listed_and_exits_1(repo, capsys):
    code = _run(repo, [_entry("x < 0", "x > 0"), _entry('else "pos"', 'else "POS"', name="正の側")])

    assert code == 1
    assert "落ちなかった件: [2] 正の側" in capsys.readouterr().out


def test_ref_runs_the_old_tests_beside_and_removes_them(repo, capsys):
    code = _run(repo, [_entry('else "pos"', 'else "POS"')], ref="HEAD~1")

    out = capsys.readouterr().out
    assert code == 1
    assert "落ちた（作業ツリーのテスト）: 0本" in out
    assert "落ちた（HEAD~1 のテスト）: 1本\n    backend/tests/test_calc.py > test_positive" in out
    assert _git(repo, "status", "--short") == ""


@pytest.mark.parametrize(
    ("entry", "reason"),
    [
        (_entry("x <= 0", "x > 0"), "0回現れる"),
        (_entry('"', "'"), "4回現れる"),
        (_entry("x < 0", "x > 0", tests=["backend/tests/test_calc.py", "frontend/a.test.ts"]), "片方だけ"),
        (_entry("x < 0", "x > 0", tests=["backend/tests/test_missing.py"]), "テストのファイルが無い"),
        ({"name": "欄の欠け", "file": "backend/calc.py"}, "欄が無い: before, after, tests"),
    ],
)
def test_an_entry_that_does_not_fit_refuses_the_whole_list(repo, entry, reason):
    with pytest.raises(bt.Refused, match=reason):
        bt.load(repo, [_entry("x < 0", "x > 0"), entry])


def test_an_implementation_changed_from_head_is_refused(repo):
    (repo / "backend/calc.py").write_text(_CALC + "\n", encoding="utf-8")

    with pytest.raises(bt.Refused, match="HEAD から変わっている"):
        bt.load(repo, [_entry("x < 0", "x > 0")])


def test_tests_failing_before_breaking_refuse_and_leave_the_implementation(repo):
    _commit(repo, {"backend/tests/test_calc.py": _NEGATIVE + "\n\ndef test_broken():\n    assert False\n"})

    with pytest.raises(bt.Refused, match="壊す前に落ちる"):
        _run(repo, [_entry("x < 0", "x > 0")])
    assert _git(repo, "status", "--short") == ""


def test_vitest_report_gives_failed_tests_and_files_that_failed_to_load(tmp_path):
    frontend = tmp_path / "frontend"
    report = {"testResults": [
        {"name": str(frontend / "src/a.test.ts"), "status": "failed", "assertionResults": [
            {"ancestorTitles": ["a"], "title": "落ちる", "status": "failed"},
            {"ancestorTitles": ["a"], "title": "通る", "status": "passed"},
        ]},
        {"name": str(frontend / "src/b.test.ts"), "status": "failed", "message": "Transform failed\nat b.ts",
         "assertionResults": []},
    ]}

    assert bt.vitest_failures(report, frontend) == [
        ("frontend/src/a.test.ts", "a > 落ちる"),
        ("frontend/src/b.test.ts", "（ファイルが落ちた）Transform failed"),
    ]
