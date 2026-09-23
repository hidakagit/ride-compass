"""`scripts/deploy_backend_gate.py`の判定テスト（本番・ネットワークには触れない）。

照合の規則はGitHubの`paths`と同じ（上から当て、最後に当たったものが勝つ。`*`は`/`を跨がず、
`**`は跨ぐ）。本物の一覧ではなく、規則を確かめるための一覧で当てる。
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

PATTERNS = ("app/**", "!app/tests/**", "!app/*.ini", "app/tests/keep.py", "ci.yml")


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("app/main.py", True),
        ("app/deep/er/x.py", True),
        ("app/tests/test_x.py", False),  # 後の否定が勝つ
        ("app/tests/keep.py", True),  # さらに後の肯定が勝つ
        ("app/pytest.ini", False),
        ("app/sub/pytest.ini", True),  # `*`は`/`を跨がない
        ("ci.yml", True),
        ("docs/ci.yml", False),  # 先頭から当てる
        ("frontend/app/main.py", False),
    ],
)
def test_matches_follows_github_paths_rules(path, expected):
    assert gate.matches(path, PATTERNS) is expected


def test_pattern_with_symbols_of_other_meaning_is_rejected():
    with pytest.raises(ValueError):
        gate.matches("app/a.py", ("app/?.py",))


@pytest.mark.parametrize(
    ("relation", "changed", "expected"),
    [
        ("unknown", [], True),
        ("same", ["app/main.py"], False),
        ("older", ["app/main.py"], False),
        ("diverged", [], True),
        ("newer", ["app/tests/test_x.py", "docs/a.md"], False),
        ("newer", ["docs/a.md", "app/main.py"], True),
    ],
)
def test_decide(relation, changed, expected):
    assert gate.decide(relation, changed, PATTERNS)[0] is expected


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name, encoding="utf-8")
    subprocess.run(["git", "add", name], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", name],
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

    assert gate._relation("", second) == "unknown"
    assert gate._relation("0" * 40, second) == "unknown"
    assert gate._relation(second, second) == "same"
    assert gate._relation(second, first) == "older"
    assert gate._relation(first, second) == "newer"
    assert gate._relation(second, side) == "diverged"
