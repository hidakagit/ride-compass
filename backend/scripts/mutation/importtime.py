"""生き残りのうち、読み込みのときに呼ばれうる関数の変異を拾う。backend の下で打つ。

mutmut の「関数ごとに通るテスト」の記録は、テストが走る前（モジュールの読み込み・クラスの本体・既定値・デコレータ）に
呼ばれた関数のテストを漏らす。そうした関数の変異は、記録にあるテストだけを回すと生き残りに見えるので、テスト全体を
当て直す（issue #661 の検算の3）。関数の外で呼ばれる名前を集め、生き残りの関数の名前と照らす。メソッドの get は
辞書の get と名前がぶつかるので外す。
引数: survivors.json（analyze.py が書く） 出力のファイル
"""
import ast
import glob
import json
import sys

called = set()


def visit(node, in_func):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        if not isinstance(node, ast.Lambda):
            for d in node.decorator_list + node.args.defaults + node.args.kw_defaults:
                if d is not None:
                    visit(d, in_func)
        return  # 本体は呼ばれたときに走るので見ない
    if isinstance(node, ast.Call) and not in_func:
        f = node.func
        called.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None))
    for child in ast.iter_child_nodes(node):
        visit(child, in_func)


for path in glob.glob("app/**/*.py", recursive=True):
    visit(ast.parse(open(path, encoding="utf-8").read()), False)
hits = []
for m in json.load(open(sys.argv[1], encoding="utf-8")):
    fn = m.rsplit(".", 1)[1].split("__mutmut_")[0]
    name = fn.split("ǁ")[-1] if "ǁ" in fn else fn[2:]
    if name in called and "ǁget__mutmut_" not in m:
        hits.append(m)
open(sys.argv[2], "w", encoding="utf-8").write("\n".join(hits) + "\n")
print(len(hits), "件")
