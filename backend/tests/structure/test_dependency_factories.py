"""`api/dependencies.py`の公開関数が、注入の口だけであることの検査。

公開関数（`_`で始まらない最上位の`def`）は、`app`配下のどこかで`Depends(<名前>)`の引数になっているか、
`main.py`から参照されるもの（HTTPの経路に無い起動時の組み立て）に限る。ルーターが普通の関数として
呼ぶものは部品を束ねる判断か、DI工場でない共通処理で、`services/`か`api/`の別モジュールの持ち物である
（docs/architecture/directory-layout.md「backend」の`api/`）。

母集団はソースから導く——`app`配下の全`.py`をASTで読み、`Depends(...)`の最初の引数に書かれた名前
（`Depends(x)`・`Depends(mod.x)`）と、`main.py`に現れる名前を集める。
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent.parent / "app"
DEPENDENCIES = Path("api") / "dependencies.py"


def _public_functions(tree: ast.Module) -> list[str]:
    return [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
    ]


def _referenced_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _injected_names(tree: ast.Module) -> set[str]:
    """`Depends(<名前>)`の引数に書かれた名前。"""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _referenced_name(node.func) == "Depends" and node.args:
            name = _referenced_name(node.args[0])
            if name is not None:
                out.add(name)
    return out


def _names_in(tree: ast.Module) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Name, ast.Attribute)):
            out.add(_referenced_name(node) or "")
        elif isinstance(node, ast.alias):
            out.add(node.asname or node.name)
    return out


def dependencies_functions_not_injected(root: Path) -> list[str]:
    """`api/dependencies.py`の公開関数のうち、`Depends`にも`main.py`にも出てこないもの。"""
    trees = {path: ast.parse(path.read_text(encoding="utf-8")) for path in sorted(root.rglob("*.py"))}
    injected = set().union(*(_injected_names(tree) for tree in trees.values()))
    in_main = _names_in(trees[root / "main.py"])
    return [
        name
        for name in _public_functions(trees[root / DEPENDENCIES])
        if name not in injected and name not in in_main
    ]


def test_dependencies_exposes_only_injection_points() -> None:
    violations = dependencies_functions_not_injected(APP_ROOT)

    assert violations == [], (
        "`api/dependencies.py`の公開関数が`Depends`にも`main.py`にも使われていない"
        "（束ねる判断は`services/`へ、DI工場でない共通処理は`api/`の別モジュールへ移す）:\n  "
        + "\n  ".join(violations)
    )


def test_detects_a_function_called_without_depends(tmp_path: Path) -> None:
    """検査が効いていること（わざと1件置いて捕まえる）。"""
    root = tmp_path / "app"
    (root / "api" / "routers").mkdir(parents=True)
    (root / "api" / "dependencies.py").write_text(
        "def get_a(): ...\n"
        "def get_b(): ...\n"
        "async def pick_material(materials): ...\n"
        "def _private(): ...\n",
        encoding="utf-8",
    )
    (root / "api" / "routers" / "sample.py").write_text(
        "from fastapi import Depends\n"
        "from app.api import dependencies\n"
        "from app.api.dependencies import pick_material\n"
        "async def handler(a=Depends(dependencies.get_a)):\n"
        "    return await pick_material([])\n",
        encoding="utf-8",
    )
    (root / "main.py").write_text("from app.api.dependencies import get_b\n", encoding="utf-8")

    assert dependencies_functions_not_injected(root) == ["pick_material"]
