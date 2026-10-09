"""Pull Request の変異の結果を知らせる。backend の下で、runner.py のあとに打つ。

引数: 比べる版（diff_scope.py に渡したもの）
読むもの（環境変数 MUT_OUT の場所）: results.jsonl・kills/（runner.py が書く）・scope.json（pr_plan.py が書く）。
- 生き残り: 変異を入れてもテストが1本も落ちなかったもの。落ちたテストが全部、その関数の基準（変異を入れない版で同じ組み合わせを
  2回）でも落ちたものも、生き残りに数える（変異と関係なく落ちていて、気づいたとは言えない）。集める時点で落ちたもの・
  時間切れは気づいた側。
- 生き残りのうち、書き換えた行が Pull Request で変わった行に当たるものを、その行への注記（GitHub Actions の
  `::warning file=…,line=…::…`）として出す。同じ行には1つだけ、全体で MUT_PR_MAX_NOTES 件まで（既定の10は、Actions が1つの段で
  出せる warning の注記の上限。それを超えた分は黙って捨てられる。REST の Checks の文書「Update a check run」）。
- 全部の生き残りと、変わったのにどのテストも通らない関数は、実行の要約（GITHUB_STEP_SUMMARY があればそこ、無ければ標準出力）へ書く。
変異を入れた版の関数は、mutmut を読み込まずに差し込んだ版のファイル（mutants/）を構文木で読む。
"""
import ast
import collections
import difflib
import glob
import json
import os
import sys

from diff_scope import changed_lines

OUT = os.environ["MUT_OUT"]
MAX_NOTES = int(os.environ.get("MUT_PR_MAX_NOTES", "10"))
base = sys.argv[1]
scope = json.load(open(os.path.join(OUT, "scope.json"), encoding="utf-8"))
results = [json.loads(line) for line in open(os.path.join(OUT, "results.jsonl"), encoding="utf-8")] \
    if os.path.exists(os.path.join(OUT, "results.jsonl")) else []
kills: dict[str, set[str]] = collections.defaultdict(set)
for f in glob.glob(os.path.join(OUT, "kills", "*.tsv")):
    for line in open(f, encoding="utf-8"):
        m, t, _w = line.rstrip("\n").split("\t")
        kills[m].add(t)


def fn_of(m):
    return m.partition("__mutmut_")[0]


base_fail: dict[str, set[str]] = collections.defaultdict(set)
for name, tests in kills.items():
    kind, _, fn = name.partition(":")
    if fn and kind in ("BASE1", "BASE2"):
        base_fail[fn] |= tests

survivors, detected = [], 0
for r in results:
    name = r["mutant"]
    if ":" in name:
        continue
    if r["status"] == "survived" or (r["status"] == "killed" and not (kills[name] - base_fail[fn_of(name)])):
        survivors.append(name)
    else:
        detected += 1


def file_of(mutant):
    """mutmut の名前から、backend からのファイルのパス（パッケージなら __init__.py）。"""
    module = fn_of(mutant).rsplit(".", 1)[0]
    path = module.replace(".", "/")
    return f"{path}.py" if os.path.exists(f"{path}.py") else f"{path}/__init__.py"


def find(body, name):
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == name:
                    return child
    return None


trees: dict[str, tuple[str, ast.Module]] = {}


def parsed(path):
    if path not in trees:
        src = open(path, encoding="utf-8").read()
        trees[path] = (src, ast.parse(src))
    return trees[path]


def mutation_line(mutant):
    """書き換えた行の（今の版のファイルの行番号, 元の行, 書き換えた行）。見つからなければ None。"""
    path = file_of(mutant)
    short = mutant.rsplit(".", 1)[1]
    orig_name = fn_of(short) + "__mutmut_orig"
    msrc, mtree = parsed(os.path.join("mutants", path))
    orig, mut = find(mtree.body, orig_name), find(mtree.body, short)
    if orig is None or mut is None:
        return None
    o = (ast.get_source_segment(msrc, orig) or "").split("\n")
    n = (ast.get_source_segment(msrc, mut) or "").replace(short, orig_name, 1).split("\n")
    for tag, i1, _i2, j1, _j2 in difflib.SequenceMatcher(None, o, n).get_opcodes():
        if tag != "equal":
            fn = fn_of(short)
            _src, tree = parsed(path)
            if "ǁ" in fn:  # xǁクラスǁメソッド: そのクラスの中だけを探す（同じ名前のメソッドを別のクラスが持ちうる）
                _x, cls, method = fn.split("ǁ")
                owner = next((c for c in tree.body if isinstance(c, ast.ClassDef) and c.name == cls), None)
                real = find(owner.body, method) if owner else None
            else:
                real = next((f for f in tree.body if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
                             and f.name == fn[2:]), None)
            if real is None:
                return None
            return real.lineno + i1, o[i1].strip() if i1 < len(o) else "", n[j1].strip() if j1 < len(n) else ""
    return None


def escape(s):
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


diff = changed_lines(base)
rows, notes, noted_lines = [], 0, set()
for m in sorted(survivors):
    where = mutation_line(m)
    if where is None:
        rows.append((file_of(m), "", fn_of(m), "（書き換えた行を読めなかった）", False))
        continue
    line, old, new = where
    on_diff = line in diff.get(file_of(m), set())
    rows.append((file_of(m), line, fn_of(m), f"`{old}` → `{new}`", on_diff))
    if on_diff and (file_of(m), line) not in noted_lines and notes < MAX_NOTES:
        noted_lines.add((file_of(m), line))
        notes += 1
        print(f"::warning file=backend/{file_of(m)},line={line},title=テストが気づかない書き換え::"
              + escape(f"この行を「{new}」に書き換えても、この関数を通るテストが全部通った（元: {old}）"))

lines = ["## 変えた関数の変異テスト", "",
         f"変えた関数 {len(scope['funcs'])}・回した変異 {detected + len(survivors)}・気づいた {detected}・生き残り {len(survivors)}"
         f"（変えた行への注記 {notes}、上限 {MAX_NOTES}）", ""]
if scope["untested"]:
    lines += ["### 変わったのに、どのテストも通らない関数", ""] + [f"- `{f}`" for f in scope["untested"]] + [""]
if rows:
    lines += ["### 生き残り", "", "| ファイル | 行 | 関数 | 書き換え | 変えた行 |", "|---|---:|---|---|---|"]
    lines += [f"| `{f}` | {ln} | `{fn.rsplit('.', 1)[1]}` | {d.replace('|', '\\|')} | {'◯' if od else ''} |"
              for f, ln, fn, d, od in rows]
text = "\n".join(lines) + "\n"
summary = os.environ.get("GITHUB_STEP_SUMMARY")
if summary:
    open(summary, "a", encoding="utf-8").write(text)
else:
    sys.stdout.write(text)
