"""変異ごとの当てるテストと、かかる時間の見込みを出し、回す変異の一覧を書く。backend/mutants の下で打つ。

書くもの（環境変数 MUT_OUT の場所）:
- rows.json: 変異ごとの（ファイル・変異・当てるテストの数・記録の段で測ったテストの秒の合計）
- all.txt: テストの当たる変異を全部、種を固定した無作為の並びで。分けて回すときは行を順に配る（ランナーごとに
  無作為の標本になり、途中で止まっても回した分が偏らない）。この台本の隣に一覧（recheck.txt・only.txt）があれば、その中身
テストの当たらない変異は回しても見つけようがないので、all.txt に入れず別に数える。
"""
import collections
import glob
import json
import os
import random

OUT = os.environ["MUT_OUT"]
st = json.load(open("mutmut-stats.json", encoding="utf-8"))
tbf = st["tests_by_mangled_function_name"]
dur = st["duration_by_test"]
rows = []
for f in glob.glob("app/**/*.meta", recursive=True):
    for k in json.load(open(f, encoding="utf-8"))["exit_code_by_key"]:
        tests = tbf.get(k.partition("__mutmut_")[0], [])
        rows.append((f[:-5].replace("\\", "/"), k, len(tests), sum(dur.get(t, 0) for t in tests)))
json.dump(rows, open(os.path.join(OUT, "rows.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("変異", len(rows), "テストの当たらない変異", sum(1 for r in rows if r[2] == 0),
      "テストの秒の合計", round(sum(r[3] for r in rows)))
by: dict[str, list[float]] = collections.defaultdict(lambda: [0, 0, 0.0])
for f, _k, c, s in rows:
    layer = f.split("/")[1] if f.count("/") > 1 else f
    by[layer][0] += 1
    by[layer][1] += c == 0
    by[layer][2] += s
for layer, v in sorted(by.items()):
    print(layer, v[0], v[1], round(v[2]))
pool = sorted(r[1] for r in rows if r[2] > 0)
random.Random(661).shuffle(pool)
# 一覧があれば、それだけを回す。recheck.txt は runner.py がテスト全体を当てる（importtime.py の説明）。only.txt は
# 記録のテスト（その関数を通るテスト）で回す——テストを消したあと、消したテストが見つけていた変異を残る側が
# 落とすかを確かめる。両方あれば recheck.txt を使う。
HERE = os.path.dirname(os.path.abspath(__file__))
# baseline.txt があれば、変異を入れない基準を回す（runner.py の説明）。行は関数の名前（mutmut の mangled name）か、
# 全部の関数なら「*」。「+orig」の行があれば、元の版（差し込んでいない版）の基準も回す。
BASELINE = os.path.join(HERE, "baseline.txt")
if os.path.exists(BASELINE):
    lines = [line.strip() for line in open(BASELINE, encoding="utf-8") if line.strip()]
    funcs = sorted({r[1].partition("__mutmut_")[0] for r in rows if r[2] > 0})
    if "*" not in lines:
        funcs = [f for f in funcs if f in lines]
    kinds = ["BASE1", "BASE2"] + (["ORIG"] if "+orig" in lines else [])
    pool = [f"{k}:{f}" for f in funcs for k in kinds]
    random.Random(661).shuffle(pool)
    open(os.path.join(OUT, "all.txt"), "w", encoding="utf-8").write("\n".join(pool) + "\n")
    print("baseline.txt の基準を回す", len(funcs), "関数", len(pool), "件")
    raise SystemExit(0)
for listed in ("recheck.txt", "only.txt"):
    if os.path.exists(os.path.join(HERE, listed)):
        pool = [line.strip() for line in open(os.path.join(HERE, listed), encoding="utf-8") if line.strip()]
        print(listed, "の一覧を回す")
        break
open(os.path.join(OUT, "all.txt"), "w", encoding="utf-8").write("\n".join(pool) + "\n")
print("all.txt", len(pool), "件")
