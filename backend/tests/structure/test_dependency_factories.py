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

DI工場が配るのは組み立てた部品だけで、`api/dependencies.py`の関数は`await`しない（呼び出しの結果を配らない）、
`app.infrastructure`から開いた`with ... as`の名前（DBのセッション）をそのままか、`app.infrastructure`のクラスに
包んだだけで配らない（受けた側が、どのセッション工場の上で動くかを見られない）。母集団は`api/dependencies.py`の
全関数の`yield`・`return`。定期ジョブ（`main.py`で`add_job`に渡す関数）は、DI工場の組む`app.infrastructure`の
クラスを組まず、DI工場の口を使う。

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


def _called_infrastructure(tree: ast.Module, within: ast.AST | None = None) -> list[tuple[int, str]]:
    """`app.infrastructure`の名前を呼んだ箇所（行, `モジュール.名前`）。`C(...)`と`mod.C(...)`の両方を拾う。
    `within`を渡すと、`tree`の中のその部分だけを見る。"""
    imported = _infrastructure_names(tree)
    out = []
    for node in ast.walk(within or tree):
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


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def factories_handing_out_calls_or_sessions(root: Path) -> list[str]:
    """`api/dependencies.py`の関数のうち、`await`するもの・開いたセッションを部品に組まずに配るもの。"""
    tree = ast.parse((root / DEPENDENCIES).read_text(encoding="utf-8"))
    imported = _infrastructure_names(tree)
    out: list[str] = []
    for name, function in _functions(tree).items():
        opened = {
            item.optional_vars.id
            for node in ast.walk(function)
            if isinstance(node, (ast.With, ast.AsyncWith))
            for item in node.items
            if isinstance(item.optional_vars, ast.Name)
            and any(isinstance(n, ast.Name) and n.id in imported for n in ast.walk(item.context_expr))
        }
        for node in ast.walk(function):
            if isinstance(node, ast.Await):
                out.append(f"{name}:{node.lineno} await {ast.unparse(node.value)}")
            elif isinstance(node, (ast.Yield, ast.Return)) and node.value is not None:
                value = node.value
                bare = isinstance(value, ast.Name) and value.id in opened
                wrapped = (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id in imported
                    and any(isinstance(n, ast.Name) and n.id in opened for n in ast.walk(value))
                )
                if bare or wrapped:
                    out.append(f"{name}:{node.lineno} 配る {ast.unparse(value)}")
    return out


def test_factories_hand_out_only_assembled_parts() -> None:
    violations = factories_handing_out_calls_or_sessions(APP_ROOT)

    assert violations == [], (
        "DI工場が呼び出しの結果か、開いたセッション（とそれを包んだだけのリポジトリ）を配っている"
        "（services の部品に組んで配る。呼び出しはその部品の口にする）:\n  " + "\n  ".join(violations)
    )


def jobs_assembling_what_the_factories_assemble(root: Path) -> list[str]:
    """`main.py`の定期ジョブが、DI工場の組む`app.infrastructure`のクラスを自分で組んでいる箇所。"""
    classes = _infrastructure_classes(root)
    assembled = {
        name
        for _line, name in _called_infrastructure(ast.parse((root / DEPENDENCIES).read_text(encoding="utf-8")))
        if name in classes
    }
    main = ast.parse((root / "main.py").read_text(encoding="utf-8"))
    functions = _functions(main)
    jobs = {
        node.args[0].id
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and _referenced_name(node.func) == "add_job"
        and node.args
        and isinstance(node.args[0], ast.Name)
    }
    return [
        f"main.py:{line} {job} {name}"
        for job in sorted(jobs & functions.keys())
        for line, name in _called_infrastructure(main, functions[job])
        if name in assembled
    ]


def test_jobs_use_the_factories() -> None:
    violations = jobs_assembling_what_the_factories_assemble(APP_ROOT)

    assert violations == [], (
        "定期ジョブが、DI工場の組む部品を自分で組んでいる（`api/dependencies.py`の口を使う）:\n  "
        + "\n  ".join(violations)
    )


def test_detects_factories_and_jobs_that_bypass_assembly(tmp_path: Path) -> None:
    """検査が効いていること（呼び出しの結果・セッション・包んだだけのリポジトリを配る工場と、工場の部品を組むジョブを
    捕まえ、サービスに組んで配る工場・中継のクライアントを配る工場・開き方を通す）。"""
    root = tmp_path / "app"
    for directory in ("api", "services", "infrastructure"):
        (root / directory).mkdir(parents=True)
    (root / "infrastructure" / "db.py").write_text(
        "class Repository: ...\nclass Client: ...\ndef open_session(): ...\n", encoding="utf-8"
    )
    (root / "api" / "dependencies.py").write_text(
        "from app.infrastructure.db import Client, Repository, open_session\n"
        "from app.services.region import RegionService\n"
        "async def get_area():\n"
        "    async with open_session() as session:\n"
        "        return await RegionService(Repository(session)).area()\n"
        "async def get_session():\n"
        "    async with open_session() as session:\n"
        "        yield session\n"
        "async def get_repository():\n"
        "    async with open_session() as session:\n"
        "        yield Repository(session)\n"
        "async def get_region_service():\n"
        "    async with open_session() as session:\n"
        "        yield RegionService(Repository(session))\n"
        "def get_client():\n"
        "    return Client()\n"
        "def get_opener():\n"
        "    return get_region_service\n",
        encoding="utf-8",
    )
    (root / "main.py").write_text(
        "from app.infrastructure.db import Repository, open_session\n"
        "from app.api.dependencies import get_client\n"
        "async def _job():\n"
        "    async with open_session() as session:\n"
        "        return Repository(session)\n"
        "async def _uses_factory():\n"
        "    return get_client()\n"
        "def _not_a_job():\n"
        "    return Repository(None)\n"
        "scheduler.add_job(_job, trigger='interval')\n"
        "scheduler.add_job(_uses_factory, trigger='interval')\n",
        encoding="utf-8",
    )

    assert factories_handing_out_calls_or_sessions(root) == [
        "get_area:5 await RegionService(Repository(session)).area()",
        "get_session:8 配る session",
        "get_repository:11 配る Repository(session)",
    ]
    assert jobs_assembling_what_the_factories_assemble(root) == ["main.py:5 _job app.infrastructure.db.Repository"]
