"""作業ツリーのスロット（.claude/worktrees/slot-<N>）の貸し借り。Claude Code の WorktreeCreate・WorktreeRemove フック。

    python scripts/worktree_slots.py create   # 標準入力のフックの JSON を読み、貸したスロットのパスを出す
    python scripts/worktree_slots.py remove   # 失う作業が無ければ印を外す

貸した印は git のロック（理由が "slot " で始まる）だけ。ロックの作成は原子的なので、同時に取りに来た2本の
うち片方だけが取れる。未コミットの変更か、どのリモートからも届かないコミットのあるスロットは貸さず、印も外さない。
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

SLOTS = 4
MARK = "slot "


def git(*args: str, cwd: Path | None = None) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=False)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])}: {(r.stderr or r.stdout).strip()}")
    return r.stdout.strip()


def slots() -> list[Path]:
    root = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir")).parent / ".claude" / "worktrees"
    return [(root / f"slot-{n}").resolve() for n in range(1, SLOTS + 1)]


def lent() -> list[Path]:
    """印の付いたスロット。`worktree list --porcelain` は ASCII でない理由を引用符と8進に書き換えるので、印は ASCII で書く。"""
    locked, path = set(), ""
    for line in git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.startswith(f"locked {MARK}"):
            locked.add(Path(path).resolve())
    return [p for p in slots() if p in locked]


def unsaved(path: Path) -> str | None:
    """貸し直すと失う作業。"""
    if git("status", "--porcelain", cwd=path):
        return "未コミットの変更がある"
    if git("rev-list", "HEAD", "--not", "--remotes", cwd=path):
        return "どのリモートからも届かないコミットがある"
    return None


def create(name: str) -> Path:
    """印の無いスロットを origin/master に戻して貸す。"""
    git("fetch", "--quiet", "origin", "master")
    reasons = []
    for path in [p for p in slots() if p not in lent()]:
        try:
            if not (path / ".git").exists():
                git("worktree", "add", "--quiet", "--detach", str(path), "origin/master")
            git("worktree", "lock", "--reason", f"{MARK}{name} {dt.datetime.now():%m-%d %H:%M}", str(path))
        except RuntimeError as e:
            reasons.append(f"{path.name}: {e}")
            continue
        if problem := unsaved(path):
            git("worktree", "unlock", str(path))
            reasons.append(f"{path.name}: {problem}")
            continue
        git("switch", "--quiet", "--detach", "origin/master", cwd=path)
        return path
    raise RuntimeError("空いたスロットが無い" + (f"（{' / '.join(reasons)}）" if reasons else ""))


def remove(path: Path) -> None:
    """ディレクトリは消さず、失う作業が無ければ印を外す。"""
    if path.resolve() in lent() and not unsaved(path):
        git("worktree", "unlock", str(path))


if __name__ == "__main__":
    hook = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    try:
        if sys.argv[1] == "create":
            # 印の理由は ASCII だけにする（上の lent の説明）。
            print(create(str(hook.get("name") or "").encode("ascii", "ignore").decode() or "unknown"))
        elif hook.get("worktree_path"):
            remove(Path(hook["worktree_path"]))
    except RuntimeError as e:
        print(f"[worktree_slots] {e}", file=sys.stderr)
        sys.exit(1)
