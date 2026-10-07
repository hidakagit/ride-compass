"""ルーターのハンドラが要求の段取りを持たないことの検査。

段取りは`services/`の持ち物である（docs/architecture/directory-layout.md「backend」の`api/`）。ハンドラ
（`api/routers/`の`@<router>.<method>(...)`を付けた関数）と、ルーターのモジュール直下の補助関数が持ってはいけない形:

- 流れ: `domain/`の関数・下の層（注入した部品——`Depends`で受けた引数と、それを開いて`with ... as`で得たもの——の
  メソッドと、`app.services`の関数）の戻り値が、下の層の呼び出しの引数へ流れる。下の層の戻り値で、下の層を呼ぶかを
  `if`で分ける形も同じ。戻り値は代入した名前を通して辿る。下の層を独立に何度呼んでも、流れが無ければ違反にしない。
- 選り分け: `if`の付いた内包表記・`sorted`・`filter`。宣言や結果から選ぶ・並べるのは`domain/`の判断である。

母集団はソースから導く——`app/api/routers/`の全`.py`のハンドラと、ハンドラが呼ぶ同じモジュールの関数（受け渡した
注入の部品・流れは、渡した先の引数でも同じに読む）。同じモジュールの関数の戻り値は、中で`domain/`の関数か下の層を
呼んでいれば流れの元に数える。

ここで見ないもの:
- 部品を呼ばず、`infrastructure/`を直接呼ぶ素通し（directory-layout.md が許す）
- 要求モデル（クラス）の validator の中の導出——要求の形の検査で、ハンドラの段取りではない
- `domain/`のクラスで要求を組む（`Coordinates(...)`）——要求を`domain/`の型へ詰める射影
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.structure.source_symbols import Scope, SourceTree

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "api_route"}
SELECTING_CALLS = {"sorted", "filter"}

Function = ast.FunctionDef | ast.AsyncFunctionDef


def _is_depends(node: ast.expr | None) -> bool:
    return node is not None and any(
        isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "Depends"
        for call in ast.walk(node)
    )


def _parameters(function: Function) -> list[ast.arg]:
    arguments = function.args
    return arguments.posonlyargs + arguments.args + arguments.kwonlyargs


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


def _assignments(function: Function) -> list[tuple[list[ast.expr], ast.expr]]:
    """代入の先と値の組（`=`・`+=`・`:=`・`for`・内包表記の`for`）。"""
    out: list[tuple[list[ast.expr], ast.expr]] = []
    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            out.append((node.targets, node.value))
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)) and node.value is not None:
            out.append(([node.target], node.value))
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            out.append(([node.target], node.iter))
    return out


def _target_names(targets: list[ast.expr]) -> set[str]:
    return {name.id for target in targets for name in ast.walk(target) if isinstance(name, ast.Name)}


class _Module:
    def __init__(self, source: SourceTree, module: str):
        tree = source.tree(module)
        assert tree is not None
        self.scope = Scope(source, module, tree)
        self.module = module
        self.functions = {
            node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

    def _resolves_into(self, func: ast.expr, package: str, kind: str | None = None) -> bool:
        symbol = self.scope.resolve(func)
        return symbol is not None and symbol.module.startswith(package) and kind in (None, symbol.kind)

    def _is_lower(self, call: ast.Call, injected: set[str]) -> bool:
        return _root_name(call.func) in injected or self._resolves_into(call.func, "app.services")

    def _helper(self, call: ast.Call) -> Function | None:
        return self.functions.get(call.func.id) if isinstance(call.func, ast.Name) else None

    def _passed_injected(self, call: ast.Call, helper: Function, injected: set[str]) -> set[str]:
        """`call`が`helper`へ渡した注入の部品を受ける引数の名前。"""
        names = [argument.arg for argument in _parameters(helper)]
        passed = [*zip(names, call.args), *((keyword.arg, keyword.value) for keyword in call.keywords)]
        return {name for name, value in passed if name and isinstance(value, ast.Name) and value.id in injected}

    def _is_source(self, call: ast.Call, injected: set[str], seen: frozenset[str]) -> bool:
        """戻り値が流れの元になる呼び出し（同じモジュールの関数は、中で`domain/`の関数か下の層を呼ぶもの）。"""
        if self._is_lower(call, injected) or self._resolves_into(call.func, "app.domain", "function"):
            return True
        helper = self._helper(call)
        if helper is None or helper.name in seen:
            return False
        inner = self._passed_injected(call, helper, injected)
        return any(
            isinstance(node, ast.Call) and self._is_source(node, inner, seen | {helper.name})
            for node in ast.walk(helper)
        )

    def _carries(self, expr: ast.expr, tainted: set[str], injected: set[str], seen: frozenset[str]) -> bool:
        return any(
            (isinstance(node, ast.Name) and node.id in tainted)
            or (isinstance(node, ast.Call) and self._is_source(node, injected, seen))
            for node in ast.walk(expr)
        )

    def violations(
        self, function: Function, injected: set[str], tainted: set[str], seen: frozenset[str]
    ) -> list[str]:
        """`function`（と、そこから呼ぶ同じモジュールの関数）の流れ・選り分け。"""
        injected = set(injected)
        for node in ast.walk(function):
            if isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if isinstance(item.optional_vars, ast.Name) and _root_name(item.context_expr) in injected:
                        injected.add(item.optional_vars.id)
        tainted = set(tainted)
        assignments = _assignments(function)
        while True:
            grown = tainted | {
                name
                for targets, value in assignments
                if self._carries(value, tainted, injected, seen)
                for name in _target_names(targets)
            }
            if grown == tainted:
                break
            tainted = grown

        out: list[str] = []
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and self._is_lower(node, injected):
                for value in [*node.args, *(keyword.value for keyword in node.keywords)]:
                    if self._carries(value, tainted, injected, seen):
                        out.append(f"{function.name}:{node.lineno} 流れ {ast.unparse(value)} → {ast.unparse(node.func)}")
            elif isinstance(node, (ast.If, ast.IfExp)) and self._carries(node.test, tainted, injected, seen):
                branches = [node.body, node.orelse] if isinstance(node, ast.IfExp) else [*node.body, *node.orelse]
                if any(
                    isinstance(call, ast.Call) and self._is_lower(call, injected)
                    for branch in branches
                    for call in ast.walk(branch)
                ):
                    out.append(f"{function.name}:{node.lineno} 分岐 {ast.unparse(node.test)}")
            elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)) and any(
                generator.ifs for generator in node.generators
            ):
                out.append(f"{function.name}:{node.lineno} 選り分け {ast.unparse(node)}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in SELECTING_CALLS:
                out.append(f"{function.name}:{node.lineno} 選り分け {ast.unparse(node)}")
            if isinstance(node, ast.Call) and (helper := self._helper(node)) is not None and helper.name not in seen:
                names = [argument.arg for argument in _parameters(helper)]
                passed = [*zip(names, node.args), *((keyword.arg, keyword.value) for keyword in node.keywords)]
                out += self.violations(
                    helper,
                    self._passed_injected(node, helper, injected),
                    {name for name, value in passed if name and self._carries(value, tainted, injected, seen)},
                    seen | {helper.name},
                )
        return out


def handlers_orchestrating(backend_root: Path) -> list[str]:
    """段取りを持つハンドラ（`<モジュール>.<ハンドラ> <関数>:<行> <形> <式>`）。"""
    source = SourceTree(backend_root)
    out: set[str] = set()
    for path in sorted((backend_root / "app" / "api" / "routers").glob("*.py")):
        module = _Module(source, source.module_of(path))
        for name, function in module.functions.items():
            if _is_handler(function):
                out |= {
                    f"{module.module}.{name} {violation}"
                    for violation in module.violations(function, _injected_parameters(function), set(), frozenset({name}))
                }
    return sorted(out)


def test_router_handlers_hold_no_orchestration() -> None:
    violations = handlers_orchestrating(BACKEND_ROOT)

    assert violations == [], (
        "ハンドラが段取りを持っている（下の層・domain の関数の戻り値を下の層へ渡す・それで呼ぶかを分ける・"
        "選り分ける。services へ移し、ハンドラはその口を呼んで応答へ詰める）:\n  " + "\n  ".join(violations)
    )


def test_detects_handlers_that_orchestrate(tmp_path: Path) -> None:
    """検査が効いていること（段取りを形ごとに置いて捕まえ、独立に呼ぶだけのものと要求を型へ詰めるものは通す）。"""
    root = tmp_path
    (root / "app" / "api" / "routers").mkdir(parents=True)
    (root / "app" / "services").mkdir(parents=True)
    (root / "app" / "domain").mkdir(parents=True)
    (root / "app" / "services" / "tiles.py").write_text(
        "async def cached(client, path): ...\nasync def upstream(client, path): ...\n", encoding="utf-8"
    )
    (root / "app" / "domain" / "grid.py").write_text(
        "class Point: ...\nDECLARED = []\ndef points(area): ...\n", encoding="utf-8"
    )
    (root / "app" / "api" / "routers" / "sample.py").write_text(
        "from fastapi import APIRouter, Depends\n"
        "from app.domain import grid\n"
        "from app.domain.grid import DECLARED, Point, points\n"
        "from app.services import tiles\n"
        "from app.services.tiles import cached\n"
        "router = APIRouter()\n"
        "def _points(area):\n"
        "    return points(area)\n"
        "async def _read(service, at):\n"
        "    return await service.read(at)\n"
        "@router.get('/domain-into-lower')\n"
        "async def domain_into_lower(service=Depends(object)):\n"
        "    at = grid.points(1)\n"
        "    return await service.read(at)\n"
        "@router.get('/lower-into-lower')\n"
        "async def lower_into_lower(client=Depends(object)):\n"
        "    return await tiles.upstream(client, await cached(client, 'p'))\n"
        "@router.get('/through-helpers')\n"
        "async def through_helpers(service=Depends(object)):\n"
        "    return await _read(service, _points(2))\n"
        "@router.get('/branch')\n"
        "async def branch(service=Depends(object), other=Depends(object)):\n"
        "    if await service.get() is None:\n"
        "        return await other.get()\n"
        "@router.get('/select')\n"
        "async def select():\n"
        "    return [d for d in DECLARED if d], sorted(DECLARED)\n"
        "async def _get(service):\n"
        "    return await service.get()\n"
        "@router.get('/helper-output')\n"
        "async def helper_output(service=Depends(object), other=Depends(object)):\n"
        "    return await other.read(await _get(service))\n"
        "@router.get('/independent')\n"
        "async def independent(service=Depends(object), client=Depends(object)):\n"
        "    return await service.get(), await cached(client, 'p'), await service.read(Point())\n",
        encoding="utf-8",
    )

    assert handlers_orchestrating(root) == [
        "app.api.routers.sample.branch branch:23 分岐 await service.get() is None",
        "app.api.routers.sample.domain_into_lower domain_into_lower:14 流れ at → service.read",
        "app.api.routers.sample.helper_output helper_output:32 流れ await _get(service) → other.read",
        "app.api.routers.sample.lower_into_lower lower_into_lower:17 流れ await cached(client, 'p') → tiles.upstream",
        "app.api.routers.sample.select select:27 選り分け [d for d in DECLARED if d]",
        "app.api.routers.sample.select select:27 選り分け sorted(DECLARED)",
        "app.api.routers.sample.through_helpers _read:10 流れ at → service.read",
    ]
