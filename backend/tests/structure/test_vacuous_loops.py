"""要素ごとに検査するテストが、空の母集団で何も確かめずに通らないことの検査
（規約は docs/conventions/testing.md パターン6）。

母集団が0件になると、要素ごとのアサーションは1回も走らずテストは緑になる。絞り込みの
条件が実データ側の変化で当てはまらなくなっても、テストは落ちずに黙る。

性質は「絞り込んだ後の要素にしか届かないアサーション」で、絞り込みの書き方によらない。
母集団はソースから導く——`backend/tests`配下の全`test_*.py`をASTで読み、テスト関数の中の
要素ごとの検査を数える:

- 本体に`assert`がある`for`ループと、`assert all(...)`・`assert not any(...)`
  （空なら真になる量化）
- 絞り込みがその場にある: 反復対象が`if`付きの内包表記・`filter(...)`・`.filter(...)`を経ている、
  またはループ本体の条件（`if`の片側だけにアサーションがある・`continue`等で抜ける）を
  通らないとアサーションへ届かない。絞り込んだ後の母集団に名前が無く、空でないことを主張
  できないため常に違反になる。一度名前へ束ねてから確かめる
- 絞り込みが名前の代入にある: 反復対象が名前なら、同じテスト関数（無ければモジュール）での
  その名前の代入を見る。`.items()`・`.values()`・`.keys()`は件数を変えないので剥がして読む。
  同じテスト関数に、その名前が空でないことの主張
  （`assert xs`・`assert len(xs) > 0`・`>= 1`・`== 3`・`!= 0`）が無ければ違反
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent.parent
_SIZE_PRESERVING = {"items", "values", "keys"}
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)

_ASSERTS, _EXITS, _FALLS = "asserts", "exits", "falls"


def _is_narrowing(node: ast.expr) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, _COMPREHENSIONS):
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


def _flow(stmts: list[ast.stmt]) -> str:
    """1つの要素が文の並びを通ったとき、アサーションへ必ず届くか。

    入れ子のループは、その中身を自分の母集団として別に数えるため、アサーションを含めば届くとみなす。
    """
    for stmt in stmts:
        if isinstance(stmt, ast.Assert):
            return _ASSERTS
        if isinstance(stmt, (ast.Continue, ast.Break, ast.Return)):
            return _EXITS
        if isinstance(stmt, ast.If):
            branches = (_flow(stmt.body), _flow(stmt.orelse))
            if _EXITS in branches:
                return _EXITS
            if all(branch == _ASSERTS for branch in branches):
                return _ASSERTS
            continue
        if isinstance(stmt, (ast.With, ast.AsyncWith, ast.Try)):
            inner = _flow(stmt.body)
            if inner != _FALLS:
                return inner
            continue
        if any(isinstance(node, ast.Assert) for node in ast.walk(stmt)):
            return _ASSERTS
    return _FALLS


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


def _own_nodes(func: ast.AST):
    """`func`直下のノード（入れ子の関数・クラスの中は見ない）。"""
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _quantified(test: ast.expr) -> ast.expr | None:
    """空なら真になる量化（`all(...)`・`not any(...)`）の引数。"""
    call = test.operand if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) else test
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and len(call.args) == 1):
        return None
    if call.func.id == ("any" if call is not test else "all"):
        return call.args[0]
    return None


def _population(node: ast.expr) -> tuple[bool, ast.expr]:
    """(その場で絞り込んでいるか, 母集団の式)。内包表記は述語でなく反復対象だけを読む。"""
    if isinstance(node, _COMPREHENSIONS):
        narrowed = any(gen.ifs or _is_narrowing(gen.iter) for gen in node.generators)
        return narrowed, _strip_size_preserving(node.generators[0].iter)
    iterable = _strip_size_preserving(node)
    return _is_narrowing(iterable), iterable


def vacuous_loops(root: Path) -> list[str]:
    out: list[str] = []
    for path in sorted(root.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func in _test_functions(tree):
            for node in _own_nodes(func):
                if isinstance(node, (ast.For, ast.AsyncFor)):
                    if not any(isinstance(n, ast.Assert) for stmt in node.body for n in ast.walk(stmt)):
                        continue
                    inline, population = _population(node.iter)
                    guarded = _flow(node.body) != _ASSERTS
                elif isinstance(node, ast.Assert) and (argument := _quantified(node.test)) is not None:
                    inline, population = _population(argument)
                    guarded = False
                else:
                    continue
                where = f"{path.relative_to(root.parent).as_posix()}:{node.lineno}"
                if inline:
                    out.append(f"{where}: その場で絞り込んだ母集団を検査している（名前へ束ねて空でないことを確かめる）")
                    continue
                if guarded:
                    out.append(
                        f"{where}: ループの中の条件を通った要素にしか届かないアサーションがある"
                        "（絞り込みを名前へ束ねて空でないことを確かめる）"
                    )
                    continue
                if not isinstance(population, ast.Name):
                    continue
                name = population.id
                if name in _parameters(func):
                    continue  # 母集団はparametrize等の呼び出し側が決める
                bound = _bindings_in_function(func, name, node.lineno) or _bindings_in_module(tree, name)
                if any(_is_narrowing(value) for value in bound) and not _asserts_nonempty(func, name):
                    out.append(f"{where}: 絞り込んだ母集団 `{name}` が空でも通る（空でないことを同じテストで確かめる）")
    return sorted(out, key=lambda line: (line.split(":")[0], int(line.split(":")[1])))


def test_filtered_populations_are_checked_to_be_nonempty() -> None:
    violations = vacuous_loops(TESTS_ROOT)

    assert violations == [], (
        "絞り込んだ母集団を要素ごとに検査するのに、空でないことを確かめていないテストがある"
        "（docs/conventions/testing.md パターン6）:\n  " + "\n  ".join(violations)
    )


def _write(tmp_path: Path, source: str) -> Path:
    root = tmp_path / "tests"
    root.mkdir()
    (root / "test_sample.py").write_text(source, encoding="utf-8")
    return root


def test_detects_a_filtered_population_without_a_nonempty_check(tmp_path: Path) -> None:
    """検査が効いていること（絞り込みの書き方ごとに、空になりうる母集団を捕まえる）。"""
    root = _write(
        tmp_path,
        "SPECS = {'a': 1}\n\n\n"
        "def test_every_picked_spec_is_positive():\n"
        "    picked = [v for v in SPECS.values() if v > 5]\n"
        "    for value in picked:\n"
        "        assert value > 0\n\n\n"
        "def test_inline():\n"
        "    for value in filter(None, SPECS.values()):\n"
        "        assert value\n\n\n"
        "def test_guarded_by_if():\n"
        "    for key, value in SPECS.items():\n"
        "        if value > 5:\n"
        "            assert key\n\n\n"
        "def test_guarded_by_continue():\n"
        "    for value in SPECS.values():\n"
        "        if value <= 5:\n"
        "            continue\n"
        "        assert value\n\n\n"
        "def test_quantified_inline():\n"
        "    assert all(v > 0 for v in SPECS.values() if v > 5)\n"
        "    assert not any(v < 0 for v in SPECS.values() if v > 5)\n\n\n"
        "def test_quantified_named():\n"
        "    picked = [v for v in SPECS.values() if v > 5]\n"
        "    assert all(v > 0 for v in picked)\n",
    )

    assert vacuous_loops(root) == [
        "tests/test_sample.py:6: 絞り込んだ母集団 `picked` が空でも通る（空でないことを同じテストで確かめる）",
        "tests/test_sample.py:11: その場で絞り込んだ母集団を検査している（名前へ束ねて空でないことを確かめる）",
        "tests/test_sample.py:16: ループの中の条件を通った要素にしか届かないアサーションがある"
        "（絞り込みを名前へ束ねて空でないことを確かめる）",
        "tests/test_sample.py:22: ループの中の条件を通った要素にしか届かないアサーションがある"
        "（絞り込みを名前へ束ねて空でないことを確かめる）",
        "tests/test_sample.py:29: その場で絞り込んだ母集団を検査している（名前へ束ねて空でないことを確かめる）",
        "tests/test_sample.py:30: その場で絞り込んだ母集団を検査している（名前へ束ねて空でないことを確かめる）",
        "tests/test_sample.py:35: 絞り込んだ母集団 `picked` が空でも通る（空でないことを同じテストで確かめる）",
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
        "        assert value > 0\n"
        "    assert all(v > 0 for v in picked)\n\n\n"
        "def test_asserts_length_of_a_module_level_population():\n"
        "    assert len(PICKED) >= 1\n"
        "    for key, value in PICKED.items():\n"
        "        assert value\n\n\n"
        "def test_every_element_reaches_an_assertion():\n"
        "    for key, value in SPECS.items():\n"
        "        if value > 5:\n"
        "            assert key\n"
        "        else:\n"
        "            assert value\n"
        "        if value:\n"
        "            key = key.upper()\n"
        "        assert key\n"
        "    assert all(k in {s for s in SPECS if s} for k in SPECS)\n\n\n"
        "def _cases():\n"
        "    colors = [c for c in SPECS if c]\n"
        "    return colors\n\n\n"
        "def test_population_given_by_the_caller(colors):\n"
        "    for color in colors:\n"
        "        assert color\n",
    )

    assert vacuous_loops(root) == []
