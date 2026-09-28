"""autouse のフィクスチャが、テストの寄りかかれる値を配っていないことの検査。

autouse で配ってよいのは何も与えないものだけ（docs/conventions/testing.md「テストの足場で、本来のNGを覆わない」）。
値・データ・動く代役を配ると、それに依るテストが依ると言わないまま通り、前提の無い状態で走るテストが1件も
無くなる。

母集団はソースから導く——`backend/tests`配下の全`.py`（この検査のディレクトリを除く）の autouse の
フィクスチャと、そこから呼ぶ`tests`の補助関数（`with`の文脈管理も含む）を読み、共有の状態へ書く値を1つずつ
判定する。書く形は`setattr`・`setitem`・属性や添字への代入・`update`等の書き足し。

何も与えない値:
- 空の値（`None`・`0`・`""`・空の入れ物）と、何もしない関数（本体が`return None`・`pass`だけ）
- 一時ディレクトリ（pytest の`tmp_path`・`tmp_path_factory`から作るもの）
- 元へ戻す値（同じ書き先から読んでおいた値）
- 同じ種類の作り直し（書き先の宣言と同じ呼び出しを、定数だけの引数で作る）
- 時計（書き先が`time`・`datetime`のモジュール）
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from tests.structure.source_symbols import Scope, SourceTree, Symbol

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPORARY = {"tmp_path", "tmp_path_factory"}
CLOCKS = {"time", "datetime"}
GROWING = {"update", "setdefault", "append", "extend", "add", "insert"}


@dataclass
class Frame:
    """読んでいる関数1つ。`arguments`は引数名→（呼び出し元が渡した式, 呼び出し元のFrame）。"""

    scope: Scope
    function: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda
    arguments: dict[str, tuple[ast.expr, Frame]] = field(default_factory=dict)

    def locals(self) -> dict[str, list[ast.AST]]:
        out: dict[str, list[ast.AST]] = {}
        for node in _own_nodes(self.function):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and node.value is not None:
                        out.setdefault(target.id, []).append(node.value)
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
                for name in ast.walk(node.target):
                    if isinstance(name, ast.Name):
                        out.setdefault(name.id, []).append(node)
            elif isinstance(node, ast.withitem) and node.optional_vars is not None:
                for name in ast.walk(node.optional_vars):
                    if isinstance(name, ast.Name):
                        out.setdefault(name.id, []).append(node.context_expr)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node is not self.function:
                out.setdefault(node.name, []).append(node)
        return out

    def parameters(self) -> set[str]:
        args = self.function.args
        return {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs} | {
            a.arg for a in (args.vararg, args.kwarg) if a is not None
        }


def _own_nodes(function: ast.AST) -> Iterator[ast.AST]:
    """関数の本体のうち、その関数が動くときに動く部分（入れ子の関数・lambdaの本体は除く）。"""
    stack = list(ast.iter_child_nodes(function))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            stack.extend(ast.iter_child_nodes(node))


def _is_autouse(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(decorator, ast.Call)
        and any(k.arg == "autouse" and isinstance(k.value, ast.Constant) and k.value.value is True
                for k in decorator.keywords)
        for decorator in function.decorator_list
    )


def _root(expr: ast.expr) -> ast.expr:
    while True:
        if isinstance(expr, (ast.Attribute, ast.Subscript)):
            expr = expr.value
        elif isinstance(expr, ast.Call):
            expr = expr.func
        elif isinstance(expr, ast.BinOp):
            expr = expr.left
        else:
            return expr


def _is_noop(function: ast.AST) -> bool:
    if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    for stmt in function.body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue
        if isinstance(stmt, ast.Return) and (stmt.value is None or _is_empty_constant(stmt.value)):
            continue
        return False
    return True


def _is_empty_constant(expr: ast.expr) -> bool:
    if isinstance(expr, ast.Constant):
        value = expr.value
        return value is None or value is False or value == "" or (type(value) in (int, float) and value == 0)
    if isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
        return not expr.elts
    if isinstance(expr, ast.Dict):
        return not expr.keys
    return False


def _constants_only(call: ast.Call) -> bool:
    return all(isinstance(a, ast.Constant) for a in call.args) and all(
        isinstance(k.value, ast.Constant) for k in call.keywords
    )


class Reader:
    def __init__(self, source: SourceTree):
        self.source = source

    def _is_temporary(self, expr: ast.expr, frame: Frame) -> bool:
        root = _root(expr)
        if isinstance(root, ast.Lambda):
            return self._is_temporary(root.body, frame)
        if not isinstance(root, ast.Name):
            return False
        if root.id in frame.arguments:
            passed, caller = frame.arguments[root.id]
            return self._is_temporary(passed, caller)
        return root.id in TEMPORARY and root.id in frame.parameters()

    def _function(self, expr: ast.expr, frame: Frame) -> tuple[ast.AST, Frame] | None:
        """式が指す関数の定義（このファイル・`tests`の補助関数）。"""
        if isinstance(expr, ast.Name):
            if expr.id in frame.arguments:
                passed, caller = frame.arguments[expr.id]
                return self._function(passed, caller)
            local = frame.locals().get(expr.id, [])
            if len(local) == 1 and isinstance(local[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
                return local[0], frame
        symbol = frame.scope.resolve(expr)
        if symbol is not None and symbol.kind == "function" and symbol.module.split(".")[0] == "tests":
            tree = self.source.tree(symbol.module)
            assert tree is not None and symbol.node is not None
            return symbol.node, Frame(Scope(self.source, symbol.module, tree), symbol.node)
        return None

    def gives_nothing(self, value: ast.expr, frame: Frame, target: str, replaced: Symbol | None) -> bool:
        if replaced is not None and replaced.kind == "module" and replaced.module in CLOCKS:
            return True
        if _is_empty_constant(value) or self._is_temporary(value, frame):
            return True
        if isinstance(value, ast.Lambda):
            return _is_empty_constant(value.body) or self._is_temporary(value.body, frame)
        if isinstance(value, ast.Name):
            if value.id in frame.arguments:
                passed, caller = frame.arguments[value.id]
                return self.gives_nothing(passed, caller, target, replaced)
            assigned = frame.locals().get(value.id, [])
            if len(assigned) == 1 and isinstance(assigned[0], ast.expr):
                if any(ast.unparse(n) == target for n in ast.walk(assigned[0]) if isinstance(n, ast.expr)):
                    return True
                return self.gives_nothing(assigned[0], frame, target, replaced)
        if isinstance(value, ast.Call):
            called = frame.scope.resolve(value.func)
            if called is not None and (called.module, getattr(called.node, "name", "")) == ("tests.bound_fake", "bound"):
                return len(value.args) == 2 and self.gives_nothing(value.args[1], frame, target, None)
            declared = replaced.node if replaced is not None and replaced.kind == "data" else None
            if isinstance(declared, (ast.Assign, ast.AnnAssign)) and isinstance(declared.value, ast.Call):
                if ast.unparse(declared.value.func) == ast.unparse(value.func) and _constants_only(value):
                    return True
        found = self._function(value, frame) if isinstance(value, (ast.Name, ast.Attribute)) else None
        return found is not None and _is_noop(found[0])

    def _writes(self, frame: Frame) -> Iterator[tuple[ast.AST, ast.expr, str, Symbol | None]]:
        """（書いた場所, 書いた値, 書き先の式, 書き先が今指しているもの）。"""
        local_names = set(frame.locals()) - frame.parameters()
        for node in _own_nodes(frame.function):
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name)):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
                args = node.args
                if name == "setattr" and len(args) == 3 and isinstance(args[1], ast.Constant):
                    owner = frame.scope.resolve(args[0])
                    replaced = self.source.attribute(owner, args[1].value) if owner else None
                    yield node, args[2], f"{ast.unparse(args[0])}.{args[1].value}", replaced
                elif name == "setattr" and len(args) == 3:
                    yield node, args[2], ast.unparse(args[0]), None
                elif name == "setattr" and len(args) == 2 and isinstance(args[0], ast.Constant):
                    split = self.source.dotted(str(args[0].value))
                    yield node, args[1], str(args[0].value), (self.source.attribute(*split) if split else None)
                elif name == "setitem" and len(args) == 3:
                    yield node, args[2], ast.unparse(args[0]), None
                elif name in GROWING and isinstance(node.func, ast.Attribute):
                    root = _root(node.func.value)
                    if not (isinstance(root, ast.Name) and root.id in local_names):
                        for arg in args:
                            yield node, arg, ast.unparse(node.func.value), None
            elif isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if not isinstance(target, (ast.Attribute, ast.Subscript)):
                        continue
                    root = _root(target)
                    if isinstance(root, ast.Name) and root.id in local_names:
                        continue
                    replaced = None
                    if isinstance(target, ast.Attribute):
                        owner = frame.scope.resolve(target.value)
                        replaced = self.source.attribute(owner, target.attr) if owner else None
                    yield node, node.value, ast.unparse(target.value if isinstance(target, ast.Subscript) else target), replaced

    def violations(self, frame: Frame, seen: set[int]) -> Iterator[tuple[ast.AST, str, Frame]]:
        if id(frame.function) in seen:
            return
        seen = seen | {id(frame.function)}
        for node, value, target, replaced in self._writes(frame):
            if not self.gives_nothing(value, frame, target, replaced):
                yield node, f"{target} ← {ast.unparse(value)}", frame
        for node in _own_nodes(frame.function):
            if not isinstance(node, ast.Call):
                continue
            found = self._function(node.func, frame)
            if found is None or not isinstance(found[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            helper, helper_frame = found
            parameters = [a.arg for a in helper.args.posonlyargs + helper.args.args]
            arguments = dict(zip(parameters, ((a, frame) for a in node.args)))
            arguments.update({k.arg: (k.value, frame) for k in node.keywords if k.arg})
            yield from self.violations(Frame(helper_frame.scope, helper, arguments), seen)


def autouse_violations(root: Path) -> list[str]:
    """`root`（`backend`）の`tests`で、autouse のフィクスチャが何かを与えている箇所。"""
    source = SourceTree(root)
    reader = Reader(source)
    out: list[str] = []
    for path in sorted((root / "tests").rglob("*.py")):
        if "structure" in path.relative_to(root / "tests").parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        scope = Scope(source, source.module_of(path), tree)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_autouse(node):
                for where, text, frame in reader.violations(Frame(scope, node), set()):
                    written = f"{frame.scope.module}:{getattr(where, 'lineno', '?')}"
                    out.append(f"{path.relative_to(root).as_posix()}: {node.name}（{written}: {text}）")
    return sorted(out)


def test_autouse_fixtures_give_nothing() -> None:
    violations = autouse_violations(BACKEND_ROOT)

    assert violations == [], (
        "autouse のフィクスチャが値・データ・代役を配っている。autouse を外し、要るテストが引数で取ること"
        "（docs/conventions/testing.md「テストの足場で、本来のNGを覆わない」）:\n  " + "\n  ".join(violations)
    )


def _backend(tmp_path: Path, test_source: str) -> Path:
    for relative, text in {
        "app/__init__.py": "",
        "app/store.py": "import time\nfrom cachetools import TTLCache\n\nCACHE = TTLCache(maxsize=1, ttl=60)\ncurrent = None\n",
        "tests/__init__.py": "",
        "tests/world.py": (
            "from contextlib import contextmanager\nfrom app import store\n\n\n"
            "@contextmanager\ndef installed(value):\n    original = store.current\n"
            "    store.current = value\n    yield\n    store.current = original\n"
        ),
        "tests/test_sample.py": test_source,
    }.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(text, encoding="utf-8")
    return tmp_path


def test_detects_data_given_directly_and_through_a_helper(tmp_path: Path) -> None:
    """検査が効いていること（データを直接書く形と、補助関数へ渡して書かせる形を1件ずつ置く）。"""
    root = _backend(
        tmp_path,
        "import pytest\nfrom app import store\nfrom tests.world import installed\n\nNETWORK = object()\n\n\n"
        "@pytest.fixture(autouse=True)\ndef direct(monkeypatch):\n    monkeypatch.setattr(store, 'current', NETWORK)\n\n\n"
        "@pytest.fixture(autouse=True)\ndef through_helper():\n    with installed({'a': 1}):\n        yield\n",
    )

    assert autouse_violations(root) == [
        "tests/test_sample.py: direct（tests.test_sample:10: store.current ← NETWORK）",
        "tests/test_sample.py: through_helper（tests.world:8: store.current ← value）",
    ]


def test_resets_temporary_places_restores_and_clocks_give_nothing(tmp_path: Path) -> None:
    """空・一時ディレクトリ・同じ種類の作り直し・元へ戻す・時計・何もしない関数は、何も与えない。"""
    root = _backend(
        tmp_path,
        "import pytest\nfrom cachetools import TTLCache\nfrom app import store\nfrom tests.world import installed\n\n\n"
        "async def _noop():\n    return None\n\n\n"
        "@pytest.fixture(autouse=True)\ndef reset(monkeypatch, tmp_path):\n"
        "    monkeypatch.setattr(store, 'current', None)\n"
        "    monkeypatch.setattr(store, 'ROOT', tmp_path / 'x')\n"
        "    monkeypatch.setattr(store, 'CACHE', TTLCache(maxsize=1, ttl=60))\n"
        "    monkeypatch.setattr(store, 'time', object())\n"
        "    monkeypatch.setattr(store, 'refresh', _noop)\n"
        "    with installed(None):\n        yield\n",
    )

    assert autouse_violations(root) == []
