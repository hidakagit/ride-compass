"""定期確認のフックの起動役。origin/masterの版の道具で`check --if-due`を走らせる。

フック（`scripts/orchestration/hook.sh`）はセッションを始めたディレクトリ（多くは本体のチェックアウト）
から読まれ、本体はmasterが進んでも手で早送りしない限り古いままである。本体を自動で書き換えるのは
ユーザーの作業ツリーを触ることになるので、ここではフックがこのファイルをorigin/masterから取り出して
動かし、このファイルが道具一式（`scripts/orchestrate.py`・`scripts/orchestration/`・
`scripts/check_master_ci.py`・`scripts/lockrun.py`）をorigin/masterの版で`<gitの共通ディレクトリ>/orchestration/tools/<sha>/`へ
書き出して、そこから動かす。書き出しはshaごとに1回で、別のshaの書き出しは消す。

フックの入口そのもの（本体の`hook.sh`と`.claude/settings.json`）はここから直せないので、本体の
`hook.sh`がorigin/masterの版と違えば、確認の結果に「入口が古い」と添える（本体を早送りすると直る）。

    printf '%s' "<フックの入力>" | python launch.py --project <本体のチェックアウト>
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

#: origin/masterから書き出す道具（定期確認が読み込むもの・定期確認が裏で起こすスロットの温めが呼ぶ枠）。
TOOL_PATHS = ("scripts/orchestrate.py", "scripts/check_master_ci.py", "scripts/lockrun.py", "scripts/orchestration")
HOOK_PATH = "scripts/orchestration/hook.sh"
GIT_TIMEOUT_SECONDS = 60


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
    for old in root.iterdir():
        if old.name != sha:
            shutil.rmtree(old, ignore_errors=True)
    return target if target.exists() else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    project = Path(args.project)
    hook_input = sys.stdin.buffer.read()
    common_out = git(project, "rev-parse", "--path-format=absolute", "--git-common-dir")
    sha_out = git(project, "rev-parse", "--verify", "origin/master^{commit}")
    tools = (export_tools(project, Path(common_out.decode().strip()), sha_out.decode().strip())
             if common_out and sha_out else None)
    # origin/masterから書き出せないとき（参照が無い等）だけ、本体の道具で確認する。
    entry = (tools or project) / "scripts" / "orchestrate.py"
    r = subprocess.run([sys.executable, str(entry), "--repo", str(project), "check", "--if-due"],
                       input=hook_input, capture_output=True, check=False)
    out = r.stdout.decode("utf-8", errors="replace").strip()
    if not out:
        return 0
    notes = []
    if tools is None:
        notes.append("注: origin/masterの版の道具を書き出せず、本体のチェックアウトの道具で確認した（古い可能性がある）")
    if sha_out:
        latest = git(project, "rev-parse", f"{sha_out.decode().strip()}:{HOOK_PATH}")
        local = git(project, "hash-object", "--", HOOK_PATH)
        if latest and local and latest.strip() != local.strip():
            notes.append("注: フックの入口（本体のscripts/orchestration/hook.sh）がorigin/masterの版と違う。"
                         "本体のチェックアウトを早送りすると直る（入口だけは本体から読まれる）")
    if not notes:
        print(out)
        return 0
    try:
        payload = json.loads(out)
        payload["hookSpecificOutput"]["additionalContext"] += "\n" + "\n".join(notes)
        print(json.dumps(payload))
    except (ValueError, KeyError, TypeError):
        print(out)
    return 0


if __name__ == "__main__":
    # 標準出力はフックの出力（JSON。やり取りする符号はUTF-8と決まっている）としてClaude Codeが読み、
    # ここは子（origin/masterの版）の出力をそのまま出し直すことがあるので、Windowsの既定（cp932）で出さない。
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
