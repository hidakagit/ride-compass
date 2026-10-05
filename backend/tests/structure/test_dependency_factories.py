"""`api/dependencies.py`の公開関数が注入の口だけであることと、`services/`が部品を自分で組まないことの検査。

公開関数（`_`で始まらない最上位の`def`）は、`app`配下のどこかで`Depends(<名前>)`の引数になっているか、
`main.py`から参照されるもの（HTTPの経路に無い起動時の組み立て）に限る。ルーターが普通の関数として
呼ぶものは部品を束ねる判断か、DI工場でない共通処理で、`services/`か`api/`の別モジュールの持ち物である
（docs/architecture/directory-layout.md「backend」の`api/`）。

母集団はソースから導く——`app`配下の全`.py`をASTで読み、`Depends(...)`の最初の引数に書かれた名前
（`Depends(x)`・`Depends(mod.x)`）と、`main.py`に現れる名前を集める。

`services/`は、組み立ての置き場（`api/dependencies.py`・`main.py`）が組む`app.infrastructure`のクラスを
呼ばない——自分で組むと、DI工場と別のタイムアウト・別の共有状態で動く。母集団は、組み立ての置き場が呼ぶ
`app.infrastructure`のクラス（値の型は組み立ての置き場が組まないので入らない）。

ここで見ないもの:
- 注入した部品の結線 → APIの経路のテスト（例: `tests/test_weather_route.py`）
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


def _infrastructure_names(tree: ast.Module) -> dict[str, str]:
    """`app.infrastructure`から取り込んだ名前 → 取り込み元（`モジュール.名前`）。モジュールごと取り込んだ名前も入る。"""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app.infrastructure"):
            for alias in node.names:
                out[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return out


def _called_infrastructure(tree: ast.Module) -> list[tuple[int, str]]:
    """`app.infrastructure`の名前を呼んだ箇所（行, `モジュール.名前`）。`C(...)`と`mod.C(...)`の両方を拾う。"""
    imported = _infrastructure_names(tree)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in imported:
            out.append((node.lineno, imported[func.id]))
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in imported:
            out.append((node.lineno, f"{imported[func.value.id]}.{func.attr}"))
    return out


def _infrastructure_classes(root: Path) -> set[str]:
    """`app.infrastructure`の各モジュールが定義するクラス（`モジュール.名前`）。"""
    out = set()
    for path in sorted((root / "infrastructure").rglob("*.py")):
        module = "app." + ".".join(path.relative_to(root).with_suffix("").parts)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        out.update(f"{module}.{node.name}" for node in tree.body if isinstance(node, ast.ClassDef))
    return out


def services_assembling_infrastructure(root: Path) -> list[str]:
    """`services/`が、組み立ての置き場の組む`app.infrastructure`のクラスを呼んでいる箇所。"""
    classes = _infrastructure_classes(root)
    assembled = {
        name
        for path in (root / DEPENDENCIES, root / "main.py")
        for _line, name in _called_infrastructure(ast.parse(path.read_text(encoding="utf-8")))
        if name in classes
    }
    return [
        f"{path.relative_to(root).as_posix()}:{line} {name}"
        for path in sorted((root / "services").rglob("*.py"))
        for line, name in _called_infrastructure(ast.parse(path.read_text(encoding="utf-8")))
        if name in assembled
    ]


def test_services_do_not_assemble_what_the_factories_assemble() -> None:
    violations = services_assembling_infrastructure(APP_ROOT)

    assert violations == [], (
        "`services/`が、`api/dependencies.py`・`main.py`の組むクラスを自分で組んでいる（コンストラクタで受け取る）:\n  "
        + "\n  ".join(violations)
    )


def test_detects_a_service_assembling_a_client(tmp_path: Path) -> None:
    """検査が効いていること（わざと置いた2つの呼び方を捕まえ、値の型は見逃す）。"""
    root = tmp_path / "app"
    for directory in ("api", "services", "infrastructure"):
        (root / directory).mkdir(parents=True)
    (root / "infrastructure" / "tile_client.py").write_text(
        "class TileClient: ...\nclass TileValue: ...\n", encoding="utf-8"
    )
    (root / "api" / "dependencies.py").write_text(
        "from app.infrastructure.tile_client import TileClient\n"
        "def get_tile_client():\n"
        "    return TileClient()\n",
        encoding="utf-8",
    )
    (root / "main.py").write_text("", encoding="utf-8")
    (root / "services" / "sample.py").write_text(
        "from app.infrastructure import tile_client\n"
        "from app.infrastructure.tile_client import TileClient as Client, TileValue\n"
        "def build():\n"
        "    return Client(), tile_client.TileClient(), TileValue()\n",
        encoding="utf-8",
    )

    assert services_assembling_infrastructure(root) == [
        "services/sample.py:4 app.infrastructure.tile_client.TileClient",
        "services/sample.py:4 app.infrastructure.tile_client.TileClient",
    ]


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
