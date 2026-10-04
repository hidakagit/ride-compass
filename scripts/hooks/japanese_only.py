"""Claude の文に英語の文があれば、先へ進ませずに日本語で書き直させるフック（CLAUDE.md「出力言語」を機械で守る）。

.claude/settings.json の hooks から、次の出来事で打つ（標準入力でフックの JSON を受け取る。公式「Hooks reference」）:
- Stop・SubagentStop: その手番の最後の文（`last_assistant_message`）を見る。英語の文があれば終わらせない（`decision: block`）。
- PreToolUse: 道具を打つ直前に書いた文（記録 `transcript_path` の、前の道具の結果より後に書いた文の塊）を見る。英語の文があれば
  その道具を打たせない（`permissionDecision: deny`）。書き直した文が記録に足されると、次の打ち直しは通る。

英語の文とは、仮名・漢字を1字も含まず、英字だけの語が5つ以上並ぶ行。コードブロック・`で囲んだもの・URL は見ない
（コマンド・ファイル名・コードは英語のままでよい）。
"""

import json
import re
import sys

JAPANESE = re.compile(r"[぀-ヿ㐀-鿿ｦ-ﾟ]")
WORD = re.compile(r"(?<![\w/.#@-])[A-Za-z]{2,}(?![\w/.#@-])")
MIN_WORDS = 5


def english_lines(text: str) -> list[str]:
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"https?://\S+", "", text)
    return [line.strip() for line in text.splitlines()
            if not JAPANESE.search(line) and len(WORD.findall(line)) >= MIN_WORDS]


def last_text_before_tool(transcript_path: str) -> str:
    """記録の末尾から、前の道具の結果（またはユーザーの発言）より後にアシスタントが書いた文を集める。"""
    with open(transcript_path, encoding="utf-8") as f:
        entries = [json.loads(line) for line in f.read().splitlines()[-200:] if line.strip()]
    texts: list[str] = []
    for entry in reversed(entries):
        content = (entry.get("message") or {}).get("content")
        if entry.get("type") == "user":
            break
        if entry.get("type") == "assistant" and isinstance(content, list):
            texts += [block.get("text", "") for block in content if block.get("type") == "text"]
    return "\n".join(reversed(texts))


def reason(lines: list[str]) -> str:
    shown = "\n".join(f"- {line[:120]}" for line in lines[:3])
    return ("英語の文がある（CLAUDE.md「出力言語」: ユーザーへ見せる文は、道具の合間の短い文も含めてすべて日本語）。"
            f"日本語で書き直してから続ける。\n{shown}")


def main() -> int:
    # Claude Code はフックの入出力を UTF-8 でやり取りする。Windows の既定（cp932）のままだと理由の文が化ける。
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    hook = json.load(sys.stdin)
    event = hook.get("hook_event_name")
    if event in ("Stop", "SubagentStop"):
        lines = english_lines(hook.get("last_assistant_message") or "")
        if lines:
            print(json.dumps({"decision": "block", "reason": reason(lines)}, ensure_ascii=False))
    # 裏の作業役（agent_id がある）の中では、transcript_path が呼び出し元のセッションの記録を指し、作業役の文を読めない。
    # 作業役の文は、作業役が終わるときの SubagentStop で見る。
    elif event == "PreToolUse" and hook.get("transcript_path") and not hook.get("agent_id"):
        lines = english_lines(last_text_before_tool(hook["transcript_path"]))
        if lines:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                     "permissionDecisionReason": reason(lines)}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
