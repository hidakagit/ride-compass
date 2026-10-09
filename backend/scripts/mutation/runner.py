"""変異ごとに別のプロセスで pytest を打ち、当てるテストを最後まで回す（最初の失敗で止めない）。backend/mutants の下で打つ。

引数: 変異の一覧のファイル 結果の JSONL 担い手の数
環境変数:
- MUT_OUT: 落ちたテストの記録（kills/）と、テストの名前を渡すファイル（args/）を置く場所
- MUT_DB_PREFIX: 担い手ごとのテストDBの名前の頭（<頭><番号>。前もって作っておく）
- MUT_STOP_AFTER: 始めてからこの秒数を過ぎたら、新しい変異を取らずに抜ける（ジョブの持ち時間の前に結果を残す。任意）
済んだ変異（結果の JSONL にあるもの）は飛ばすので、止まっても打ち直せる。MUT_OUT に STOP というファイルを置いても止まる。
"""
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
done = set()
if os.path.exists(out_path):
    done = {json.loads(line)["mutant"] for line in open(out_path, encoding="utf-8")}
stats = json.load(open("mutmut-stats.json", encoding="utf-8"))
tbf = stats["tests_by_mangled_function_name"]
dur = stats["duration_by_test"]

q = queue.Queue()
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
        tests = sorted(tbf.get(name.partition("__mutmut_")[0], []))
        if not tests:
            rec = {"mutant": name, "status": "no tests", "seconds": 0}
        else:
            limit = 60 + 5 * sum(dur.get(t, 0) for t in tests)
            env["MUTANT_UNDER_TEST"] = name
            t0 = time.time()
            # テストの名前を引数に並べると命令行の長さの上限を超えうるので、ファイルで渡す（pytest の @ファイル）。
            args_file = os.path.join(args_dir, f"w{slot}.txt")
            with open(args_file, "w", encoding="utf-8") as f:
                f.write("\n".join(tests))
            try:
                p = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q", "--rootdir=.", "--tb=no", "-p", "no:cacheprovider",
                     "-p", "no:randomly", "-p", "mutkill", "-o", "timeout=60", f"@{args_file}"],
                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=limit)
                code = p.returncode
                status = {0: "survived", 1: "killed"}.get(code, f"exit {code}")
                err = p.stderr.decode(errors="replace")[-300:] if code not in (0, 1) else ""
            except subprocess.TimeoutExpired:
                status, err = "timeout", ""
            rec = {"mutant": name, "status": status, "seconds": round(time.time() - t0, 2), "tests": len(tests)}
            if err:
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
