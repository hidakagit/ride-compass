"""Pull Request で回す一覧を書く。backend/mutants の下で、plan.py のあとに打つ。

引数: 関数の一覧のファイル（diff_scope.py が書く）
環境変数 MUT_OUT の rows.json（plan.py が書く）から、一覧の関数の変異で、テストの当たるものを選び、関数ごとの基準
（BASE1・BASE2: 変異を入れずに同じテストの組み合わせを2回。runner.py の説明）と一緒に MUT_OUT/all.txt へ書く。
"""
import json
import os
import sys

OUT = os.environ["MUT_OUT"]
funcs = {line.strip() for line in open(sys.argv[1], encoding="utf-8") if line.strip()}
rows = json.load(open(os.path.join(OUT, "rows.json"), encoding="utf-8"))
mutants = sorted(r[1] for r in rows if r[2] > 0 and r[1].partition("__mutmut_")[0] in funcs)
tested = sorted({m.partition("__mutmut_")[0] for m in mutants})
pool = mutants + [f"{k}:{f}" for f in tested for k in ("BASE1", "BASE2")]
open(os.path.join(OUT, "all.txt"), "w", encoding="utf-8").write("\n".join(pool) + ("\n" if pool else ""))
untested = sorted({r[1].partition("__mutmut_")[0] for r in rows if r[2] == 0 and r[1].partition("__mutmut_")[0] in funcs})
json.dump({"funcs": sorted(funcs), "untested": untested}, open(os.path.join(OUT, "scope.json"), "w", encoding="utf-8"),
          ensure_ascii=False)
print("変わった関数", len(funcs), "変異", len(mutants), "テストの当たらない関数", len(untested))
