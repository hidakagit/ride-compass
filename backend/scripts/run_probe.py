"""調査用スクリプトを本番DBに対して走らせる。

性能・データの計測は本番DBで行う（開発DBはスペックも中身も前提が違う）。その都度
接続先を手で組み立てると、環境変数の付け忘れ・SSHの引用の崩れで失敗する。ここへ寄せる。

    # 手元のPythonから本番DBを引く（読み取りのみの調査はこちら）
    python scripts/run_probe.py path/to/probe.py

    # 本番コンテナの中で走らせる（アプリと同じ環境・localhost接続で測りたいとき）
    python scripts/run_probe.py --in-container path/to/probe.py

手元実行の場合、プローブは`PROBE_DATABASE_URL`（本番の接続文字列）と`BACKEND_DIR`
（`app`パッケージのある場所）を環境変数から受け取る。コンテナ実行の場合は
`app.config.settings.database_url`をそのまま使えばよい。

接続情報は`backend/.env.oracle.local`の`DATABASE_URL`と`SSH_COMMAND`から読む（在処の探し方は`_prod_env.py`）。
"""

import argparse
import os
import pathlib
import subprocess
import sys

from _prod_env import read_prod_env

_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
_CONTAINER = "ridecompass-backend"


def _run_locally(probe: pathlib.Path) -> int:
    env = {
        **os.environ,
        "PROBE_DATABASE_URL": read_prod_env("DATABASE_URL"),
        "BACKEND_DIR": str(_BACKEND_DIR),
        "PYTHONIOENCODING": "utf-8",
    }
    return subprocess.call([sys.executable, str(probe)], env=env)


def _run_in_container(probe: pathlib.Path) -> int:
    """プローブの本文を標準入力でコンテナ内のPythonへ流す（VMにもコンテナにもファイルを残さない）。"""
    ssh = read_prod_env("SSH_COMMAND").split()
    remote = f"sudo docker exec -i -w /app -e PYTHONPATH=/app {_CONTAINER} python -"
    with probe.open("rb") as source:
        return subprocess.call([*ssh, remote], stdin=source)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("probe", type=pathlib.Path, help="走らせるPythonファイル")
    parser.add_argument(
        "--in-container",
        action="store_true",
        help="本番VMのbackendコンテナ内で走らせる（既定は手元のPythonから本番DBを引く）",
    )
    args = parser.parse_args(argv)
    if not args.probe.exists():
        raise SystemExit(f"{args.probe} がない")
    return _run_in_container(args.probe) if args.in_container else _run_locally(args.probe)


if __name__ == "__main__":
    from _stdio import use_utf8_stdio

    use_utf8_stdio()
    raise SystemExit(main())
