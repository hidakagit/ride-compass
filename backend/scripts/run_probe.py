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

接続情報は`backend/.env.oracle.local`（リポジトリに入れないため各自が置く）の
`DATABASE_URL`と`SSH_COMMAND`から読む。worktreeから実行したときは本体のチェックアウト側を
見る——gitignore対象のファイルはworktreeへコピーされないため。
"""

import argparse
import base64
import os
import pathlib
import subprocess
import sys

_BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
_CONTAINER = "ridecompass-backend"


def _env_file() -> pathlib.Path:
    """`.env.oracle.local`の在処。worktreeに無ければ本体のチェックアウトを見る。"""
    here = _BACKEND_DIR / ".env.oracle.local"
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
        candidate = main_checkout / "backend" / ".env.oracle.local"
        if candidate.exists():
            return candidate
    return here


def _read_env(key: str) -> str:
    path = _env_file()
    if not path.exists():
        raise SystemExit(f"{path} がない。本番への接続情報が要る")
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line[len(key) + 1 :].strip().strip('"')
    raise SystemExit(f"{path} に {key} が無い")


def _run_locally(probe: pathlib.Path) -> int:
    env = {
        **os.environ,
        "PROBE_DATABASE_URL": _read_env("DATABASE_URL"),
        "BACKEND_DIR": str(_BACKEND_DIR),
        "PYTHONIOENCODING": "utf-8",
    }
    return subprocess.call([sys.executable, str(probe)], env=env)


def _run_in_container(probe: pathlib.Path) -> int:
    """VMへ転送してコンテナ内で走らせる。

    パイプやリダイレクトを含むコマンドを`eval`で組むと引用が崩れて黙って空になるため、
    base64で1つの引数へ畳んでから展開する。
    """
    ssh = _read_env("SSH_COMMAND").split()
    encoded = base64.b64encode(probe.read_bytes()).decode("ascii")
    name = probe.name
    remote = (
        f"printf %s '{encoded}' > /tmp/{name}.b64 && base64 -d /tmp/{name}.b64 > /tmp/{name}"
        f" && sudo docker cp /tmp/{name} {_CONTAINER}:/tmp/{name}"
        f" && sudo docker exec -w /app -e PYTHONPATH=/app {_CONTAINER} python /tmp/{name}"
        f"; sudo docker exec {_CONTAINER} rm -f /tmp/{name}; rm -f /tmp/{name} /tmp/{name}.b64"
    )
    return subprocess.call([*ssh, remote])


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
