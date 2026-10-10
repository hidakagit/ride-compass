"""テストが派生の表へ行を直接書かないことの検査（.claude/rules/testing-backend.md パターン8）。

派生の表は本番では派生の段だけが書く。テストが直接書くと、段では作れない行（標高の無い区間の勾配等）ができ、
その行に合わせた読み手の分岐がテストだけで緑のまま残る。段を通して作れば、表の制約が段の書く値に締まっても
テストが本番と同じ行で確かめ続ける。

母集団はソースから導く（`backend/tests`配下の全`.py`の文に現れる、派生の表（`derived_tables()`）への
`INSERT INTO`・`UPDATE`・`DELETE FROM`）。表の名前を文字列の連結や変数で組み立てた文は拾わない。
直接書いてよいファイルは下に列挙し、**列挙が古くなったらこのテスト自身が落ちる**ようにしてある。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.infrastructure.derived_data_freshness import derived_tables

TESTS_ROOT = Path(__file__).resolve().parent.parent

# 派生の表へ直接書いてよいファイルと、その理由。
ALLOWED = {
    "test_declared_constraints.py": "段が書かない行を表の制約が断ることを見る（書いた行は巻き戻す）",
}


def _write_pattern() -> re.Pattern[str]:
    tables = "|".join(re.escape(table.name) for table in derived_tables())
    return re.compile(rf"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+\"?(?:{tables})\b", re.IGNORECASE)


def files_writing_derived_tables(root: Path) -> set[str]:
    pattern = _write_pattern()
    return {path.relative_to(root).as_posix() for path in sorted(root.rglob("*.py"))
            if pattern.search(path.read_text(encoding="utf-8"))}


def test_tests_do_not_write_derived_tables() -> None:
    unexpected = sorted(files_writing_derived_tables(TESTS_ROOT) - ALLOWED.keys())
    assert unexpected == [], (
        "派生の表へ行を直接書いているテストがある（生データを取込の入口から入れ、派生の段を通して作ること。"
        "testing-backend.md パターン8）:\n  " + "\n  ".join(unexpected)
    )


def test_allowlist_has_no_stale_entries() -> None:
    """直接書かなくなったファイルが列挙に残り続けないこと。"""
    stale = sorted(ALLOWED.keys() - files_writing_derived_tables(TESTS_ROOT))
    assert stale == [], "派生の表へ書いていないのにALLOWEDへ残っている:\n  " + "\n  ".join(stale)


def test_detects_a_direct_write(tmp_path: Path) -> None:
    """検査が効いていること（わざと1件置いて捕まえる）。"""
    table = derived_tables()[0].name
    (tmp_path / "test_sample.py").write_text(f'SQL = "update {table} SET x = 1"\n', encoding="utf-8")

    assert files_writing_derived_tables(tmp_path) == {"test_sample.py"}
