"""review_checks.py の経緯コメント検知のテスト。

この検知器は pre-commit と CI が「新規混入を機械的にブロックする」根拠になっている
（docs/comments.md「機械的な強制」）。検知できない書き方があると、止まっているつもりで
素通りし続けるため、**過去に実際にすり抜けた形**を回帰として固定する。

実行: backend/.venv/Scripts/python.exe -m pytest scripts/tests/test_review_checks.py -q
"""

import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "review_checks", Path(__file__).resolve().parents[1] / "review_checks.py"
)
review_checks = importlib.util.module_from_spec(_SPEC)
sys.modules["review_checks"] = review_checks
_SPEC.loader.exec_module(review_checks)


def _violations(path: str, lines: list[tuple[int, str]]) -> list[str]:
    return review_checks.find_source_narrative_violations({path: lines})


class TestNarrativePattern:
    """パターンが拾えずすり抜けた実例。"""

    def test_kaizen_keikaku_followed_by_punctuation(self):
        # 「改善計画T572。」（句点）・「改善計画T87/T606」（スラッシュ）・「改善計画T278、」（読点）は
        # かつて `改善計画T[0-9]+で|[:：]` しか要求していなかったため素通りしていた。
        for text in ("改善計画T572。basemap.pyと同じ方式", "改善計画T87/T606", "改善計画T278、例: 舗装質"):
            assert review_checks.NARRATIVE_PATTERN.search(text), text

    def test_paraphrases_that_slipped_through(self):
        for text in ("旧実装は昇順制約に違反していた", "旧デザインは直方体の軸", "ユーザーからの明示許可"):
            assert review_checks.NARRATIVE_PATTERN.search(text), text

    def test_current_tense_constraints_are_not_flagged(self):
        # 現在形の制約表現は経緯ではないため検出しない（誤検出すると書けなくなる）。
        for text in ("このロックはXがYから並列に呼ばれるため必要", "配信元は要素ごとにzoomUseを持つ"):
            assert not review_checks.NARRATIVE_PATTERN.search(text), text


class TestPythonDocstring:
    """Pythonの説明文は大半がdocstringにあるが、以前は`#`しか見ていなかった。"""

    def test_module_docstring_is_scanned(self, tmp_path):
        f = tmp_path / "m.py"
        f.write_text('"""説明。\n\n改善計画T999。以前はこうだった。\n"""\n\nX = 1\n', encoding="utf-8")
        out = _violations(str(f), [(3, "改善計画T999。以前はこうだった。")])
        assert len(out) == 1, out

    def test_function_docstring_is_scanned(self, tmp_path):
        f = tmp_path / "m.py"
        f.write_text('def f():\n    """実測で0.2秒だった。"""\n    return 1\n', encoding="utf-8")
        assert len(_violations(str(f), [(2, '    """実測で0.2秒だった。"""')])) == 1

    def test_hash_comment_still_works(self, tmp_path):
        f = tmp_path / "m.py"
        f.write_text("# 以前はこうだった\nX = 1\n", encoding="utf-8")
        assert len(_violations(str(f), [(1, "# 以前はこうだった")])) == 1

    def test_code_line_is_not_flagged(self, tmp_path):
        # 文字列リテラルに同じ語が入っていても、コメント/docstringでなければ検出しない。
        f = tmp_path / "m.py"
        f.write_text('MESSAGE = "以前は取得できました"\n', encoding="utf-8")
        assert _violations(str(f), [(1, 'MESSAGE = "以前は取得できました"')]) == []


class TestCssModules:
    """CSS Modulesは設計意図を長文コメントで書く運用だが、以前はパス対象外だった。"""

    def test_block_comment_is_scanned(self, tmp_path):
        f = tmp_path / "a.module.css"
        assert len(_violations(str(f), [(1, "/* ユーザー要望「まとめて1ボタンで」 */")])) == 1

    def test_multiline_block_continuation_is_scanned(self, tmp_path):
        f = tmp_path / "a.module.css"
        out = _violations(str(f), [(1, "/* 全レイヤー一括OFF"), (2, "   実機フィードバックで左上から移設）。 */")])
        assert len(out) == 1, out

    def test_declaration_is_not_flagged(self, tmp_path):
        f = tmp_path / "a.module.css"
        assert _violations(str(f), [(1, "  color: var(--foreground);")]) == []


def test_css_is_in_pathspecs():
    assert any("css" in spec for spec in review_checks.SOURCE_COMMENT_PATHSPECS)

# --- docs/tasks の「状態:」行の分類（improvement-plan.mdの[x]/[ ]との照合の土台） ---


_task_file_seq = 0


def _task_file(tmp_path, body: str):
    # 1テスト内で複数作るため名前を重複させない（同名だと後の書き込みが前のを上書きし、
    # 先に作ったパスを検証しているつもりで後の内容を見ることになる）。
    global _task_file_seq
    _task_file_seq += 1
    path = tmp_path / f"T{900 + _task_file_seq}.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_task_status_kind_reads_a_line_starting_with_the_marker(tmp_path):
    done = _task_file(tmp_path, """# T999

規模S。

状態: 完了（2026-09-08）
""")
    assert review_checks.task_status_kind(done) == "done"

    open_ = _task_file(tmp_path, """# T999

規模S。

状態: 未着手（起票のみ）
""")
    assert review_checks.task_status_kind(open_) == "open"


def test_task_status_kind_returns_none_when_the_marker_is_not_at_line_head(tmp_path):
    # 実際にすり抜けた形。規模と同じ行へ畳むと照合対象から外れ、[x]との不一致が
    # 検知されないまま残る（この戻り値がNoneのときcheck_plan_vs_tasksが違反を上げる）。
    folded = _task_file(tmp_path, """# T999

規模S。状態: 完了（2026-09-08）。
""")
    assert review_checks.task_status_kind(folded) is None


def test_task_status_kind_treats_deferred_as_closed_and_on_hold_as_open(tmp_path):
    # 「見送り」は今後もやらない確定判断でimprovement-plan側は[x]、トリガー待ちの
    # 「保留」は[ ]（CLAUDE.md「コミット時の同期ルール」6番の用語法）。
    deferred = _task_file(tmp_path, "状態: 見送り（ユーザー判断で現状維持）")
    on_hold = _task_file(tmp_path, "状態: 保留（トリガー成立まで着手しない）")

    assert review_checks.task_status_kind(deferred) == "done"
    assert review_checks.task_status_kind(on_hold) == "open"
