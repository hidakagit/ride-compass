"""本番へつなぐ道具が共有する、手元の接続情報の読み方。

接続情報は`backend/.env.oracle.local`（リポジトリに入れないため各自が置く）に置く。worktreeから実行したときは
本体のチェックアウト側を見る——gitignore対象のファイルはworktreeへコピーされないため。
"""

import pathlib
import subprocess

from dotenv import dotenv_values

_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
_FILE_NAME = ".env.oracle.local"


def prod_env_file() -> pathlib.Path:
    """`.env.oracle.local`の在処。worktreeに無ければ本体のチェックアウトを見る。"""
    here = _BACKEND_DIR / _FILE_NAME
    if here.exists():
        return here
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=_BACKEND_DIR, capture_output=True, check=False,
    )
    # 出力はパスのみ。環境の既定エンコーディングに左右されないようbytesで受ける
    # （日本語を含むパスでcp932のdecodeに失敗する）。
    common = result.stdout.decode("utf-8", "replace").strip()
    if common:
        main_checkout = (_BACKEND_DIR / common).resolve().parent
        candidate = main_checkout / "backend" / _FILE_NAME
        if candidate.exists():
            return candidate
    return here


def read_prod_env(key: str) -> str:
    """鍵の値。ファイルか鍵が無ければ、どこに何を足せばよいかを言って止まる（値は出さない）。"""
    path = prod_env_file()
    if not path.exists():
        raise SystemExit(f"{path} がない。本番への接続情報が要る")
    value = dotenv_values(path, encoding="utf-8").get(key)
    if not value:
        raise SystemExit(f"{path} に {key} が無い")
    return value
