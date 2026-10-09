"""生き残った変異を、書き換えた文の種類で機械的に振り分ける。backend の下で、測った版の差し込んだ版（mutants/）がある所で打つ。

引数: 生き残りの一覧（JSON の配列） 変異ごとのファイル（成果物の rows.json） 出力の JSON
振り分け（書き換えた行を含む、いちばん内側の文で見る。上から順に当てる）:
  例外の文: raise 文の中
  ログ・計測: 文に logger. / log_ / fields[ / mark_failed / warnings.warn / perf_counter / monotonic / logging. を含む
  文字列の中身: 書き換えが文字列の定数の中身だけ（is_string_only）
  それ以外: 上のどれでもない（振る舞いの穴か等価かは、人が読んで決める）
"""
import ast
import collections
import difflib
import json
import sys

import libcst as cst
from mutmut.mutation.diff_apply import read_functions_from_index, read_mutant_function, read_mutants_module, \
    read_original_function

class _BlankStrings(ast.NodeTransformer):
    def visit_Constant(self, node):
        return ast.Constant(value="") if isinstance(node.value, str) else node


def is_string_only(orig, mut):
    """文字列の定数をすべて空にすると同じになる（書き換えが文字列の中身だけ。見出しの名前の大文字・小文字、
    メッセージの文等。振る舞いに効くかは、その文字列を誰が読むかで決まる）。"""
    return ast.dump(_BlankStrings().visit(ast.parse(orig))) == ast.dump(_BlankStrings().visit(ast.parse(mut)))


LOG_MARKS = ("logger.", "log_", "fields[", "mark_failed", "warnings.warn", "perf_counter", "monotonic", "logging.")
surv = json.load(open(sys.argv[1], encoding="utf-8"))
file_of = {r[1]: r[0] for r in json.load(open(sys.argv[2], encoding="utf-8"))}
modules = {}
out = []
for m in surv:
    path = file_of[m]
    pair = read_functions_from_index(m, path)
    if pair is None:
        if path not in modules:
            modules[path] = read_mutants_module(path)
        pair = (read_original_function(modules[path], m), read_mutant_function(modules[path], m))
    orig = cst.Module([pair[0]]).code.strip()
    mut = cst.Module([pair[1]]).code.strip()
    o_lines, m_lines = orig.split("\n"), mut.split("\n")
    changed: set[int] = set()
    for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(None, o_lines, m_lines).get_opcodes():
        if tag != "equal":
            changed.update(range(i1 + 1, max(i2, i1 + 1) + 1))
    tree = ast.parse(orig)
    best: ast.stmt | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            end = node.end_lineno or node.lineno
            if any(node.lineno <= ln <= end for ln in changed):
                # 複合文（if・for・with 等）は、書き換えが頭の行にあるときだけその文とする
                if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try)):
                    head_end = node.body[0].lineno - 1
                    if not any(node.lineno <= ln <= head_end for ln in changed):
                        continue
                if best is None or end - node.lineno <= (best.end_lineno or best.lineno) - best.lineno:
                    best = node
    text = (ast.get_source_segment(orig, best) or "") if best is not None else ""
    if isinstance(best, ast.Raise):
        kind = "例外の文"
    elif any(mark in text for mark in LOG_MARKS):
        kind = "ログ・計測"
    elif is_string_only(orig, mut):
        kind = "文字列の中身"
    else:
        kind = "それ以外"
    diff = [line for line in difflib.unified_diff(o_lines, m_lines, lineterm="", n=0)
            if line[:1] in "+-" and line[:3] not in ("+++", "---")]
    out.append({"mutant": m, "file": path, "kind": kind, "diff": diff})
print(dict(collections.Counter(r["kind"] for r in out)))
json.dump(out, open(sys.argv[3], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
