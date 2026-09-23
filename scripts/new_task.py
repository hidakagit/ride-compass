"""起票が承認されたタスクに番号を振り、記録の雛形と台帳の行を1コミットでorigin/masterへ入れる。

## 目的

タスク番号（Txxx）は複数のセッション・エージェントが同時に「次の番号」を計算するため衝突する。
番号を決めてからmasterへ載せるまでの時間窓を、fetch→書く→pushの一続きへ縮め、
衝突したら自分の側を次の空き番号へ振り直す。承認の1回のやり取りで承認された分は、件名
`台帳: 起票 T1090・T1091`の1コミットにまとめる（CLAUDE.md「1タスク=1コミット」の例外）。

## 方法

作業ツリーとブランチには触れずに、**リモートのmasterそのものを土台に**起票コミットを作る。

1. `git fetch origin master` で土台を取る
2. 土台の `docs/records/tasks/` のファイル名の番号の最大+1から、承認された件数ぶん順に採る
3. 一時インデックスへ土台のツリーを読み、雛形 `docs/records/tasks/Txxx.md` と、台帳
   `docs/improvement-plan.md` の該当節の末尾の1行を件数ぶん足してコミットを作る
   （作業ツリーの未コミット変更・ブランチ上の未pushコミットは、構造上このコミットに入らない）
4. `git push origin <sha>:refs/heads/master`
5. 拒否されてリモートのmasterが動いていたら、新しい土台で2からやり直す（番号は土台から
   導くので、他者が先に取った番号は自然に避けられる）。リモートが動いていないのに拒否された
   （フック・認証等）なら、やり直さずに失敗する

手元のブランチへは取り込まない（fetchで追う）。

## 使い方

    python scripts/new_task.py "タイトル" --section "節見出しの一部" --size S [--background "背景"] \\
        [-- "タイトル2" --section ... --size M ...]

`--`で区切って、承認された件を並べる。終了コード: 確保できたら0。節が一意に決まらない・pushできない等で
確保できなければ1。
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

sys.path.insert(0, str(Path(__file__).resolve().parent))

from orchestration.core import PLAN_DOC, TASKS_DIR, find_section, insert_ledger_row

REPO_ROOT = Path(__file__).resolve().parent.parent
REMOTE = "origin"
ATTEMPTS = 10
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


def fetch_base() -> str:
    git("fetch", "--quiet", REMOTE, "master")
    return git_out("rev-parse", "FETCH_HEAD")


def next_number(base: str) -> int:
    names = git_out("ls-tree", "--name-only", base, f"{TASKS_DIR}/").splitlines()
    numbers = [int(m.group(1)) for n in names if (m := TASK_FILE_RE.match(n.rsplit("/", 1)[-1]))]
    if not numbers:
        raise GitError(f"{TASKS_DIR}/ にタスク番号を持つファイルが無い（土台 {base[:8]}）")
    return max(numbers) + 1


def build_commit(base: str, first: int, tasks: list[argparse.Namespace], today: str) -> tuple[str, list[str]]:
    plan = decode(git("show", f"{base}:{PLAN_DOC}").stdout)
    files, ids = [], []
    for number, task in enumerate(tasks, first):
        tid = f"T{number}"
        heading_index, _ = find_section(plan, task.section)
        if heading_index is None:
            raise GitError(f"節「{task.section}」が土台 {base[:8]} で一意に決まらない")
        plan = insert_ledger_row(plan, heading_index, f"- [ ] [{tid}](records/tasks/{tid}.md). {task.title} 規模{task.size}")
        stub = (f"# {tid}. {task.title}\n\n状態: 未完了（{today}起票）\n\n## 背景\n\n"
                + (f"{task.background.strip()}\n" if task.background.strip() else ""))
        files.append((f"{TASKS_DIR}/{tid}.md", stub))
        ids.append(tid)
    files.append((PLAN_DOC, plan))

    fd, index_path = tempfile.mkstemp(prefix="new_task_index_")
    os.close(fd)
    os.unlink(index_path)  # read-treeは存在しない索引ファイルを新規に作る
    env = {**os.environ, "GIT_INDEX_FILE": index_path}
    try:
        git("read-tree", base, env=env)
        for path, content in files:
            blob = git_out("hash-object", "-w", "--stdin", stdin=content.encode("utf-8"))
            git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
        tree = git_out("write-tree", env=env)
    finally:
        if os.path.exists(index_path):
            os.unlink(index_path)
    message = (f"台帳: 起票 {'・'.join(ids)}\n\n"
               + "".join(f"{tid}: {task.title}\n" for tid, task in zip(ids, tasks)))
    return git_out("commit-tree", tree, "-p", base, stdin=message.encode("utf-8")), ids


def push(sha: str) -> tuple[bool, str]:
    result = git("push", "--porcelain", REMOTE, f"{sha}:refs/heads/master", check=False)
    return result.returncode == 0, (decode(result.stdout) + decode(result.stderr)).strip()


def parse_tasks(argv: list[str]) -> list[argparse.Namespace]:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("title", help="タスクのタイトル")
    parser.add_argument("--section", required=True, help="台帳の節見出しの一部（一意に決まること）")
    parser.add_argument("--size", required=True, help="規模（S・M・L・S〜M 等）")
    parser.add_argument("--background", default="", help="背景1〜2行")
    groups: list[list[str]] = [[]]
    for arg in argv:
        if arg == "--":
            groups.append([])
        else:
            groups[-1].append(arg)
    tasks = [parser.parse_args(g) for g in groups]
    for task in tasks:
        if not SIZE_RE.match(task.size):
            parser.error(f"規模「{task.size}」は S・M・L か S〜M の形で指定する")
        task.title = " ".join(task.title.split())
    return tasks


def main() -> int:
    tasks = parse_tasks(sys.argv[1:])
    today = dt.datetime.now().astimezone().date().isoformat()
    try:
        base = fetch_base()
        plan = decode(git("show", f"{base}:{PLAN_DOC}").stdout)
        for task in tasks:
            _, candidates = find_section(plan, task.section)
            if candidates:
                print(f"節「{task.section}」が一意に決まらない。候補:", file=sys.stderr)
                for c in candidates:
                    print(f"  {c}", file=sys.stderr)
                return 1

        for attempt in range(1, ATTEMPTS + 1):
            sha, ids = build_commit(base, next_number(base), tasks, today)
            ok, output = push(sha)
            if ok:
                print(f"{'・'.join(ids)} を確保しました（push: {sha}。手元へはfetchで取り込む）")
                return 0
            new_base = fetch_base()
            if new_base == base:
                print(f"pushが拒否されました（リモートのmasterは動いていない）:\n{output}", file=sys.stderr)
                return 1
            print(f"{'・'.join(ids)} のpushは先を越されました。土台を取り直して振り直します"
                  f"（{attempt}/{ATTEMPTS}回目）", file=sys.stderr)
            base = new_base
        print(f"{ATTEMPTS}回続けて先を越されたため中止しました", file=sys.stderr)
        return 1
    except GitError as e:
        print(str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
