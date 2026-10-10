"""`orm_base.py: TABLE_MODULES`が、表を宣言するモジュールを全部並べていることの検査。

並べ忘れたモジュールの表は、全表を見る側（スキーマの作成・実DBとの突き合わせ・バックアップ・派生の表の一覧）から
黙って抜ける。`Base.metadata`はimportしたモジュールの表しか持たず、テストの集まりの中ではほかのテストがimportして
いるので、表を動かして確かめるテストでは欠けが出ない。そのためソースを読んで突き合わせる。

並びを実行時にソースから導かないのは、本番のプロセスにソースの走査を抱えさせないため。

母集団はソースから導く（`backend/app`配下の全`.py`）。表を宣言するとみなすのは、クラスの本体で`__tablename__`へ
代入するか、`Table(...)`を呼ぶモジュール。

ここで見ないもの:
- 宣言した表と実DBの差 → `scripts/schema_gap.py`
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.infrastructure.orm_base import TABLE_MODULES

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


def _declares_table(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [getattr(stmt, "target", None)]
                if any(isinstance(t, ast.Name) and t.id == "__tablename__" for t in targets):
                    return True
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name == "Table":
                return True
    return False


def table_modules(root: Path) -> set[str]:
    out = set()
    for path in sorted((root / "app").rglob("*.py")):
        if _declares_table(ast.parse(path.read_text(encoding="utf-8"))):
            out.add(".".join(path.relative_to(root).with_suffix("").parts))
    return out


def test_表を宣言するモジュールを全部並べる() -> None:
    declared = table_modules(BACKEND_ROOT)
    assert declared, "表を宣言するモジュールが1つも見つからない"
    assert set(TABLE_MODULES) == declared, (
        "`orm_base.py: TABLE_MODULES`と、表を宣言するモジュールが違う"
        f"（並べていない: {sorted(declared - set(TABLE_MODULES))}、表を持たない: {sorted(set(TABLE_MODULES) - declared)}）"
    )
