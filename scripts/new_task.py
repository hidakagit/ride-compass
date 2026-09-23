"""タスク番号を確保する——スタブと台帳1行をorigin/masterへ即pushする。

## 目的

タスク番号（Txxx）は複数のセッション・エージェントが同時に「次の番号」を計算するため衝突する。
番号を決めてからmasterへ載せるまでの時間窓を、fetch→書く→pushの一続きへ縮め、
衝突したら自分の側を次の空き番号へ振り直す。これを手でやらずに1コマンドにする。

## 方法

作業ツリーとブランチには触れずに、**リモートのmasterそのものを土台に**起票コミットを作る。

1. `git fetch <remote> master` で土台を取る
2. 土台の `docs/records/tasks/` のファイル名（`T1234.md`・`T317-2.md`・`T145a.md` 等）の
   番号の最大+1を採る
3. 一時インデックスへ土台のツリーを読み、スタブ `docs/records/tasks/Txxx.md` と
   台帳 `docs/improvement-plan.md` の該当節の末尾の1行だけを足してコミットを作る
   （作業ツリーの未コミット変更・ブランチ上の未pushコミットは、構造上このコミットに入らない）
4. `git push <remote> <sha>:refs/heads/master`。pre-pushフックは通常どおり走る（検査はしない）
5. 拒否されてリモートのmasterが動いていたら、新しい土台で2からやり直す（番号は土台から
   導くので、他者が先に取った番号は自然に避けられる）。リモートが動いていないのに拒否された
   （フック・認証等）なら、やり直さずに失敗する

push後、確保したコミットを手元のブランチへ取り込む（ブランチが自分のコミットを持たなければ
早送り、持っていればその上へcherry-pick）。手元の変更とぶつかって取り込めないときは、
番号は確保済みのまま取り込みだけを飛ばし、手で取り込む方法を表示する。

## 使い方

    python scripts/new_task.py "タイトル" --section "節見出しの一部" --size S [--background "背景"]

終了コード: 確保できたら0。節が一意に決まらない・push できない等で確保できなければ1。
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLAN_DOC = "docs/improvement-plan.md"
TASKS_DIR = "docs/records/tasks"
TASK_FILE_RE = re.compile(r"^T(\d+)")
SIZE_RE = re.compile(r"^[SML](〜[SML])?$")


class GitError(RuntimeError):
    pass


def git(*args: str, stdin: bytes | None = None, env: dict[str, str] | None = None,
        check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(["git", *args], cwd=str(REPO_ROOT), input=stdin,
                            capture_output=True, env=env, check=False)
    if check and result.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {decode(result.stderr).strip()}")
    return result


def decode(b: bytes) -> str:
    return b.decode("utf-8", errors="replace")


def git_out(*args: str, **kw) -> str:
    return decode(git(*args, **kw).stdout).strip()


def fetch_base(remote: str) -> str:
    git("fetch", "--quiet", remote, "master")
    return git_out("rev-parse", "FETCH_HEAD")


def next_number(base: str) -> int:
    names = git_out("ls-tree", "--name-only", base, f"{TASKS_DIR}/").splitlines()
    numbers = [int(m.group(1)) for n in names if (m := TASK_FILE_RE.match(n.rsplit("/", 1)[-1]))]
    if not numbers:
        raise GitError(f"{TASKS_DIR}/ にタスク番号を持つファイルが無い（土台 {base[:8]}）")
    return max(numbers) + 1


def find_section(plan: str, needle: str) -> tuple[int | None, list[str]]:
    """needleを含む `## ` 見出しの行番号。一意でなければNoneと候補を返す。"""
    lines = plan.splitlines()
    headings = [(i, l) for i, l in enumerate(lines) if l.startswith("## ")]
    hits = [(i, l) for i, l in headings if needle in l]
    if len(hits) == 1:
        return hits[0][0], []
    return None, [l for _, l in (hits or headings)]


def insert_ledger_line(plan: str, heading_index: int, entry: str) -> str:
    """節の最後のタスク行の直後へ入れる。タスク行が無ければ見出しの直後へ。"""
    nl = "\r\n" if "\r\n" in plan else "\n"
    lines = plan.split(nl)
    end = next((i for i in range(heading_index + 1, len(lines)) if lines[i].startswith("## ")),
               len(lines))
    items = [i for i in range(heading_index + 1, end) if lines[i].startswith("- [")]
    if items:
        lines.insert(items[-1] + 1, entry)
    else:
        lines[heading_index + 1:heading_index + 1] = ["", entry]
    return nl.join(lines)


def build_commit(base: str, number: int, title: str, heading_needle: str, size: str,
                 background: str, today: str) -> str:
    tid = f"T{number}"
    plan = decode(git("show", f"{base}:{PLAN_DOC}").stdout)
    heading_index, _ = find_section(plan, heading_needle)
    if heading_index is None:
        raise GitError(f"節「{heading_needle}」が土台 {base[:8]} で一意に決まらない")
    entry = f"- [ ] [{tid}](records/tasks/{tid}.md). {title} 規模{size}"
    new_plan = insert_ledger_line(plan, heading_index, entry)
    stub = (f"# {tid}. {title}\n\n状態: 未完了（{today}起票）\n\n## 背景\n\n"
            + (f"{background.strip()}\n" if background.strip() else ""))

    fd, index_path = tempfile.mkstemp(prefix="new_task_index_")
    os.close(fd)
    os.unlink(index_path)  # read-treeは存在しない索引ファイルを新規に作る
    env = {**os.environ, "GIT_INDEX_FILE": index_path}
    try:
        git("read-tree", base, env=env)
        for path, content in ((f"{TASKS_DIR}/{tid}.md", stub), (PLAN_DOC, new_plan)):
            blob = git_out("hash-object", "-w", "--stdin", stdin=content.encode("utf-8"))
            git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
        tree = git_out("write-tree", env=env)
    finally:
        if os.path.exists(index_path):
            os.unlink(index_path)
    message = f"{tid}を起票: {title}（番号確保）\n"
    return git_out("commit-tree", tree, "-p", base, stdin=message.encode("utf-8"))


def push(remote: str, sha: str) -> tuple[bool, str]:
    result = git("push", "--porcelain", remote, f"{sha}:refs/heads/master", check=False)
    return result.returncode == 0, (decode(result.stdout) + decode(result.stderr)).strip()


def integrate(sha: str) -> str:
    """確保したコミットを手元のブランチへ取り込み、結果を返す。

    ブランチが自分のコミットを持たなければ早送り、持っていればその上へcherry-pickする。
    """
    behind = git("merge-base", "--is-ancestor", "HEAD", sha, check=False).returncode == 0
    if behind:
        result = git("merge", "--ff-only", "--quiet", sha, check=False)
    else:
        result = git("cherry-pick", sha, check=False)
        if result.returncode != 0 and git("rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD",
                                           check=False).returncode == 0:
            git("cherry-pick", "--abort", check=False)
    if result.returncode == 0:
        return "手元のブランチへ取り込みました"
    reason = decode(result.stdout + result.stderr).strip().splitlines()
    how = f"git merge --ff-only {sha[:10]}" if behind else f"git rebase {sha[:10]}"
    return ("手元への取り込みは飛ばしました（番号は確保済み。手元の変更を片付けてから "
            f"{how} で取り込む）\n  git: {reason[0] if reason else '理由不明'}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("title", help="タスクのタイトル")
    parser.add_argument("--section", required=True, help="台帳の節見出しの一部（一意に決まること）")
    parser.add_argument("--size", required=True, help="規模（S・M・L・S〜M 等）")
    parser.add_argument("--background", default="", help="背景1〜2行")
    parser.add_argument("--remote", default="origin", help="pushするリモート名またはURL")
    parser.add_argument("--attempts", type=int, default=10, help="pushの最大試行回数")
    args = parser.parse_args()

    if not SIZE_RE.match(args.size):
        print(f"規模「{args.size}」は S・M・L か S〜M の形で指定する", file=sys.stderr)
        return 1
    title = " ".join(args.title.split())
    today = dt.datetime.now().astimezone().date().isoformat()

    try:
        base = fetch_base(args.remote)
        plan = decode(git("show", f"{base}:{PLAN_DOC}").stdout)
        _, candidates = find_section(plan, args.section)
        if candidates:
            print(f"節「{args.section}」が一意に決まらない。候補:", file=sys.stderr)
            for c in candidates:
                print(f"  {c}", file=sys.stderr)
            return 1

        for attempt in range(1, args.attempts + 1):
            number = next_number(base)
            sha = build_commit(base, number, title, args.section, args.size,
                               args.background, today)
            ok, output = push(args.remote, sha)
            if ok:
                print(f"T{number} を確保しました（push: {sha}）")
                print(integrate(sha))
                return 0
            new_base = fetch_base(args.remote)
            if new_base == base:
                print(f"pushが拒否されました（リモートのmasterは動いていない）:\n{output}",
                      file=sys.stderr)
                return 1
            print(f"T{number} のpushは先を越されました。土台を取り直して振り直します"
                  f"（{attempt}/{args.attempts}回目）", file=sys.stderr)
            base = new_base
        print(f"{args.attempts}回続けて先を越されたため中止しました", file=sys.stderr)
        return 1
    except GitError as e:
        print(str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
