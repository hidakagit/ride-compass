"""計測した作業コピーの素性（HEAD・origin/masterとの一致・未コミットの変更）を出す。

ベンチマークの数字はタスクエントリへ「本番実測」として引用される。どのコードを測ったかが
数字と一緒に残っていないと、作業コピーが古いまま測ったときに出るのはエラーではなく
「古いコードのもっともらしい数字」になり、後から気づく手段が無い。
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

SKIP_ENV = "BENCH_SKIP_REVISION_CHECK"


@dataclass(frozen=True)
class RevisionState:
    head: str | None
    remote_head: str | None
    dirty: bool


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def read_revision_state() -> RevisionState:
    """作業コピーのHEADと、配信元（origin/master）の現在のHEADを読む。

    `ls-remote`で配信元へ直接聞く——手元の`origin/master`はfetchするまで動かないため、
    それと比べても「古いまま測っている」ことを検出できない。
    """
    head = _git("rev-parse", "HEAD")
    remote = _git("ls-remote", "origin", "refs/heads/master")
    remote_head = remote.split()[0] if remote else None
    status = _git("status", "--porcelain")
    return RevisionState(head=head, remote_head=remote_head, dirty=bool(status))


def describe(state: RevisionState) -> str:
    """結果へ添える1行。どのコードを測ったかを数字と同じ出力に残す。"""
    head = state.head[:12] if state.head else "不明"
    parts = [f"計測した作業コピー: {head}"]
    if state.dirty:
        parts.append("未コミットの変更あり")
    if state.remote_head and state.head and state.remote_head != state.head:
        parts.append(f"origin/master: {state.remote_head[:12]}")
    return "（" + "／".join(parts) + "）"


def stale_reason(state: RevisionState) -> str | None:
    """測る前に止めるべき理由。問題が無ければNone。

    配信元を引けない（ネットワーク断・gitが無い）ときは止めない——測れないことより、
    測れるのに測らせないことの害が大きい。素性は`describe`が出力へ残す。
    """
    if state.head is None or state.remote_head is None:
        return None
    if state.head != state.remote_head:
        return (
            f"作業コピーが配信元と違うコミットです（手元 {state.head[:12]} / "
            f"origin/master {state.remote_head[:12]}）。古いコードを測ると、誤りではなく"
            "もっともらしい数字が出ます。`git fetch origin master && git reset --hard origin/master`"
            f"で揃えるか、意図した計測なら環境変数 {SKIP_ENV}=1 を付けて実行してください。"
        )
    return None


def require_current_revision() -> RevisionState:
    """素性を1行出し、古ければ止める。`BENCH_SKIP_REVISION_CHECK=1`で止めない。"""
    state = read_revision_state()
    print(describe(state))
    reason = stale_reason(state)
    if reason is None:
        return state
    if os.environ.get(SKIP_ENV):
        print(f"警告: {reason}")
        return state
    raise SystemExit(reason)
