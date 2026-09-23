"""絞り込んだ母集団をループして検査するテストが、母集団が空でないことを確かめていることの検査
（規約は docs/conventions/testing.md パターン6）。

母集団が0件になると、ループの中のアサーションは1回も走らずテストは緑になる。絞り込みの
条件が実データ側の変化で当てはまらなくなっても、テストは落ちずに黙る。

母集団はソースから導く——`backend/tests`配下の全`test_*.py`をASTで読み、テスト関数の中で
次の形をしたループを数える:

- ループ本体に`assert`がある
- 反復対象が絞り込みを経ている: `if`付きの内包表記・`filter(...)`・`.filter(...)`。
  反復対象が名前なら、同じテスト関数（無ければモジュール）でのその名前の代入を見る。
  `.items()`・`.values()`・`.keys()`は件数を変えないので剥がして読む
- 同じテスト関数に、その名前が空でないことの主張が無い
  （`assert xs`・`assert len(xs) > 0`・`>= 1`・`== 3`・`!= 0`）

その場で絞り込む書き方（`for x in [m for m in ms if ...]:`）は主張する相手の名前を持たない
ため、常に違反になる。一度名前へ束ねてから確かめる。
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent.parent
_SIZE_PRESERVING = {"items", "values", "keys"}


def _is_narrowing(node: ast.expr) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            if any(gen.ifs for gen in sub.generators):
                return True
        if isinstance(sub, ast.Call):
            func = sub.func
            if (isinstance(func, ast.Name) and func.id == "filter") or (
                isinstance(func, ast.Attribute) and func.attr == "filter"
            ):
                return True
    return False


def _strip_size_preserving(node: ast.expr) -> ast.expr:
    if (
        isinstance(node, ast.Call)
        and not node.args
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _SIZE_PRESERVING
    ):
        return node.func.value
    return node


def _assigned_value(node: ast.AST, name: str) -> ast.expr | None:
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
        return node.value
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
        return node.value
    return None


def _bindings_in_function(func: ast.FunctionDef | ast.AsyncFunctionDef, name: str, before_line: int) -> list[ast.expr]:
    return [
        value
        for node in ast.walk(func)
        if getattr(node, "lineno", before_line) < before_line
        and (value := _assigned_value(node, name)) is not None
    ]


def _bindings_in_module(tree: ast.Module, name: str) -> list[ast.expr]:
    """モジュール直下の代入だけ（他の関数の中の同名の変数は別物）。"""
    return [value for stmt in tree.body if (value := _assigned_value(stmt, name)) is not None]


def _parameters(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    args = func.args
    return {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}


def _asserts_nonempty(func: ast.AST, name: str) -> bool:
    def is_name(node: ast.expr) -> bool:
        return isinstance(node, ast.Name) and node.id == name

    for node in ast.walk(func):
        if not isinstance(node, ast.Assert):
            continue
        test = node.test
        if is_name(test):
            return True
        if (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Call)
            and isinstance(test.left.func, ast.Name)
            and test.left.func.id == "len"
            and len(test.left.args) == 1
            and is_name(test.left.args[0])
            and len(test.ops) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and isinstance(test.comparators[0].value, int)
        ):
            op, bound = test.ops[0], test.comparators[0].value
            if (
                (isinstance(op, ast.Gt) and bound >= 0)
                or (isinstance(op, ast.GtE) and bound >= 1)
                or (isinstance(op, ast.Eq) and bound >= 1)
                or (isinstance(op, ast.NotEq) and bound == 0)
            ):
                return True
    return False


def _test_functions(tree: ast.Module):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            yield node


def _loops(func: ast.AST):
    """`func`直下のループ（入れ子の関数・クラスの中は見ない）。"""
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(node, (ast.For, ast.AsyncFor)):
            yield node
        stack.extend(ast.iter_child_nodes(node))


def vacuous_loops(root: Path) -> list[str]:
    out: list[str] = []
    for path in sorted(root.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func in _test_functions(tree):
            for loop in _loops(func):
                if not any(isinstance(n, ast.Assert) for stmt in loop.body for n in ast.walk(stmt)):
                    continue
                iterable = _strip_size_preserving(loop.iter)
                where = f"{path.relative_to(root.parent).as_posix()}:{loop.lineno}"
                if _is_narrowing(iterable):
                    out.append(f"{where}: その場で絞り込んだ母集団をループしている（名前へ束ねて空でないことを確かめる）")
                    continue
                if not isinstance(iterable, ast.Name):
                    continue
                name = iterable.id
                if name in _parameters(func):
                    continue  # 母集団はparametrize等の呼び出し側が決める
                bound = _bindings_in_function(func, name, loop.lineno) or _bindings_in_module(tree, name)
                if any(_is_narrowing(value) for value in bound) and not _asserts_nonempty(func, name):
                    out.append(f"{where}: 絞り込んだ母集団 `{name}` が空でも通る（空でないことを同じテストで確かめる）")
    return out


def test_filtered_populations_are_checked_to_be_nonempty() -> None:
    violations = vacuous_loops(TESTS_ROOT)

    assert violations == [], (
        "絞り込んだ母集団をループして検査するのに、空でないことを確かめていないテストがある"
        "（docs/conventions/testing.md パターン6）:\n  " + "\n  ".join(violations)
    )


def _write(tmp_path: Path, source: str) -> Path:
    root = tmp_path / "tests"
    root.mkdir()
    (root / "test_sample.py").write_text(source, encoding="utf-8")
    return root


def test_detects_a_filtered_population_without_a_nonempty_check(tmp_path: Path) -> None:
    """検査が効いていること（わざと空になりうる母集団をループして捕まえる）。"""
    root = _write(
        tmp_path,
        "SPECS = {'a': 1}\n\n\n"
        "def test_every_picked_spec_is_positive():\n"
        "    picked = [v for v in SPECS.values() if v > 5]\n"
        "    for value in picked:\n"
        "        assert value > 0\n\n\n"
        "def test_inline():\n"
        "    for value in filter(None, SPECS.values()):\n"
        "        assert value\n",
    )

    assert vacuous_loops(root) == [
        "tests/test_sample.py:6: 絞り込んだ母集団 `picked` が空でも通る（空でないことを同じテストで確かめる）",
        "tests/test_sample.py:11: その場で絞り込んだ母集団をループしている（名前へ束ねて空でないことを確かめる）",
    ]


def test_accepts_a_population_that_is_checked_to_be_nonempty(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        "SPECS = {'a': 1}\n"
        "PICKED = {k: v for k, v in SPECS.items() if v}\n\n\n"
        "def test_asserts_truthiness():\n"
        "    picked = [v for v in SPECS.values() if v > 0]\n"
        "    assert picked, 'no spec'\n"
        "    for value in picked:\n"
        "        assert value > 0\n\n\n"
        "def test_asserts_length_of_a_module_level_population():\n"
        "    assert len(PICKED) >= 1\n"
        "    for key, value in PICKED.items():\n"
        "        assert value\n\n\n"
        "def _cases():\n"
        "    colors = [c for c in SPECS if c]\n"
        "    return colors\n\n\n"
        "def test_population_given_by_the_caller(colors):\n"
        "    for color in colors:\n"
        "        assert color\n",
    )

    assert vacuous_loops(root) == []
