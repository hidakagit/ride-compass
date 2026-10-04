"""チェックアウトが origin/master に追いついているかを確かめる。

開発機の本体のチェックアウトは、誰も早送りしないと master から遅れたまま使われる。遅れた
チェックアウトで打った道具は、古いコードで判定し、本番へ古いコードを流す。結果がコードの版に
左右される道具は、実行口でここを呼んで、遅れていれば止まる。

    python scripts/checkout_freshness.py          # 遅れていれば理由と追いつくコマンドを出して終了コード1
    python scripts/checkout_freshness.py --sync   # SessionStart フック用。下の条件のときだけ早送りし、結果を1行出す

遅れの定義は「origin/master が HEAD の祖先でない」。作業ブランチでも、origin/master の上に
載っていれば遅れていない。作業ツリーの変更は遅れに数えない——作業ツリーの変更は今まさに
確かめたいコードであり、古いコードではないため。

早送り（`--sync`）は、master にいて、追跡しているファイルに変更が無いときだけ打つ。ほかの枝・
変更のある作業ツリーには触らず、遅れを出すだけにする——並行のセッションが同じ作業ツリーで
作業している最中かもしれないため。
"""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REMOTE = "origin"
BRANCH = "master"
UPSTREAM = f"{REMOTE}/{BRANCH}"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # 資格情報を端末で尋ねられると、フックも道具も入力を待ったまま止まる。
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def _behind(repo: Path) -> int | str:
    """origin の master を取り直し、HEAD に無いコミットの数を返す。数えられなければ理由を返す。"""
    for args in (("fetch", "-q", REMOTE, BRANCH), ("rev-list", "--count", f"HEAD..{UPSTREAM}")):
        result = _git(repo, *args)
        if result.returncode != 0:
            return result.stderr.strip() or f"git {args[0]} の終了コード {result.returncode}"
    return int(result.stdout.strip())


def _branch(repo: Path) -> str | None:
    result = _git(repo, "symbolic-ref", "-q", "--short", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else None


def _dirty(repo: Path) -> bool:
    return bool(_git(repo, "status", "--porcelain", "--untracked-files=no").stdout.strip())


def _catch_up_command(repo: Path) -> str:
    if _branch(repo) != BRANCH:
        return f"git -C {repo} rebase {UPSTREAM}"
    command = f"git -C {repo} merge --ff-only {UPSTREAM}"
    return f"作業ツリーの変更を片付けてから {command}" if _dirty(repo) else command


def staleness(repo: Path = REPO_ROOT) -> str | None:
    """遅れていれば（確かめられなければ）その説明と追いつくコマンド。追いついていれば None。"""
    behind = _behind(repo)
    if isinstance(behind, str):
        return f"{repo} が {UPSTREAM} に追いついているかを確かめられない（{behind}）"
    if not behind:
        return None
    return (f"{repo} の HEAD は {UPSTREAM} より {behind} コミット遅れている。"
            f"古いコードで判定しないよう止まる。追いつく: {_catch_up_command(repo)}")


def _fast_forward(repo: Path) -> str | None:
    """master にいて変更が無ければ早送りする。早送りしたら None、しなければ（できなければ）その理由。"""
    if _branch(repo) != BRANCH or _dirty(repo):
        return "master でないか変更があるので触らない"
    result = _git(repo, "merge", "-q", "--ff-only", UPSTREAM)
    if result.returncode == 0:
        return None
    return "早送りできなかった（" + (result.stderr.strip().splitlines() or [f"終了コード {result.returncode}"])[-1] + "）"


def require_current(repo: Path = REPO_ROOT) -> None:
    """遅れていれば、master にいて変更が無いときだけ早送りして進む。追いつけなければ（確かめられなければ）説明を出して止まる。"""
    behind = _behind(repo)
    if isinstance(behind, int) and behind and _fast_forward(repo) is None:
        print(f"{repo} を {UPSTREAM} へ {behind} コミット早送りした", file=sys.stderr)
    message = staleness(repo)
    if message:
        raise SystemExit(message)


def sync(repo: Path = REPO_ROOT) -> str:
    """master にいて変更が無ければ早送りする。何をしたか（しなかったか）を1行で返す。"""
    behind = _behind(repo)
    if isinstance(behind, str):
        return f"チェックアウトの遅れ: 確かめられなかった（{behind}）"
    if not behind:
        return f"チェックアウトの遅れ: なし（{UPSTREAM} を含む）"
    skipped = _fast_forward(repo)
    if skipped is None:
        return f"チェックアウトの遅れ: {UPSTREAM} へ {behind} コミット早送りした"
    return f"チェックアウトの遅れ: {UPSTREAM} より {behind} コミット遅れ（{skipped}）。追いつく: {_catch_up_command(repo)}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sync", action="store_true", help="条件を満たすときだけ早送りし、結果を1行出す（常に0で終わる）")
    args = parser.parse_args(argv)
    if args.sync:
        print(sync())
        return 0
    message = staleness()
    if message:
        print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
