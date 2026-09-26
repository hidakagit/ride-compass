"""並行して動く複数のエージェントの間で、重い処理を1本ずつに絞るロック付き実行器。

何をロックの下に置くか（処理の段1つで決め、包みでは決めない）・保持の上限・独占の時間帯は
docs/conventions/orchestration.md「重い処理は機械全体で1本ずつ」が正本。

使い方:
    python scripts/lockrun.py -- '<bashコマンド文字列>'
    python scripts/lockrun.py --report [--since 2026-09-23T00:00] [--mine]

ロックはgitの共通ディレクトリ（全worktreeで共有される）の`lockrun/heavy.lock`に対するOSのファイル
ロック（Windowsは`msvcrt.locking`、それ以外は`fcntl.flock`）で取る。`finally`が走らない殺され方でも、
保持者のプロセスが終わればOSが放す。ロックのファイルは消さない——消すと、開いて待っている側と
作り直した側が別々のファイルを掴み、2本が同時に保持しうる。保持者の表示（待ち手・定期確認が読む）は
別のファイル`lockrun/heavy.owner.json`が持つ。Windowsのロックはその範囲の読み取りも拒むため、
ロックのファイルへは書かない。

保持者のプロセスだけが殺されてbashの子が残った場合、ロックは即座に放され、次の処理が子と並んで走る。

枠は機械全体で1つ（ロック名`heavy`）。

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
import time
from datetime import datetime

if os.name == "nt":
    import msvcrt
else:
    import fcntl

#: 1回の保持の上限。超えたら処理を打ち切ってロックを放す——1本が枠を持ち続けると、後ろに
#: 並んだ全員（数秒で終わるものも含む）が同じだけ待つ。npm ci・検査・テスト1段階はこの中に収まる。
MAX_HOLD_SECONDS = int(os.environ.get("LOCKRUN_MAX_HOLD_SECONDS", "600"))
TIMED_OUT = 124
HELD_ENV = "LOCKRUN_HELD"
POLL_SECONDS = 5
#: 機械全体で1つの枠の名前（ロックのファイル・保持者のファイル・記録の`lock`）。
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


def owner_path(root: str, name: str) -> str:
    return os.path.join(root, f"{name}.owner.json")


def read_owner(root: str, name: str) -> str:
    try:
        with open(owner_path(root, name), encoding="utf-8") as f:
            owner = json.load(f)
        return f"{owner.get('cwd')} / {owner.get('cmd')}"
    except (OSError, ValueError, AttributeError):
        return "不明"


def try_lock(fd: int) -> bool:
    try:
        if os.name == "nt":
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def unlock(fd: int) -> None:
    try:
        if os.name == "nt":
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def acquire(root: str, name: str) -> tuple[int, float]:
    """ロックを取ったファイル記述子と、待った秒数。"""
    fd = os.open(os.path.join(root, f"{name}.lock"), os.O_RDWR | os.O_CREAT)
    started = time.monotonic()
    last_report = -60.0
    while not try_lock(fd):
        waited = time.monotonic() - started
        if waited - last_report >= 60:
            print(f"[lockrun] {name} のロック待ち（保持者: {read_owner(root, name)}、待ち{int(waited)}秒）", flush=True)
            last_report = waited
        time.sleep(POLL_SECONDS)
    return fd, time.monotonic() - started


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


def run(command: str) -> int:
    name = LOCK_NAME
    root = lock_root()
    stop_file = os.path.join(os.path.dirname(root), "orchestration", "STOP")
    if os.path.exists(stop_file):
        # 司令塔やエージェントの協力に頼らずに、重い処理を新しく始めさせないための札（pushはpre-pushフックが止める）。
        print(f"[lockrun] 停止ファイル（{stop_file}）があるため {name} を始めません", flush=True)
        return 75
    if name in os.environ.get(HELD_ENV, "").split(","):
        # 枠を持った処理の中から同じ枠を取りに来た。待つと自分を待って止まる。
        return subprocess.run([find_bash(), "-c", command], cwd=os.getcwd(), check=False).returncode
    start = datetime.now().astimezone().isoformat(timespec="seconds")
    fd, wait_seconds = acquire(root, name)
    held_from = time.monotonic()
    returncode = -1
    try:
        with open(owner_path(root, name), "w", encoding="utf-8") as f:
            json.dump({"cwd": os.getcwd(), "cmd": command[:200], "pid": os.getpid(),
                       "at": datetime.now().astimezone().isoformat(timespec="seconds")}, f, ensure_ascii=False)
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
        unlock(fd)
        record = {
            "start": start, "lock": name, "cwd": os.getcwd(), "cmd": command[:200],
            "wait_s": round(wait_seconds, 1), "hold_s": round(time.monotonic() - held_from, 1),
            "rc": returncode,
        }
        with open(os.path.join(root, "log.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return returncode


def worktree_top() -> str:
    """呼び出した作業ディレクトリが属する作業ツリーの根（比べやすい形）。"""
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                         encoding="utf-8", check=True).stdout.strip()
    return os.path.normcase(os.path.normpath(top))


def under(cwd: str, top: str) -> bool:
    path = os.path.normcase(os.path.normpath(cwd))
    return path == top or path.startswith(top + os.sep)


def parse_time(value: str) -> datetime:
    """時刻の文字列。日付と時刻の間は空白でも`T`でもよく、時差が無ければ手元の時刻として読む。
    文字列のまま比べると、空白（`2026-09-26 22:39`）は`T`より前に並び、`--since`がその日の記録を全部拾う。"""
    at = datetime.fromisoformat(value.strip())
    return at if at.tzinfo else at.astimezone()


def parse_since(since: str) -> datetime:
    try:
        return parse_time(since)
    except ValueError:
        raise SystemExit(f"--since は時刻で書く（例: 2026-09-26 22:39）: {since}") from None


def report(since: str | None, mine: bool = False) -> int:
    log = os.path.join(lock_root(), "log.jsonl")
    if not os.path.exists(log):
        print("記録がありません")
        return 0
    start = parse_since(since) if since else None
    rows = []
    with open(log, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if start is None or parse_time(row["start"]) >= start:
                rows.append(row)
    if mine:
        # スロットは担当を替えて使い回すので、--since（依頼の時刻）と合わせて自分の分だけにする。
        top = worktree_top()
        rows = [r for r in rows if under(str(r.get("cwd") or ""), top)]
        print(f"作業ツリー {top} の記録{'（' + since + ' 以降）' if since else ''}")
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
        if head or not command:
            print("使い方: python scripts/lockrun.py -- '<bashコマンド文字列>'（重い段だけを包む。"
                  "docs/conventions/orchestration.md「重い処理は機械全体で1本ずつ」）")
            return 2
        return run(command)
    parser = argparse.ArgumentParser(description="ロック付き実行器の記録を集計する")
    parser.add_argument("--report", action="store_true", required=True)
    parser.add_argument("--since", help="この時刻（例: 2026-09-26 22:39。時差が無ければ手元の時刻）以降の記録だけを集計する")
    parser.add_argument("--mine", action="store_true",
                        help="呼び出した作業ツリー（とその下のディレクトリ）で走った記録だけを集計する")
    args = parser.parse_args()
    return report(args.since, args.mine)


if __name__ == "__main__":
    sys.exit(main())
