"""変異テストの結果を集計する。backend の下で、測った版と同じ版のチェックアウトで打つ（テスト関数の行数を tests/ から数える）。

引数: 成果物を取ってきた場所（gh run download で mutation-<番号> のディレクトリが並ぶ所）［当て直しの成果物の場所］
出すもの（標準出力と、同じ場所の summary.json・pertest.json・survivors.json）:
- 層ごとの変異スコア（95%の幅つき）。テストの当たらない変異は回していないので、別に数える
- テスト1本ごとの発見と重なり（ほかに無い発見・全部の発見を保つ最小の組・広く壊れたときにしか落ちない）と、その行数
状態の読み方: 終わりの値 0 は生き残り、1 は落ちた、2〜4 は集める時点で落ちた（変異が import やパラメータの組を壊した。
素の版では集まる）、時間切れは止まらなくなったもの。落ちた・集める時点で落ちた・時間切れを見つけた側に数える。
"""
import ast
import collections
import glob
import json
import math
import os
import sys
from pathlib import Path

ART = sys.argv[1]
RECHECK_ART = sys.argv[2] if len(sys.argv) > 2 else None
shard_dirs = sorted(glob.glob(os.path.join(ART, "mutation-*")))
rows = json.load(open(os.path.join(shard_dirs[0], "rows.json"), encoding="utf-8"))
stats = json.load(open(os.path.join(shard_dirs[0], "mutmut-stats.json"), encoding="utf-8"))
tbf = {k: set(v) for k, v in stats["tests_by_mangled_function_name"].items()}
all_tests = set(stats["duration_by_test"])
file_of = {r[1]: r[0] for r in rows}

results = {}
kills = collections.defaultdict(set)
for d in shard_dirs:
    path = os.path.join(d, "results.jsonl")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            results[r["mutant"]] = r
    for f in glob.glob(os.path.join(d, "kills", "*.tsv")):
        for line in open(f, encoding="utf-8"):
            m, t, _when = line.rstrip("\n").split("\t")
            kills[m].add(t)

untested = [r[1] for r in rows if r[2] == 0]
planned = [r[1] for r in rows if r[2] > 0]
done = [m for m in planned if m in results]
print("変異", len(rows), "テストの当たらない変異", len(untested), "回す変異", len(planned), "済んだ", len(done))


def status(m):
    s = results[m]["status"]
    if s in ("killed", "survived", "timeout"):
        return s
    if s in ("exit 2", "exit 3", "exit 4"):
        return "collect"
    return s


def layer(m):
    parts = file_of[m].split("/")
    return parts[1] if len(parts) > 2 else parts[1].removesuffix(".py")


def wilson(k, n):
    if n == 0:
        return (0, 0)
    z = 1.96
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (c - h, c + h)


res = {m: status(m) for m in done}
# 当て直し（テスト全体を当てた生き残り。importtime.py）で落ちたものを「テスト全体で落ちた」へ移す。どのテストが
# 落ちたかは、テストごとの発見に足さない（記録のテストの外で見つけたもので、重なりの数を変えない）。
if RECHECK_ART:
    for d in glob.glob(os.path.join(RECHECK_ART, "mutation-*")):
        path = os.path.join(d, "results.jsonl")
        if os.path.exists(path):
            for line in open(path, encoding="utf-8"):
                r = json.loads(line)
                if res.get(r["mutant"]) == "survived" and r["status"] != "survived":
                    res[r["mutant"]] = "full"
print("状態", dict(collections.Counter(res.values())))
by: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
for m in done:
    by[layer(m)][res[m]] += 1
    by["全体"][res[m]] += 1
no_test_by = collections.Counter(layer(m) for m in untested)
no_test_by["全体"] = len(untested)
summary = {}
print("\n| 層 | 回した変異 | 落ちた | 集める時点で落ちた | 時間切れ | テスト全体で落ちた | 生き残り | ほか | スコア | 95%の幅 |"
      " テストの当たらない変異 |")
for name in sorted(by, key=lambda x: (x == "全体", x)):
    c = by[name]
    n = sum(c.values())
    det = c["killed"] + c["timeout"] + c["collect"] + c["full"]
    other = n - det - c["survived"]
    lo, hi = wilson(det, n)
    summary[name] = {"n": n, "detected": det, **c, "other": other, "no_tests": no_test_by[name]}
    print(f"| {name} | {n} | {c['killed']} | {c['collect']} | {c['timeout']} | {c['full']} | {c['survived']} | {other} | "
          f"{det / n:.1%} | {lo:.1%}〜{hi:.1%} | {no_test_by[name]} |")

survivors = sorted(m for m in done if res[m] == "survived")
odd = {m: results[m] for m in done if res[m] not in ("killed", "survived", "timeout", "collect", "full")}
killed = [m for m in done if res[m] == "killed"]
print("\n落ちたが失敗の記録が無い", sum(1 for m in killed if not kills.get(m)), "／ ほかの終わり方", len(odd))

covering: dict[str, int] = collections.defaultdict(int)
for m in done:
    for t in tbf.get(m.partition("__mutmut_")[0], ()):
        covering[t] += 1
found = collections.defaultdict(set)
for m in killed:
    for t in kills.get(m, ()):
        found[t].add(m)

fn_lines: dict[tuple[str, str], int] = {}


def func_of(nodeid):
    path, _, rest = nodeid.partition("::")
    return path, rest.split("[")[0]


def lines_of(path, name):
    key = (path, name)
    if key not in fn_lines:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        n = 0
        body = tree.body
        parts = name.split("::")
        for i, p in enumerate(parts):
            for node in body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == p:
                    if i == len(parts) - 1:
                        start = node.decorator_list[0].lineno if node.decorator_list else node.lineno
                        n = (node.end_lineno or node.lineno) - start + 1
                    body = node.body
                    break
        fn_lines[key] = n
    return fn_lines[key]


def total_lines(tests):
    return sum(lines_of(*k) for k in {func_of(t) for t in tests})


no_cover_any = {t for t in all_tests if not any(t in v for v in tbf.values())}
covered = {t for t in all_tests if covering[t] > 0}
zero = {t for t in covered if not found.get(t)}
finders: collections.Counter[str] = collections.Counter()
for t in found:
    for m in found[t]:
        finders[m] += 1
unique = {t for t in found if any(finders[m] == 1 for m in found[t])}
redundant = set(found) - unique
broad_only = {t for t in found if all(finders[m] >= 100 for m in found[t])}
remaining = set(finders)
chosen = set()
while remaining:
    t = max(found, key=lambda x: (len(found[x] & remaining), x))
    chosen.add(t)
    remaining -= found[t]

groups = [("全体（収集した）", all_tests), ("どの変異の関数も通らない", no_cover_any), ("変異の関数を通る", covered),
          ("通るのに変異を1つも見つけない", zero), ("1つ以上見つけた", set(found)),
          ("見つけたものが全部ほかでも見つかる", redundant), ("ほかに無い発見を持つ", unique),
          ("全部の発見を保つ最小の組（貪欲法）", chosen), ("100本以上が一緒に落ちる書き換えだけで落ちた", broad_only)]
print("\n| 区分 | テスト | テスト関数 | 行数 |")
for name, s in groups:
    summary["tests:" + name] = {"tests": len(s), "functions": len({func_of(t) for t in s}), "lines": total_lines(s)}
    print(f"| {name} | {len(s)} | {len({func_of(t) for t in s})} | {total_lines(s)} |")
print("1本だけが見つけた変異", sum(1 for v in finders.values() if v == 1), "／ 見つけたテストの本数の中央",
      sorted(finders.values())[len(finders) // 2] if finders else 0)

per_file: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
for t in all_tests:
    r = per_file[func_of(t)[0]]
    r["テスト"] += 1
    r["通らない"] += t in no_cover_any
    r["見つけない"] += t in zero
    r["ほかに無い"] += t in unique
    r["最小の組"] += t in chosen
    r["広くだけ"] += t in broad_only
flines = {f: total_lines([t for t in all_tests if func_of(t)[0] == f]) for f in per_file}
print("\n| ファイル | テスト | 行数 | 関数を通らない | 通るのに見つけない | ほかに無い発見 | 最小の組 | 広くだけ |")
for f, r in sorted(per_file.items(), key=lambda x: -flines[x[0]])[:40]:
    print(f"| {f} | {r['テスト']} | {flines[f]} | {r['通らない']} | {r['見つけない']} | {r['ほかに無い']} | {r['最小の組']} | {r['広くだけ']} |")

json.dump(summary, open(os.path.join(ART, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump(survivors, open(os.path.join(ART, "survivors.json"), "w", encoding="utf-8"), indent=0)
json.dump({"odd": odd, "zero": sorted(zero), "no_cover_any": sorted(no_cover_any), "unique": sorted(unique),
           "chosen": sorted(chosen), "broad_only": sorted(broad_only),
           "found": {t: sorted(v) for t, v in found.items()},
           "per_file": {f: dict(r) for f, r in per_file.items()}, "lines": flines},
          open(os.path.join(ART, "pertest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
