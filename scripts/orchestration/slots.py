"""並行実行の作業ツリーを固定数のスロットとして使い回す。依頼で足した側の機能。

エージェントの作業ツリーは`<本体>/.claude/worktrees/slot-<N>`に固定数だけ置き、消さずに次の
タスクへ渡し直す。数は回の上限（状態の表の`limits.concurrent`、無ければ既定）と同じ。

    python scripts/orchestrate.py slot list          # スロットごとの事実
    python scripts/orchestrate.py slot release <N>   # 渡した印（ロック）を外す
    python scripts/orchestrate.py slot hook-create   # WorktreeCreateフックの入口（標準入力がJSON）
    python scripts/orchestrate.py slot hook-remove   # WorktreeRemoveフックの入口

## 渡したかどうかは作業ツリー自身が持つ

渡した印は`git worktree lock`の理由（`slot <名前> <時刻>`）で、状態の表には書かない。gitの
ロックは作成が原子的なので、2本が同時に同じスロットを取りに来ても片方だけが取れる。

印を外す契機（監査で通したとき・`slot release`）は規約「作業ツリーのスロット」節。

## 渡し直すときに止まる条件（黙って消さない）

- 未コミットの変更がある
- どのリモートの枝からも届かないコミットがある（pushしていない成果）
- 作業ツリーの中にリンク（ジャンクション・シンボリックリンク）がある——`git worktree remove`の
  再帰削除がリンクの先を消すため、作業ツリーの中に置かない

## 依存

`frontend/package-lock.json`の中身が、前回`npm ci`した時点と違うとき（または`node_modules`が
無いとき）だけ`npm ci`を`heavy`の枠で走らせる。前回の値は`node_modules`の中の印に置く——
`node_modules`を消せば印も消え、入れ直しになる。
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from orchestration.core import (
    DEFAULT_CONCURRENT,
    EXPECTED_HOOKS_PATH,
    SLOT_LOCK_PREFIX,
    Context,
    git,
    git_out,
    list_worktrees,
    load_board,
    restore_hooks_path,
    unsaved_work,
)

SLOT_PREFIX = "slot-"
NPM_MARK = "frontend/node_modules/.slot-package-lock.sha1"
#: 作業ツリーの中にあってはならないリンクの置き場（過去に共有元を指すジャンクションが置かれた所）。
LINK_CANDIDATES = ("frontend/node_modules", "node_modules", "backend/data", "backend/.venv")
DEFAULT_BASE = "origin/master"


class SlotError(Exception):
    """渡し直しを止める理由。スロットには手を付けずに報告する。"""


def main_root(ctx: Context) -> Path:
    return ctx.common.parent


def slot_count(ctx: Context) -> int:
    value = load_board(ctx).get("limits", {}).get("concurrent")
    return value if isinstance(value, int) and value > 0 else DEFAULT_CONCURRENT


def slot_path(ctx: Context, n: int) -> Path:
    return main_root(ctx) / ".claude" / "worktrees" / f"{SLOT_PREFIX}{n}"


def slot_number(ctx: Context, path: str) -> int | None:
    p = Path(os.path.normpath(path))
    if os.path.normcase(str(p.parent)) != os.path.normcase(str(slot_path(ctx, 1).parent)):
        return None
    name = p.name
    return int(name[len(SLOT_PREFIX):]) if name.startswith(SLOT_PREFIX) and name[len(SLOT_PREFIX):].isdigit() else None


def registered(ctx: Context) -> dict[str, str]:
    """登録済みの作業ツリー（正規化したパス → ロックの理由。ロックが無ければ空文字）。"""
    return {os.path.normcase(t.path): (t.locked or "(理由なし)") if t.locked is not None else ""
            for t in list_worktrees(ctx)}


def lock_reason(ctx: Context, path: Path) -> str | None:
    """ロックの理由。ロックされていなければNone、登録されていなければKeyError。"""
    trees = registered(ctx)
    key = os.path.normcase(os.path.normpath(str(path)))
    if key not in trees:
        raise KeyError(str(path))
    return trees[key] or None


def run_git(cwd: Path, *args: str, strip: bool = True) -> str:
    r = git(cwd, *args)
    if r is None or r.returncode != 0:
        err = "" if r is None else r.stderr.decode("utf-8", errors="replace").strip()
        raise SlotError(f"git {' '.join(args)} が失敗: {err or '時間切れ'}")
    out = r.stdout.decode("utf-8", errors="replace")
    return out.strip() if strip else out


def is_link(path: Path) -> bool:
    return os.path.islink(path) or bool(getattr(os.path, "isjunction", lambda _: False)(path))


def blockers(path: Path) -> list[str]:
    """渡し直しを止める事実。空なら渡し直してよい。"""
    links = [f"作業ツリーの中にリンクがある: {rel}" for rel in LINK_CANDIDATES if is_link(path / rel)]
    return links + unsaved_work(path)


def lock_file_sha(path: Path) -> str | None:
    lock = path / "frontend" / "package-lock.json"
    return hashlib.sha1(lock.read_bytes()).hexdigest() if lock.exists() else None


def ensure_deps(path: Path) -> str:
    """package-lock.jsonが前回のnpm ciから変わったときだけnpm ciを走らせる。何をしたかを返す。"""
    want = lock_file_sha(path)
    if want is None:
        return "frontend/package-lock.jsonが無い"
    mark = path / NPM_MARK
    if mark.exists() and mark.read_text(encoding="utf-8").strip() == want:
        return "npm ciは不要（package-lock.jsonが前回と同じ）"
    lockrun = Path(__file__).resolve().parents[1] / "lockrun.py"
    cmd = [sys.executable, str(lockrun), "--",
           f"cd '{(path / 'frontend').as_posix()}' && npm ci --no-audit --no-fund"]
    r = subprocess.run(cmd, stdout=sys.stderr, stderr=sys.stderr, check=False)
    if r.returncode != 0:
        raise SlotError(f"npm ciが失敗（終了コード{r.returncode}）")
    mark.write_text(want + "\n", encoding="utf-8")
    return "npm ciを実行した（package-lock.jsonが前回と違う、またはnode_modulesが無い）"


def claim(ctx: Context, path: Path, owner: str) -> None:
    """渡した印を付ける。`git worktree lock`は既にロックがあれば失敗するので、同時に取りに来た
    2本のうち片方だけが取れる。"""
    at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    run_git(ctx.repo, "worktree", "lock", "--reason", f"{SLOT_LOCK_PREFIX}{owner} {at}", str(path))


def reset_to(path: Path, branch: str, base: str) -> None:
    """止める理由が無いことを確かめてから、作業用の枝をbaseから作り直す。"""
    problems = blockers(path)
    if problems:
        raise SlotError(f"{path.name} を渡し直せない: " + " / ".join(problems))
    run_git(path, "switch", "--quiet", "-C", branch, base)


def prepare(ctx: Context, n: int, owner: str, base: str) -> Path:
    """スロットNを最新のbaseから渡せる状態にし、ownerへ渡した印を付ける。
    止める理由があれば中身を変えずにSlotError（付けた印は外す）。"""
    path = slot_path(ctx, n)
    branch = f"{SLOT_PREFIX}{n}"
    try:
        reason = lock_reason(ctx, path)
        created = False
    except KeyError:
        if path.exists():
            raise SlotError(f"{path} は作業ツリーとして登録されていないのにディレクトリがある")
        run_git(ctx.repo, "worktree", "add", "--quiet", "-B", branch, str(path), base)
        reason, created = None, True
    if reason and not reason.startswith(f"{SLOT_LOCK_PREFIX}{owner} "):
        raise SlotError(f"{path.name} は渡し済み（{reason}）")
    if reason:
        run_git(ctx.repo, "worktree", "unlock", str(path))
    claim(ctx, path, owner)
    try:
        if not created:
            reset_to(path, branch, base)
        print(f"[slot] {path.name}: {ensure_deps(path)}", file=sys.stderr)
    except SlotError:
        run_git(ctx.repo, "worktree", "unlock", str(path))
        raise
    restore_hooks_path(ctx)
    return path


def acquire(ctx: Context, owner: str, base: str) -> Path:
    """空いているスロットを1つ渡す。空きが無ければSlotError（上限を仕組みで守る）。"""
    run_git(ctx.repo, "fetch", "--quiet", "origin", "master")
    reasons = []
    for n in range(1, slot_count(ctx) + 1):
        try:
            return prepare(ctx, n, owner, base)
        except SlotError as e:
            reasons.append(str(e))
    raise SlotError("空いているスロットが無い: " + " / ".join(reasons))


def cmd_list(ctx: Context) -> int:
    trees = registered(ctx)
    for n in range(1, slot_count(ctx) + 1):
        path = slot_path(ctx, n)
        key = os.path.normcase(os.path.normpath(str(path)))
        if key not in trees:
            print(f"{path.name}: 未作成")
            continue
        facts = [f"渡し先 {trees[key]}" if trees[key] else "空き（ロックなし）"]
        facts += blockers(path) or ["渡し直せる"]
        head = git_out(path, "log", "-1", "--format=%h %cd", "--date=format:%m-%d %H:%M") or "?"
        print(f"{path.name}: {head} / " + " / ".join(facts))
    extra = [p for p in trees if os.path.basename(p) not in
             {f"{SLOT_PREFIX}{n}" for n in range(1, slot_count(ctx) + 1)}]
    print(f"スロット以外の作業ツリー: {len(extra) - 1}本（本体を除く）")
    hooks = git_out(ctx.repo, "config", "--get", "core.hooksPath")
    print(f"core.hooksPath={hooks}" + ("" if hooks == EXPECTED_HOOKS_PATH else "（相対の.githooksでない）"))
    return 0


def read_hook_input() -> dict:
    # Windowsの標準入力は既定でロケールの文字コードとして読まれ、UTF-8のパス（日本語を含む）が化ける。
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    return json.loads(raw) if raw.strip() else {}


def hook_create(ctx: Context) -> int:
    """WorktreeCreateフック。標準入力の`name`を渡し先として、空きスロットのパスを最後の行に出す。
    失敗（空きが無い等）は0以外で終わり、Claude Codeは作業ツリーを作らずに起動を止める。"""
    data = read_hook_input()
    owner = str(data.get("name") or "unknown")
    try:
        path = acquire(ctx, owner, DEFAULT_BASE)
    except SlotError as e:
        print(f"[slot] 作業ツリーを渡せない: {e}", file=sys.stderr)
        return 1
    print(str(path))
    return 0


def hook_remove(ctx: Context) -> int:
    """WorktreeRemoveフック。スロットなら渡した印を外すだけで、ディレクトリは消さない。
    Claude Codeがこれを呼ぶのは利用者が作業ツリーを明示的に破棄したときだけ（担当の終了では
    呼ばない）。登録しておく理由は、フックが無いと破棄の処理が既定の`git worktree remove`へ
    落ち、スロットのディレクトリごと消えうること。"""
    data = read_hook_input()
    path = str(data.get("worktree_path") or "")
    n = slot_number(ctx, path) if path else None
    if n is not None:
        try:
            if lock_reason(ctx, slot_path(ctx, n)):
                run_git(ctx.repo, "worktree", "unlock", str(slot_path(ctx, n)))
        except (KeyError, SlotError) as e:
            print(f"[slot] 印を外せない: {e}", file=sys.stderr)
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="orchestrate.py slot", description="作業ツリーのスロット")
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--dir", default=os.environ.get("ORCH_DIR"))
    sub = parser.add_subparsers(dest="op", required=True)
    sub.add_parser("list")
    p = sub.add_parser("release")
    p.add_argument("n", type=int)
    sub.add_parser("hook-create")
    sub.add_parser("hook-remove")
    args = parser.parse_args(argv)
    ctx = Context(Path(args.repo), args.dir)
    try:
        if args.op == "list":
            return cmd_list(ctx)
        if args.op == "release":
            path = slot_path(ctx, args.n)
            if lock_reason(ctx, path):
                run_git(ctx.repo, "worktree", "unlock", str(path))
            return 0
        if args.op == "hook-create":
            return hook_create(ctx)
        return hook_remove(ctx)
    except SlotError as e:
        print(f"[slot] {e}", file=sys.stderr)
        return 2
    except KeyError as e:
        print(f"[slot] 作業ツリーとして登録されていない: {e}", file=sys.stderr)
        return 2
