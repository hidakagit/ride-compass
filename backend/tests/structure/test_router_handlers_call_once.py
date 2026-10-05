"""ルーターのハンドラが、下の層を1回だけ呼ぶことの検査。

ハンドラ（`api/routers/`の`@<router>.<method>(...)`を付けた関数）が呼ぶ下の層——注入した部品（`Depends`で
受けた引数と、それを開いて`with ... as`で得たもの）のメソッドと、`app.services`の関数——は、合わせて
1つまでにする。下の層の出力を別の下の層へ渡す・呼ぶ順を条件で変えるのは要求の段取りで、
`services/`の持ち物である（docs/architecture/directory-layout.md「backend」の`api/`）。

母集団はソースから導く——`app/api/routers/`の全`.py`のハンドラと、ハンドラが呼ぶ同じモジュールの関数
（受け渡した注入の部品は、渡した先の引数でも注入の部品として読む）。数えるのは呼んだ先の違うものの数で、
同じ口を2回呼んでも1つ。

ここで見ないもの:
- 部品を呼ばず、`infrastructure/`を直接呼ぶ素通し（directory-layout.md が許す）
- 呼んだ結果を応答へ詰める`domain/`の関数
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.structure.source_symbols import Scope, SourceTree

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "api_route"}

Function = ast.FunctionDef | ast.AsyncFunctionDef


def _is_depends(node: ast.expr | None) -> bool:
    return node is not None and any(
        isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "Depends"
        for call in ast.walk(node)
    )


def _injected_parameters(function: Function) -> set[str]:
    """`Depends`で受けた引数（既定値か`Annotated`の注釈）。"""
    arguments = function.args
    positional = arguments.posonlyargs + arguments.args
    defaults: list[ast.expr | None] = [None] * (len(positional) - len(arguments.defaults)) + list(arguments.defaults)
    pairs = list(zip(positional, defaults)) + list(zip(arguments.kwonlyargs, arguments.kw_defaults))
    return {argument.arg for argument, default in pairs if _is_depends(default) or _is_depends(argument.annotation)}


def _root_name(expr: ast.expr) -> str | None:
    while isinstance(expr, (ast.Attribute, ast.Call, ast.Subscript)):
        expr = expr.func if isinstance(expr, ast.Call) else expr.value
    return expr.id if isinstance(expr, ast.Name) else None


def _is_handler(function: Function) -> bool:
    return any(
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr in HTTP_METHODS
        for decorator in function.decorator_list
    )


class _Module:
    def __init__(self, source: SourceTree, module: str):
        tree = source.tree(module)
        assert tree is not None
        self.scope = Scope(source, module, tree)
        self.module = module
        self.functions = {
            node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def _is_services(self, func: ast.expr) -> bool:
        symbol = self.scope.resolve(func)
        return symbol is not None and symbol.module.startswith("app.services")

    def lower_calls(self, function: Function, injected: set[str], seen: set[str]) -> set[str]:
        """`function`（と、そこから呼ぶ同じモジュールの関数）が呼ぶ下の層の口。"""
        injected = set(injected)
        for node in ast.walk(function):
            if isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if isinstance(item.optional_vars, ast.Name) and _root_name(item.context_expr) in injected:
                        injected.add(item.optional_vars.id)
        calls: set[str] = set()
        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            if _root_name(node.func) in injected or self._is_services(node.func):
                calls.add(ast.unparse(node.func))
            elif isinstance(node.func, ast.Name) and node.func.id in self.functions and node.func.id not in seen:
                helper = self.functions[node.func.id]
                parameters = [argument.arg for argument in helper.args.posonlyargs + helper.args.args]
                passed = {
                    name
                    for name, value in [*zip(parameters, node.args), *((kw.arg, kw.value) for kw in node.keywords)]
                    if isinstance(value, ast.Name) and value.id in injected
                }
                calls |= self.lower_calls(helper, passed, seen | {node.func.id})
        return calls


def handlers_calling_twice(backend_root: Path) -> list[str]:
    """下の層を2つ以上呼ぶハンドラ（`<モジュール>.<ハンドラ>: <呼んだ口>`）。"""
    source = SourceTree(backend_root)
    out: list[str] = []
    for path in sorted((backend_root / "app" / "api" / "routers").glob("*.py")):
        module = _Module(source, source.module_of(path))
        for name, function in module.functions.items():
            if not _is_handler(function):
                continue
            calls = module.lower_calls(function, _injected_parameters(function), {name})
            if len(calls) >= 2:
                out.append(f"{module.module}.{name}: {', '.join(sorted(calls))}")
    return sorted(out)


def test_router_handlers_call_the_lower_layer_once() -> None:
    violations = handlers_calling_twice(BACKEND_ROOT)

    assert violations == [], (
        "ハンドラが下の層（注入した部品・services）を2つ以上呼んでいる"
        "（呼ぶ順・受け渡しは services へ移し、ハンドラはそれを1回呼んで応答へ詰める）:\n  "
        + "\n  ".join(violations)
    )


def test_detects_handlers_that_orchestrate(tmp_path: Path) -> None:
    """検査が効いていること（段取りを持つハンドラを形ごとに置いて捕まえ、1回だけ呼ぶものは通す）。"""
    root = tmp_path
    (root / "app" / "api" / "routers").mkdir(parents=True)
    (root / "app" / "services").mkdir(parents=True)
    (root / "app" / "services" / "tiles.py").write_text(
        "async def cached(client, path): ...\nasync def upstream(client, path): ...\n", encoding="utf-8"
    )
    (root / "app" / "api" / "routers" / "sample.py").write_text(
        "from fastapi import APIRouter, Depends\n"
        "from app.services import tiles\n"
        "from app.services.tiles import cached\n"
        "router = APIRouter()\n"
        "async def _all(service):\n"
        "    return await service.list_all()\n"
        "async def _job(open_setup):\n"
        "    async with open_setup() as setup:\n"
        "        return await setup.generator.run()\n"
        "@router.get('/two-methods')\n"
        "async def two_methods(service=Depends(object)):\n"
        "    return await service.get(), await _all(service)\n"
        "@router.get('/two-services')\n"
        "async def two_services(client=Depends(object)):\n"
        "    return await cached(client, 'p') or await tiles.upstream(client, 'p')\n"
        "@router.post('/opened')\n"
        "async def opened(open_setup=Depends(object)):\n"
        "    return await _job(open_setup)\n"
        "@router.get('/once')\n"
        "async def once(service=Depends(object)):\n"
        "    return [await service.list_all(), await service.list_all()]\n",
        encoding="utf-8",
    )

    assert handlers_calling_twice(root) == [
        "app.api.routers.sample.opened: open_setup, setup.generator.run",
        "app.api.routers.sample.two_methods: service.get, service.list_all",
        "app.api.routers.sample.two_services: cached, tiles.upstream",
    ]
