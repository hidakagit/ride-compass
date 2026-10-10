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


def _run(hook_input: dict, scratchpad: Path | None = None) -> str:
    if scratchpad is not None:
        hook_input = {"session_id": "s", "scratchpad_dir": str(scratchpad), **hook_input}
    return subprocess.run(
        [sys.executable, str(HOOK)], input=json.dumps(hook_input), check=True,
        capture_output=True, text=True, encoding="utf-8",
    ).stdout


@pytest.mark.parametrize("active, blocked", [(False, True), (True, False)])
def test_stop_blocks_english_unless_a_stop_hook_already_continued(active, blocked, tmp_path):
    """止めて書き直させた続きの手番（`stop_hook_active`）では止めない。止め続けると手番が終わらない。"""
    out = _run({"hook_event_name": "Stop", "stop_hook_active": active, "last_assistant_message": ENGLISH}, tmp_path)
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

    out = _run({"hook_event_name": "PreToolUse", "transcript_path": str(transcript)}, tmp_path)

    assert _denied(out)


def _denied(out: str) -> bool:
    return out != "" and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


def _transcript(tmp_path: Path, text: str | None) -> str:
    """前の道具の結果で終わる記録（text があれば、そのあとに書いた文を足す）。"""
    entries = [{"type": "user", "message": {"content": [{"type": "tool_result", "content": "結果"}]}}]
    if text is not None:
        entries.append({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})
    path = tmp_path / "transcript.jsonl"
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")
    return str(path)


def _display(tmp_path: Path, *deltas: str) -> None:
    for index, delta in enumerate(deltas):
        _run({"hook_event_name": "MessageDisplay", "message_id": "m", "index": index,
              "final": index == len(deltas) - 1, "delta": delta}, tmp_path)


def test_displayed_english_missing_from_the_transcript_stops_the_next_tool_once(tmp_path):
    """記録が遅れて道具の直前の文が無くても、画面に出した英語の文で次の道具を止める。止めたあとの打ち直しは通る。"""
    _display(tmp_path, f"{ENGLISH}\n")
    pre = {"hook_event_name": "PreToolUse", "transcript_path": _transcript(tmp_path, None)}

    assert [_denied(_run(pre, tmp_path)), _denied(_run(pre, tmp_path))] == [True, False]


def test_english_already_stopped_from_the_transcript_is_not_stopped_again_when_displayed_late(tmp_path):
    """記録で止めた文が、あとから画面の出来事で届いても、次の道具を二度止めない。"""
    first = _run({"hook_event_name": "PreToolUse", "transcript_path": _transcript(tmp_path, ENGLISH)}, tmp_path)
    _display(tmp_path, ENGLISH)
    second = _run({"hook_event_name": "PreToolUse", "transcript_path": _transcript(tmp_path, "書き直した。")}, tmp_path)

    assert [_denied(first), _denied(second)] == [True, False]


def test_displayed_code_block_split_across_batches_is_not_english(tmp_path):
    """画面の塊の境目がコードブロックの中に来ても、ブロックの中の英語は止めない。"""
    _display(tmp_path, "例:\n```\n", f"# {ENGLISH}\n", "```\n")

    assert not _denied(_run({"hook_event_name": "PreToolUse", "transcript_path": _transcript(tmp_path, None)}, tmp_path))


def test_stop_blocks_displayed_english_that_no_tool_stopped(tmp_path):
    """道具を挟まずに手番を終えても、途中で画面に出した英語の文があれば終わらせない。"""
    _display(tmp_path, ENGLISH)

    out = _run({"hook_event_name": "Stop", "stop_hook_active": False, "last_assistant_message": "終えた。"}, tmp_path)

    assert json.loads(out)["decision"] == "block"
