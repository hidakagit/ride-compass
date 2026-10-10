"""テストが一時ディレクトリに作るgitのリポジトリを操作する道具。"""

import subprocess
from pathlib import Path


def git(repo: Path, *args: str) -> str:
    """`repo`で`git <args>`を打ち、標準出力を返す。コミットの名義は使い捨てのもので、開発機の設定を読まない。"""
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo, check=True, capture_output=True, text=True, encoding="utf-8",
    ).stdout.strip()
