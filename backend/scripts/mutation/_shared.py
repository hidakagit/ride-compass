"""変異テストの台本どうしが共有する読み方（変異の名前・落ちたテストの記録・テスト関数の行）。台本と同じディレクトリから読む。"""
import ast
import collections
import functools
import glob
import os


def fn_of(mutant):
    """mutmut の変異の名前から、変異を作った関数の名前（mangled name）。"""
    return mutant.partition("__mutmut_")[0]


def read_kills(directory, kills=None):
    """runner.py が kills/ に書いた落ちたテストの記録を、変異の名前ごとのテストの集合へ足して返す。"""
    kills = collections.defaultdict(set) if kills is None else kills
    for f in glob.glob(os.path.join(directory, "kills", "*.tsv")):
        for line in open(f, encoding="utf-8"):
            m, t, _when = line.rstrip("\n").split("\t")
            kills[m].add(t)
    return kills


@functools.cache
def _parsed(path):
    src = open(path, encoding="utf-8").read()
    return src.splitlines(), ast.parse(src)


def def_lines(path, name):
    """テスト関数（`クラス::関数` のように :: でつないだ名前）の、デコレータから終わりまでの行。見つからなければ None。
    ファイルを読めなければ OSError。"""
    lines, tree = _parsed(path)
    body = tree.body
    parts = name.split("::")
    for i, p in enumerate(parts):
        node = next((n for n in body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                     and n.name == p), None)
        if node is None:
            return None
        if i == len(parts) - 1:
            start = node.decorator_list[0].lineno if node.decorator_list else node.lineno
            return lines[start - 1:node.end_lineno]
        body = node.body
    return None
