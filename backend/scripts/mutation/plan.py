"""変異ごとの当てるテストと、かかる時間の見込みを出し、回す変異の一覧を書く。backend/mutants の下で打つ。

書くもの（環境変数 MUT_OUT の場所）:
- rows.json: 変異ごとの（ファイル・変異・当てるテストの数・記録の段で測ったテストの秒の合計）
- all.txt: テストの当たる変異を全部、種を固定した無作為の並びで。分けて回すときは行を順に配る（ランナーごとに
  無作為の標本になり、途中で止まっても回した分が偏らない）
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
by = collections.defaultdict(lambda: [0, 0, 0.0])
for f, _k, c, s in rows:
    layer = f.split("/")[1] if f.count("/") > 1 else f
    by[layer][0] += 1
    by[layer][1] += c == 0
    by[layer][2] += s
for layer, v in sorted(by.items()):
    print(layer, v[0], v[1], round(v[2]))
pool = sorted(r[1] for r in rows if r[2] > 0)
random.Random(661).shuffle(pool)
open(os.path.join(OUT, "all.txt"), "w", encoding="utf-8").write("\n".join(pool) + "\n")
print("all.txt", len(pool), "件")
