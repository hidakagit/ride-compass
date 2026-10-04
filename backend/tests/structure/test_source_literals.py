"""生データのソース名と取込の状態を、SQLの文字列として`source_models.py`の外に書いていないことの検査。

生データの入れ方（`source`の値・runの状態）は`infrastructure/source_models.py`だけが知る。
外で`'accident'`のように書くと、綴りの食い違いはエラーにならず、0件を読む問い合わせとして
静かに通る。

見るのはSQLの文字列の形（単引用符で囲んだ値）だけ。同じ綴りがソース名ではない意味
（タイルの系統名・ファイルの置き場）で使われるのは、Pythonの値としてであってSQLの文字列ではない。
母集団は`source_models.py`の2つの`StrEnum`の値から導く。
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent.parent
SOURCE_MODELS = BACKEND / "app" / "infrastructure" / "source_models.py"
ENUMS = ("Source", "SourceRunStatus")


def enum_values(path: Path, class_names: tuple[str, ...]) -> dict[str, list[str]]:
    """クラスの本体に並ぶ`名前 = "値"`の値。"""
    out: dict[str, list[str]] = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ClassDef) and node.name in class_names:
            out[node.name] = [
                stmt.value.value for stmt in node.body
                if isinstance(stmt, ast.Assign)
                and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)]
    return out


def quoted_literals(root: Path, values: list[str], skip: Path) -> list[str]:
    """`root`配下のPythonの文字列（f-stringの断片を含む）に`'値'`が現れた箇所。"""
    quoted = [f"'{value}'" for value in values]
    hits = []
    for path in sorted(root.rglob("*.py")):
        if path == skip:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for literal in quoted:
                    if literal in node.value:
                        hits.append(f"{path.relative_to(BACKEND).as_posix()}:{node.lineno} {literal}")
    return hits


def test_ソース名と取込の状態をSQLの文字列でsource_modelsの外に書かない() -> None:
    declared = enum_values(SOURCE_MODELS, ENUMS)
    assert sorted(declared) == sorted(ENUMS) and all(declared.values()), (
        f"{SOURCE_MODELS.name}に{ENUMS}の値が見つからない（読み方がクラスの形と合っていない）: {declared}")
    values = [value for values in declared.values() for value in values]

    hits = [hit for package in ("app", "scripts")
            for hit in quoted_literals(BACKEND / package, values, SOURCE_MODELS)]
    assert hits == [], (
        "ソース名か取込の状態をSQLの文字列で書いている。`source_models.py`の副問い合わせか、"
        "`Source`・`SourceRunStatus`の値を使うこと:\n  " + "\n  ".join(hits))
