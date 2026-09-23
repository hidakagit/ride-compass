"""並行して動く複数のエージェントの間で、重い処理を1本ずつに絞るロック付き実行器。

何をロックの下に置くか（処理の段1つで決め、包みでは決めない）・保持の上限・独占の時間帯は
docs/conventions/orchestration.md「重い処理は機械全体で1本ずつ」が正本。

使い方:
    python scripts/lockrun.py heavy -- '<bashコマンド文字列>'
    python scripts/lockrun.py --report [--since 2026-09-23T00:00]

ロックはgitの共通ディレクトリ（全worktreeで共有される）の`lockrun/`に置き、ディレクトリの
mkdir（原子的）で取る。保持中は30秒ごとにmtimeを更新し、5分以上更新の無いロックは持ち主が
死んだものとして破棄する——ツールの時間切れでプロセスが殺されると`finally`が走らないため。
破棄したときは、保持者のpidがその時点で生きていたか・そのプロセス名を`lockrun/breaks.jsonl`へ
追記する（生きている保持者の枠が破棄されたなら、破棄の規則のほうが誤っている）。

ロック名は`heavy`だけを受け、それ以外の名前（種類別だったころの旧名を含む）は走らせずに止める。

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

from orchestration import procs

STALE_SECONDS = 300
HEARTBEAT_SECONDS = 30
#: 1回の保持の上限。超えたら処理を打ち切ってロックを放す——1本が枠を持ち続けると、後ろに
#: 並んだ全員（数秒で終わるものも含む）が同じだけ待つ。npm ci・検査・テスト1段階はこの中に収まる。
MAX_HOLD_SECONDS = int(os.environ.get("LOCKRUN_MAX_HOLD_SECONDS", "600"))
TIMED_OUT = 124
HELD_ENV = "LOCKRUN_HELD"
POLL_SECONDS = 5
#: 機械全体で1つの枠。別の名前は別の枠になり、その下の処理は`heavy`と同時に走ってCPUを取り合う。
#: 旧名を`heavy`と読み替えもしない——旧`git-push`はpushを包んでいたが、pushは枠に入れない。
LOCK_NAME = "heavy"
WINDOWS_BASH = (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe")


def lock_root() -> str:
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True, text=True, encoding="utf-8", check=True,
        # 呼び出し元の作業ディレクトリはgitの外（スクラッチ等）のことがある。
        cwd=os.path.dirname(os.path.abspath(__file__)),
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


def load_owner(path: str) -> dict:
    try:
        with open(os.path.join(path, "owner.json"), encoding="utf-8") as f:
            owner = json.load(f)
        return owner if isinstance(owner, dict) else {}
    except (OSError, ValueError):
        return {}


def read_owner(path: str) -> str:
    owner = load_owner(path)
    return f"{owner.get('cwd')} / {owner.get('cmd')}" if owner else "不明"


def record_break(path: str, name: str, age: float) -> None:
    owner = load_owner(path)
    pid = owner.get("pid")
    table = procs.processes() if isinstance(pid, int) else None
    proc = table.get(pid) if table is not None else None
    alive = None if table is None else proc is not None
    record = {
        "at": datetime.now().astimezone().isoformat(timespec="seconds"), "lock": name, "age_s": int(age),
        "holder_pid": pid, "holder_alive": alive, "holder_name": proc.name if proc else None,
        # pidは再利用されうる。生きていたときは、それが本当にlockrunかをコマンドラインで見分ける。
        "holder_cmdline": (proc.cmdline or "")[:300] if proc else None,
        "owner_cwd": owner.get("cwd"), "owner_cmd": owner.get("cmd"), "breaker_pid": os.getpid(),
    }
    state = {True: "生きていた", False: "死んでいた", None: "生死を確かめられなかった"}[alive]
    print(f"[lockrun] {name} のロックが{int(age)}秒更新されていないため破棄します"
          f"（保持者 pid {pid} は{state}{f'、{proc.name}' if proc else ''}）", flush=True)
    with open(os.path.join(os.path.dirname(path), "breaks.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


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
                record_break(path, name, age)
                shutil.rmtree(path, ignore_errors=True)
                continue
            waited = time.monotonic() - started
            if waited - last_report >= 60:
                print(f"[lockrun] {name} のロック待ち（保持者: {read_owner(path)}、待ち{int(waited)}秒）", flush=True)
                last_report = waited
            time.sleep(POLL_SECONDS)


def kill_tree(proc: subprocess.Popen) -> None:
    # bashの子（npm・node・pytest等）まで止めないと、ロックを放した後も機械を使い続ける。
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False)
    else:
        proc.kill()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pass


def run(name: str, command: str) -> int:
    if name != LOCK_NAME:
        print(f"[lockrun] ロック名 {name} は受けない。重い段は {LOCK_NAME} で呼び、軽い段（git push を含む）は"
              "枠を通さずにそのまま走らせる（docs/conventions/orchestration.md「重い処理は機械全体で1本ずつ」）。"
              "この名前を指示した手順があるなら、その出どころを直すこと", flush=True)
        return 2
    root = lock_root()
    stop_file = os.path.join(os.path.dirname(root), "orchestration", "STOP")
    if os.path.exists(stop_file):
        # 司令塔やエージェントの協力に頼らずに、重い処理とpushを止めるための札。
        print(f"[lockrun] 停止ファイル（{stop_file}）があるため {name} を始めません", flush=True)
        return 75
    if name in os.environ.get(HELD_ENV, "").split(","):
        # 枠を持った処理の中から同じ枠を取りに来た。待つと自分を待って止まる。
        return subprocess.run([find_bash(), "-c", command], cwd=os.getcwd(), check=False).returncode
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
        held = ",".join(filter(None, [os.environ.get(HELD_ENV, ""), name]))
        proc = subprocess.Popen([find_bash(), "-c", command], cwd=os.getcwd(), env={**os.environ, HELD_ENV: held})
        try:
            returncode = proc.wait(timeout=MAX_HOLD_SECONDS)
        except subprocess.TimeoutExpired:
            kill_tree(proc)
            returncode = TIMED_OUT
            print(f"[lockrun] {name} の保持が上限{MAX_HOLD_SECONDS}秒を超えたため打ち切りました。"
                  "処理を上限内に分けるか、司令塔に独占の枠を求めること", flush=True)
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
            print(f"使い方: python scripts/lockrun.py {LOCK_NAME} -- '<bashコマンド文字列>'")
            return 2
        return run(head[0], command)
    parser = argparse.ArgumentParser(description="ロック付き実行器の記録を集計する")
    parser.add_argument("--report", action="store_true", required=True)
    parser.add_argument("--since", help="この時刻（ISO形式の前方一致比較）以降の記録だけを集計する")
    args = parser.parse_args()
    return report(args.since)


if __name__ == "__main__":
    sys.exit(main())
