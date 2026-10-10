"""変異ごとに別のプロセスで pytest を打ち、当てるテストを最後まで回す（最初の失敗で止めない）。backend/mutants の下で打つ。

引数: 変異の一覧のファイル 結果の JSONL 担い手の数
環境変数:
- MUT_OUT: 落ちたテストの記録（kills/）と、テストの名前を渡すファイル（args/）を置く場所
- MUT_DB_PREFIX: 担い手ごとのテストDBの名前の頭（<頭><番号>。前もって作っておく）
- MUT_STOP_AFTER: 始めてからこの秒数を過ぎたら、新しい変異を取らずに抜ける（ジョブの持ち時間の前に結果を残す。任意）
済んだ変異（結果の JSONL にあるもの）は飛ばすので、止まっても打ち直せる。MUT_OUT に STOP というファイルを置いても止まる。
この台本の隣に recheck.txt があれば、そこに並んだ変異には記録のテストでなくテスト全体を当てる（担い手を1つにし、
1件の中を pytest-xdist で並べる。importtime.py の説明）。
"""
import configparser
import json
import os
import queue
import subprocess
import sys
import threading
import time

OUT = os.environ["MUT_OUT"]
DB_PREFIX = os.environ["MUT_DB_PREFIX"]
STOP_AFTER = float(os.environ.get("MUT_STOP_AFTER") or "inf")
names = [line.strip() for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
out_path = sys.argv[2]
workers = int(sys.argv[3])
HERE = os.path.dirname(os.path.abspath(__file__))
RECHECK_FILE = os.path.join(HERE, "recheck.txt")
RECHECK = set()
if os.path.exists(RECHECK_FILE):
    RECHECK = {line.strip() for line in open(RECHECK_FILE, encoding="utf-8") if line.strip()}
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(HERE, "setup.cfg"), encoding="utf-8")
    FULL_SELECTION = cfg["mutmut"]["pytest_add_cli_args_test_selection"].split()
    XDIST = ["-n", str(workers), "--dist", "loadgroup"]
    workers = 1
done = set()
if os.path.exists(out_path):
    done = {json.loads(line)["mutant"] for line in open(out_path, encoding="utf-8")}
stats = json.load(open("mutmut-stats.json", encoding="utf-8"))
tbf = stats["tests_by_mangled_function_name"]
dur = stats["duration_by_test"]

q: queue.Queue[str] = queue.Queue()
for n in names:
    if n not in done:
        q.put(n)
total = q.qsize()
lock = threading.Lock()
started = time.time()
count = [0]
stop_file = os.path.join(OUT, "STOP")
kill_dir = os.path.join(OUT, "kills")
args_dir = os.path.join(OUT, "args")
os.makedirs(kill_dir, exist_ok=True)
os.makedirs(args_dir, exist_ok=True)


def stopping():
    return os.path.exists(stop_file) or time.time() - started > STOP_AFTER


#: 1件の pytest のデータ領域の上限（Linux だけ）。メモリを食い尽くす変異が、ランナーごと止める（shutdown signal で
#: 成果物も残らない）のを防ぐ。超えた変異は MemoryError でテストが落ち、見つけた側に数える。上限が普通の変異を
#: 誤って落としていないかは、記録する最大のメモリ（maxrss_mb）で確かめる。CI の backend と同じランナーは 16GB で、担い手は4つ。
DATA_LIMIT = 3584 * 1024 * 1024


def run_child(cmd, env, limit, err_path, cwd=None):
    """子を起こして終わりを待つ。返すのは（終わりの値か時間切れの None・標準エラーの末尾・最大のメモリ MB か None）。"""
    with open(err_path, "w+b") as err_file:
        if os.name == "nt":
            try:
                p = subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL, stderr=err_file, timeout=limit, cwd=cwd)
                code = p.returncode
            except subprocess.TimeoutExpired:
                code = None
            maxrss = None
        else:
            import resource
            import signal

            proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=err_file, start_new_session=True,
                                    cwd=cwd)
            resource.prlimit(proc.pid, resource.RLIMIT_DATA, (DATA_LIMIT, DATA_LIMIT))
            deadline = time.time() + limit
            while True:
                pid, wstatus, usage = os.wait4(proc.pid, os.WNOHANG)
                if pid:
                    code = os.waitstatus_to_exitcode(wstatus)
                    maxrss = round(usage.ru_maxrss / 1024)
                    proc.returncode = code
                    break
                if time.time() > deadline:
                    os.killpg(proc.pid, signal.SIGKILL)
                    _, _, usage = os.wait4(proc.pid, 0)
                    code, maxrss = None, round(usage.ru_maxrss / 1024)
                    proc.returncode = -9
                    break
                time.sleep(0.2)
        err_file.seek(0)
        err = err_file.read().decode(errors="replace")[-300:]
    return code, err, maxrss


def work(slot):
    url = f"postgresql+asyncpg://ridecompass:ridecompass@localhost:5432/{DB_PREFIX}{slot}"
    env = dict(os.environ, TEST_DATABASE_URL=url, DATABASE_URL=url, PYTHONPATH=os.path.dirname(os.path.abspath(__file__)),
               MUTKILL_DIR=kill_dir, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    # 差し込んだ版のファイルは大きい（元の100倍を超えるものがある）。.pyc を書かせないと、プロセスごとに翻訳し直して
    # 起動が遅くなる（Windows の開発機で 6秒 → 33秒）。
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    while not stopping():
        try:
            name = q.get_nowait()
        except queue.Empty:
            return
        base_kind, _, base_func = name.partition(":")
        if base_func:
            # 基準: 変異を入れずに、その関数の変異と同じテストの組み合わせを同じ並びで回す（BASE1・BASE2 は差し込んだ版を2回、
            # ORIG は元の版）。基準で落ちるテストは、変異の回で落ちても見つけたとは言えない。
            tests = sorted(tbf.get(base_func, []))
        else:
            tests = sorted(tbf.get(name.partition("__mutmut_")[0], []))
        if name in RECHECK:
            tests = FULL_SELECTION
            extra = XDIST
            limit = 1800
        else:
            extra = []
            limit = 60 + 5 * sum(dur.get(t, 0) for t in tests)
        if not tests:
            rec = {"mutant": name, "status": "no tests", "seconds": 0}
        else:
            env["MUTANT_UNDER_TEST"] = "" if base_func else name
            env["MUTKILL_NAME"] = name
            t0 = time.time()
            # テストの名前を引数に並べると命令行の長さの上限を超えうるので、ファイルで渡す（pytest の @ファイル）。
            args_file = os.path.join(args_dir, f"w{slot}.txt")
            with open(args_file, "w", encoding="utf-8") as f:
                f.write("\n".join(tests))
            # 回し始めた変異をジョブの記録に出す（ランナーごと止まったとき、走っていた変異が分かるように）。
            print("始め", name, flush=True)
            code, err, maxrss = run_child(
                [sys.executable, "-m", "pytest", "-q", "--rootdir=.", "--tb=no", "-p", "no:cacheprovider",
                 "-p", "no:randomly", "-p", "mutkill", "-o", "timeout=60", *extra, f"@{args_file}"],
                env, limit, os.path.join(args_dir, f"w{slot}.err"),
                cwd=".." if base_kind == "ORIG" and base_func else None)  # 元の版は差し込んだ版の1つ上（backend）
            if code is None:
                status = "timeout"
            else:
                status = {0: "survived", 1: "killed"}.get(code, f"exit {code}")
            rec = {"mutant": name, "status": status, "seconds": round(time.time() - t0, 2), "tests": len(tests)}
            if maxrss is not None:
                rec["maxrss_mb"] = maxrss
            if code not in (0, 1, None) and err:
                rec["stderr"] = err
        with lock:
            with open(out_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            count[0] += 1
            if count[0] % 100 == 0:
                el = time.time() - started
                print(f"{count[0]}/{total} 件 {round(el)} 秒（残りの見込み {round(el / count[0] * (total - count[0]) / 60)} 分）",
                      flush=True)


threads = [threading.Thread(target=work, args=(i,)) for i in range(workers)]
for t in threads:
    t.start()
for t in threads:
    t.join()
print("終わり", count[0], "/", total, "件", round(time.time() - started), "秒", flush=True)
