"""重い処理（テスト・ビルド・依存の入れ直し）を、この機械全体で1本ずつ走らせる。
使い方: python scripts/heavy.py -- <コマンド> [引数...]
枠は git の共通ディレクトリ（全ての作業ツリーで同じ）の heavy.lock を OS のファイルロックで取り合う。
取れるまで待ち、コマンドが終わると（落ちても）放す。終了コードはコマンドのものを返す。
同時に走ると CPU とディスクを取り合って1本ごとの所要が何倍にも伸びるため、並ばせる（docs/conventions/flow.md「司令塔と担当」）。
"""
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.stderr.reconfigure(encoding="utf-8")
if len(sys.argv) < 3 or sys.argv[1] != "--":
    raise SystemExit("使い方: python scripts/heavy.py -- <コマンド> [引数...]")
common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()
path = Path(common) / "heavy.lock"
path.touch(exist_ok=True)

with open(path, "r+b") as f:
    if sys.platform == "win32":
        import msvcrt

        def lock() -> bool:
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                return False
    else:
        import fcntl

        def lock() -> bool:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                return False

    start = time.monotonic()
    while not lock():
        if int(time.monotonic() - start) % 60 == 0:
            print(f"heavy: ほかの重い処理を待っている（{int(time.monotonic() - start)}秒）", file=sys.stderr, flush=True)
        time.sleep(1)
    waited = time.monotonic() - start
    if waited >= 1:
        print(f"heavy: {waited:.0f}秒待って枠を取った", file=sys.stderr, flush=True)
    # 枠はファイルを閉じると OS が放す（コマンドが落ちても、このプロセスが殺されても残らない）。
    # Windows の npm・npx などは .cmd なので、拡張子の無い Unix 用のファイルより先に .cmd・.exe を探す。
    name = sys.argv[2]
    found = (shutil.which(f"{name}.cmd") or shutil.which(f"{name}.exe")) if sys.platform == "win32" and "." not in Path(name).name else None
    command = [found or shutil.which(name) or name, *sys.argv[3:]]
    sys.exit(subprocess.run(command, check=False).returncode)
