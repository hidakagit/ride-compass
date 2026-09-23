"""並行して動く複数のエージェントの間で、重い処理を1本ずつに絞るロック付き実行器。

使い方:
    python scripts/lockrun.py <ロック名> -- '<bashコマンド文字列>'
    python scripts/lockrun.py --report [--since 2026-09-23T00:00]

ロックはgitの共通ディレクトリ（全worktreeで共有される）の`lockrun/`に置き、ディレクトリの
mkdir（原子的）で取る。保持中は30秒ごとにmtimeを更新し、5分以上更新の無いロックは持ち主が
死んだものとして破棄する——ツールの時間切れでプロセスが殺されると`finally`が走らないため。

実行のたびに待ち時間・保持時間・終了コードを`lockrun/log.jsonl`へ追記する。`--report`は
それをロック名ごとに集計する。並行実行の運用（docs/conventions/orchestration.md）を実測で
直すための計測値であり、ロックの正しさには関与しない。
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime

STALE_SECONDS = 300
HEARTBEAT_SECONDS = 30
POLL_SECONDS = 5
WINDOWS_BASH = (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe")


def lock_root() -> str:
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout.strip()
    root = os.path.join(common, "lockrun")
    os.makedirs(root, exist_ok=True)
    return root


def find_bash() -> str:
    # PATH上の`bash`はWindowsではWSLのものが先に当たりうる。
    for candidate in WINDOWS_BASH:
        if os.path.exists(candidate):
            return candidate
    return shutil.which("bash") or "bash"


def read_owner(path: str) -> str:
    try:
        with open(os.path.join(path, "owner.json"), encoding="utf-8") as f:
            owner = json.load(f)
        return f"{owner.get('cwd')} / {owner.get('cmd')}"
    except (OSError, ValueError):
        return "不明"


def acquire(path: str, name: str) -> float:
    started = time.monotonic()
    last_report = -60.0
    while True:
        try:
            os.mkdir(path)
            return time.monotonic() - started
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(path)
            except FileNotFoundError:
                continue
            if age > STALE_SECONDS:
                print(f"[lockrun] {name} のロックが{int(age)}秒更新されていないため破棄します", flush=True)
                shutil.rmtree(path, ignore_errors=True)
                continue
            waited = time.monotonic() - started
            if waited - last_report >= 60:
                print(f"[lockrun] {name} のロック待ち（保持者: {read_owner(path)}、待ち{int(waited)}秒）", flush=True)
                last_report = waited
            time.sleep(POLL_SECONDS)


def run(name: str, command: str) -> int:
    root = lock_root()
    path = os.path.join(root, name)
    start = datetime.now().astimezone().isoformat(timespec="seconds")
    wait_seconds = acquire(path, name)
    stop = threading.Event()

    def heartbeat() -> None:
        while not stop.wait(HEARTBEAT_SECONDS):
            try:
                os.utime(path)
            except OSError:
                pass

    held_from = time.monotonic()
    returncode = -1
    try:
        with open(os.path.join(path, "owner.json"), "w", encoding="utf-8") as f:
            json.dump({"cwd": os.getcwd(), "cmd": command[:200], "pid": os.getpid()}, f, ensure_ascii=False)
        threading.Thread(target=heartbeat, daemon=True).start()
        print(f"[lockrun] {name} のロックを取得（待ち{int(wait_seconds)}秒）", flush=True)
        returncode = subprocess.run([find_bash(), "-c", command], cwd=os.getcwd(), check=False).returncode
    finally:
        stop.set()
        shutil.rmtree(path, ignore_errors=True)
        record = {
            "start": start, "lock": name, "cwd": os.getcwd(), "cmd": command[:200],
            "wait_s": round(wait_seconds, 1), "hold_s": round(time.monotonic() - held_from, 1),
            "rc": returncode,
        }
        with open(os.path.join(root, "log.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return returncode


def report(since: str | None) -> int:
    log = os.path.join(lock_root(), "log.jsonl")
    if not os.path.exists(log):
        print("記録がありません")
        return 0
    rows = []
    with open(log, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if since is None or row["start"] >= since:
                rows.append(row)
    by_lock: dict[str, list[dict]] = {}
    for row in rows:
        by_lock.setdefault(row["lock"], []).append(row)
    print(f"{'ロック':16} {'回数':>5} {'失敗':>5} {'待ち合計(分)':>12} {'待ち最大(分)':>12} {'保持合計(分)':>12}")
    for name, items in sorted(by_lock.items()):
        waits = [r["wait_s"] for r in items]
        print(
            f"{name:16} {len(items):>5} {sum(1 for r in items if r['rc'] != 0):>5} "
            f"{sum(waits) / 60:>12.1f} {max(waits) / 60:>12.1f} {sum(r['hold_s'] for r in items) / 60:>12.1f}"
        )
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    if "--" in sys.argv:
        split = sys.argv.index("--")
        head, command = sys.argv[1:split], " ".join(sys.argv[split + 1:])
        if len(head) != 1 or not command:
            print("使い方: python scripts/lockrun.py <ロック名> -- '<bashコマンド文字列>'")
            return 2
        return run(head[0], command)
    parser = argparse.ArgumentParser(description="ロック付き実行器の記録を集計する")
    parser.add_argument("--report", action="store_true", required=True)
    parser.add_argument("--since", help="この時刻（ISO形式の前方一致比較）以降の記録だけを集計する")
    args = parser.parse_args()
    return report(args.since)


if __name__ == "__main__":
    sys.exit(main())
