"""生データのソース名と取込の状態を、SQLの文字列として`source_models.py`の外に書いていないことの検査。

生データの入れ方（`source`の値・runの状態）は`infrastructure/source_models.py`だけが知る。
外で`'accident'`のように書くと、綴りの食い違いはエラーにならず、0件を読む問い合わせとして
静かに通る。

見るのはSQLの文字列の形（単引用符で囲んだ値）だけ。母集団は`source_models.py`の2つの`StrEnum`の値。

ここで見ないもの:
- Pythonの値としての同じ綴り（タイルの系統名・ファイルの置き場など、ソース名ではない意味で使われる）
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.infrastructure import source_models
from app.infrastructure.source_models import Source, SourceRunStatus

BACKEND = Path(__file__).resolve().parent.parent.parent
SOURCE_MODELS = Path(source_models.__file__).resolve()


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
    values = [member.value for enum in (Source, SourceRunStatus) for member in enum]

    hits = [hit for package in ("app", "scripts")
            for hit in quoted_literals(BACKEND / package, values, SOURCE_MODELS)]
    assert hits == [], (
        "ソース名か取込の状態をSQLの文字列で書いている。`source_models.py`の副問い合わせか、"
        "`Source`・`SourceRunStatus`の値を使うこと:\n  " + "\n  ".join(hits))
