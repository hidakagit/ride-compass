"""`scripts/hooks/japanese_only.py`のテスト。

フックは Claude Code が標準入力で JSON を渡して打つので、同じく別のプロセスで打って出力を見る。

ここで見ないもの: 英語の文の見分け方（仮名・漢字・語の数）の細かな境界。
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / "scripts" / "hooks" / "japanese_only.py"
ENGLISH = "I have finished the refactoring of the module."


def _run(hook_input: dict) -> str:
    return subprocess.run(
        [sys.executable, str(HOOK)], input=json.dumps(hook_input), check=True,
        capture_output=True, text=True, encoding="utf-8",
    ).stdout


@pytest.mark.parametrize("active, blocked", [(False, True), (True, False)])
def test_stop_blocks_english_unless_a_stop_hook_already_continued(active, blocked):
    """止めて書き直させた続きの手番（`stop_hook_active`）では止めない。止め続けると手番が終わらない。"""
    out = _run({"hook_event_name": "Stop", "stop_hook_active": active, "last_assistant_message": ENGLISH})
    assert (json.loads(out)["decision"] == "block") if blocked else out == ""


def test_pre_tool_use_reads_text_at_the_end_of_a_large_transcript(tmp_path):
    """記録が大きくても、道具の直前に書いた英語の文を見つけて止める（記録は末尾から塊で読む）。"""
    filler = {"type": "assistant", "message": {"content": [{"type": "text", "text": "日本語の文。" * 200}]}}
    entries = [filler] * 2000 + [
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "結果"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": ENGLISH}]}},
    ]
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")

    out = _run({"hook_event_name": "PreToolUse", "transcript_path": str(transcript)})

    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"
