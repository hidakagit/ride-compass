"""Claude の文に英語の文があれば、先へ進ませずに日本語で書き直させるフック（CLAUDE.md「出力言語」を機械で守る）。

.claude/settings.json の hooks から、次の出来事で打つ（標準入力でフックの JSON を受け取る。公式「Hooks reference」）:
- Stop・SubagentStop: その手番の最後の文（`last_assistant_message`）と、まだ止めていない英語の文（下の MessageDisplay）を見る。
  英語の文があれば終わらせない（`decision: block`）。止めて書き直させた続きの手番（`stop_hook_active`）では止めない——止め続けると、
  英語の文が要る場面で手番が終わらない（公式「Hooks reference」の Stop の入力）。
- MessageDisplay: 画面に出す文を塊（`delta`）で受け取る。止める力は無い（公式の MessageDisplay の出力）ので、メッセージの最後の
  塊（`final`）でメッセージ全体を見て、英語の文を「まだ止めていない英語の文」として覚えるだけにする。
- PreToolUse: 道具を打つ直前に書いた文（記録 `transcript_path` の、前の道具の結果より後に書いた文の塊）と、まだ止めていない
  英語の文を見る。英語の文があればその道具を打たせない（`permissionDecision: deny`）。書き直した文が記録に足されると、次の打ち直しは通る。

記録は非同期に書かれ、フックの時点で今の手番の文がまだ無いことがある（公式「Hooks reference」の `transcript_path`。デスクトップの
アプリで、道具の直前の文が記録に無いまま道具が打たれた）。その文は MessageDisplay が覚え、同じメッセージの道具より後に届いたときは
次の道具か手番の終わりで止める。記録で止めた文が遅れて MessageDisplay から届いても、止めた文として覚えてあるので二度は止めない。

英語の文とは、仮名・漢字を1字も含まず、英字だけの語が5つ以上並ぶ行。コードブロック・`で囲んだもの・URL は見ない
（コマンド・ファイル名・コードは英語のままでよい）。
"""

import json
import os
import re
import sys

JAPANESE = re.compile(r"[぀-ヿ㐀-鿿ｦ-ﾟ]")
WORD = re.compile(r"(?<![\w/.#@-])[A-Za-z]{2,}(?![\w/.#@-])")
MIN_WORDS = 5
TAIL_LINES = 200
CHUNK_BYTES = 64 * 1024
# 止めた文を覚えておく数。遅れて届く文は同じ手番のうちに来るので、直近のものだけでよい。
DENIED_KEEP = 50


def english_lines(text: str) -> list[str]:
    text = re.sub(r"```.*?(```|\Z)", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"https?://\S+", "", text)
    return [line.strip() for line in text.splitlines()
            if not JAPANESE.search(line) and len(WORD.findall(line)) >= MIN_WORDS]


def tail_lines(path: str, count: int) -> list[str]:
    """ファイルの最後の count 行。長いセッションの記録は数十MBになるので、末尾から塊ずつ読む。"""
    with open(path, "rb") as f:
        end = f.seek(0, os.SEEK_END)
        chunks: list[bytes] = []
        newlines = 0
        # 改行が count より多く集まれば、塊の頭で切れた行（とそこで切れた文字）を捨てても count 行が残る。
        while end > 0 and newlines <= count:
            start = max(0, end - CHUNK_BYTES)
            f.seek(start)
            chunks.append(f.read(end - start))
            newlines += chunks[-1].count(b"\n")
            end = start
    data = b"".join(reversed(chunks))
    return [line.decode("utf-8") for line in data.splitlines()[-count:]]


def last_text_before_tool(transcript_path: str) -> str:
    """記録の末尾から、前の道具の結果（またはユーザーの発言）より後にアシスタントが書いた文を集める。"""
    texts: list[str] = []
    # 1行に道具の結果がまるごと入るので、末尾から要る所までだけを解く。
    for line in reversed(tail_lines(transcript_path, TAIL_LINES)):
        if not line.strip():
            continue
        entry = json.loads(line)
        content = (entry.get("message") or {}).get("content")
        if entry.get("type") == "user":
            break
        if entry.get("type") == "assistant" and isinstance(content, list):
            texts += [block.get("text", "") for block in content if block.get("type") == "text"]
    return "\n".join(reversed(texts))


def state_dir(hook: dict) -> str:
    """セッション（裏の作業役なら作業役）ごとの覚え書きの置き場。"""
    base = hook.get("scratchpad_dir")
    if not base:
        # 道具を打つたびに走るフックなので、置き場が渡されないときにだけ読み込む。
        import tempfile
        base = os.path.join(tempfile.gettempdir(), "claude-japanese-only")
    name = f"japanese-only-{hook.get('session_id', '')}" + (f"-{hook['agent_id']}" if hook.get("agent_id") else "")
    path = os.path.join(base, name)
    os.makedirs(path, exist_ok=True)
    return path


def read_lines(path: str) -> list[str]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_lines(path: str, lines: list[str], mode: str = "a") -> None:
    with open(path, mode, encoding="utf-8") as f:
        f.writelines(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)


def remember_display(hook: dict) -> None:
    """MessageDisplay の塊をメッセージごとに貯め、最後の塊で英語の文を「まだ止めていない」へ足す。"""
    directory = state_dir(hook)
    # 塊の境目はコードブロックの途中にも来るので、塊ごとでなくメッセージ全体で見る。
    message = os.path.join(directory, f"message-{hook.get('message_id', '')}.txt")
    with open(message, "a", encoding="utf-8") as f:
        f.write(hook.get("delta") or "")
    if not hook.get("final"):
        return
    with open(message, encoding="utf-8") as f:
        text = f.read()
    os.remove(message)
    denied = set(read_lines(os.path.join(directory, "denied.jsonl")))
    write_lines(os.path.join(directory, "pending.jsonl"), [line for line in english_lines(text) if line not in denied])


def take_pending(hook: dict, found: list[str]) -> list[str]:
    """まだ止めていない英語の文を found に足して返し、止めた文として覚え直す。"""
    directory = state_dir(hook)
    pending_path = os.path.join(directory, "pending.jsonl")
    denied_path = os.path.join(directory, "denied.jsonl")
    lines = list(dict.fromkeys(found + read_lines(pending_path)))
    if os.path.exists(pending_path):
        os.remove(pending_path)
    if lines:
        denied = list(dict.fromkeys(read_lines(denied_path) + lines))[-DENIED_KEEP:]
        write_lines(denied_path, denied, mode="w")
    return lines


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
    if event == "MessageDisplay":
        remember_display(hook)
    elif event in ("Stop", "SubagentStop"):
        lines = take_pending(hook, english_lines(hook.get("last_assistant_message") or ""))
        if lines and not hook.get("stop_hook_active"):
            print(json.dumps({"decision": "block", "reason": reason(lines)}, ensure_ascii=False))
    elif event == "PreToolUse":
        # 裏の作業役（agent_id がある）の中では、transcript_path が呼び出し元のセッションの記録を指し、作業役の文を読めない。
        # 作業役の記録は見ず、作業役の覚え書きと、作業役が終わるときの SubagentStop で見る。
        text = "" if hook.get("agent_id") or not hook.get("transcript_path") else last_text_before_tool(hook["transcript_path"])
        lines = take_pending(hook, english_lines(text))
        if lines:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                     "permissionDecisionReason": reason(lines)}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
