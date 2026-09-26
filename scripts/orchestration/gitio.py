"""並行実行の道具がgitを呼ぶ口。飽和した機械で回す前提なので、索引を書き戻さず（`GIT_OPTIONAL_LOCKS=0`）、
時間切れ・起動の失敗は例外にせず`None`として返す（呼ぶ側は「未取得」として扱う）。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

GIT_TIMEOUT_SECONDS = 60


def git(repo: Path, *args: str, stdin: bytes | None = None,
        timeout: float = GIT_TIMEOUT_SECONDS) -> subprocess.CompletedProcess[bytes] | None:
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    try:
        return subprocess.run(["git", *args], cwd=str(repo), input=stdin, capture_output=True,
                              env=env, timeout=timeout, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return None


def git_out(repo: Path, *args: str) -> str | None:
    r = git(repo, *args)
    if r is None or r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", errors="replace").strip()


def is_ancestor(repo: Path, older: str, newer: str) -> bool:
    r = git(repo, "merge-base", "--is-ancestor", older, newer)
    return r is not None and r.returncode == 0


def cat_files(repo: Path, specs: list[str]) -> dict[str, str | None]:
    """`<rev>:<path>`の中身を1回の`git cat-file --batch`でまとめて読む。無ければNone。"""
    if not specs:
        return {}
    r = git(repo, "cat-file", "--batch", stdin=("\n".join(specs) + "\n").encode("utf-8"))
    out: dict[str, str | None] = dict.fromkeys(specs)
    if r is None or r.returncode != 0:
        return out
    data, pos = r.stdout, 0
    for spec in specs:
        end = data.index(b"\n", pos)
        header = data[pos:end].decode("utf-8", errors="replace").split()
        pos = end + 1
        if len(header) == 3 and header[1] == "blob":
            size = int(header[2])
            out[spec] = data[pos:pos + size].decode("utf-8", errors="replace")
            pos += size + 1
        elif len(header) == 3:
            pos += int(header[2]) + 1
    return out
