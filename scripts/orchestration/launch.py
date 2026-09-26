"""並行実行のフック（定期確認・スロットを渡す）の起動役。origin/masterの版の道具で`orchestrate.py`を走らせる。

フックはセッションを始めたディレクトリ（多くは本体のチェックアウト）から読まれ、本体はmasterが進んでも
手で早送りしない限り古いままである。本体を自動で書き換えるのはユーザーの作業ツリーを触ることになるので、
フックの入口（PostToolUseは`scripts/orchestration/hook.sh`、WorktreeCreate・WorktreeRemoveは
`.claude/settings.json`の行そのもの）がこのファイルをorigin/masterから取り出して動かし、このファイルが道具一式
（`scripts/orchestrate.py`・`scripts/orchestration/`・`scripts/check_master_ci.py`・`scripts/lockrun.py`）を
origin/masterの版で`<gitの共通ディレクトリ>/orchestration/tools/<sha>/`へ書き出して、そこから動かす。
書き出しはshaごとに1回。書き出しから動かした処理はフックの時間切れまで走りうるので、別のshaの書き出しは
しばらく使われなかったものだけを消す。書き出せなければ本体の道具へは落とさず、失敗として終わる。

フックの入口そのもの（本体の`hook.sh`と`.claude/settings.json`）はここから直せないので、定期確認では、
本体の入口がorigin/masterの版と違えば確認の結果に「入口が古い」と添える（本体を早送りすると直る）。

    printf '%s' "<フックの入力>" | python launch.py --project <本体のチェックアウト> [<orchestrate.pyの引数>...]

`orchestrate.py`の引数を省くと`check --if-due`（PostToolUseの定期確認）を走らせる。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

#: origin/masterから書き出す道具（定期確認が読み込むもの・定期確認が裏で起こすスロットの温めが呼ぶ枠）。
TOOL_PATHS = ("scripts/orchestrate.py", "scripts/check_master_ci.py", "scripts/lockrun.py", "scripts/orchestration")
#: 本体から読まれるフックの入口。
ENTRY_PATHS = ("scripts/orchestration/hook.sh", ".claude/settings.json")
CHECK_COMMAND = ("check", "--if-due")
GIT_TIMEOUT_SECONDS = 60
#: 別のshaの書き出しを消すまでの、最後に使われてからの秒数。書き出しから動かした処理が走り続けうる長さ
#: （WorktreeCreateフックの時間切れ。.claude/settings.jsonの1800秒）より長くする。
KEEP_UNUSED_SECONDS = 3600


def git(project: Path, *args: str, stdin: bytes | None = None) -> bytes | None:
    try:
        r = subprocess.run(["git", *args], cwd=str(project), input=stdin, capture_output=True,
                           timeout=GIT_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def export_tools(project: Path, common: Path, sha: str) -> Path | None:
    """origin/masterの版の道具を`tools/<sha>/`へ書き出す（既にあれば使う）。書き出した場所を返す。"""
    root = common / "orchestration" / "tools"
    target = root / sha
    if (target / "scripts" / "orchestrate.py").exists():
        os.utime(target)
        return target
    names = git(project, "ls-tree", "-r", "--name-only", sha, "--", *TOOL_PATHS)
    if not names:
        return None
    paths = [p for p in names.decode("utf-8").splitlines() if p.endswith((".py", ".sh"))]
    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"{sha}.", dir=str(root)))
    for path in paths:
        blob = git(project, "show", f"{sha}:{path}")
        if blob is None:
            shutil.rmtree(staging, ignore_errors=True)
            return None
        (staging / path).parent.mkdir(parents=True, exist_ok=True)
        (staging / path).write_bytes(blob)
    try:
        staging.rename(target)
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)  # 同時に走った別の起動が先に書き出した
    now = time.time()
    for old in root.iterdir():
        try:
            unused = now - old.stat().st_mtime
        except OSError:
            continue
        if old.name != sha and unused > KEEP_UNUSED_SECONDS:
            shutil.rmtree(old, ignore_errors=True)
    return target if target.exists() else None


def stale_entry_notes(project: Path, sha: str) -> list[str]:
    stale = []
    for path in ENTRY_PATHS:
        latest = git(project, "rev-parse", f"{sha}:{path}")
        local = git(project, "hash-object", "--", path)
        if latest and local and latest.strip() != local.strip():
            stale.append(path)
    if not stale:
        return []
    return [(f"注: フックの入口（本体の{'・'.join(stale)}）がorigin/masterの版と違う。"
             "本体のチェックアウトを早送りすると直る（入口だけは本体から読まれる）")]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    args, command = parser.parse_known_args()
    command = command or list(CHECK_COMMAND)
    project = Path(args.project)
    hook_input = sys.stdin.buffer.read()
    common_out = git(project, "rev-parse", "--path-format=absolute", "--git-common-dir")
    sha_out = git(project, "rev-parse", "--verify", "origin/master^{commit}")
    sha = sha_out.decode().strip() if sha_out else None
    tools = export_tools(project, Path(common_out.decode().strip()), sha) if common_out and sha else None
    if tools is None:
        print(f"[launch] origin/masterの版の道具を書き出せない（{project}）。`{' '.join(command)}`を走らせなかった",
              file=sys.stderr)
        return 1
    r = subprocess.run([sys.executable, str(tools / "scripts" / "orchestrate.py"), "--repo", str(project), *command],
                       input=hook_input, stdout=subprocess.PIPE, check=False)
    notes = stale_entry_notes(project, sha) if tuple(command) == CHECK_COMMAND and r.stdout.strip() else []
    if not notes:
        sys.stdout.buffer.write(r.stdout)
        sys.stdout.flush()
        return r.returncode
    out = r.stdout.decode("utf-8", errors="replace").strip()
    try:
        payload = json.loads(out)
        payload["hookSpecificOutput"]["additionalContext"] += "\n" + "\n".join(notes)
        print(json.dumps(payload))
    except (ValueError, KeyError, TypeError):
        print(out)
    return r.returncode


if __name__ == "__main__":
    # 標準出力はフックの出力（JSON。やり取りする符号はUTF-8と決まっている）としてClaude Codeが読み、
    # ここは子（origin/masterの版）の出力をそのまま出し直すことがあるので、Windowsの既定（cp932）で出さない。
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
