"""テストが共有の足場（fixture・代役・組み立ての関数）と同じ役のものを、自分のファイルに写していないことの検査。

共有の足場があるのに写すと、足場を直したときに写しだけが古いまま残り、テストは本物とずれた足場の上で通り続ける
（.claude/rules/testing.md「フェイクの数は、実装の外向き参照の写し」の「共有フェイクへ出すのは3箇所目から」）。

母集団はソースから導く——`backend/tests`配下の全`.py`（この検査のディレクトリを除く）。名前が`test_`で始まらない
ファイル（`conftest.py`を含む）を共有の足場、`test_`で始まるファイルをテストとして読む。違反は次の3つ:

1. 最上位の定義の写し: 最上位の関数・クラス（名前と docstring を除いた本体）か、最上位の値（葉——定数と名前——が
   5つ以上の式）が、3つ以上のファイルで同じ。2つまでは落とさない（3箇所目から足場へ出す決まり）。
2. 足場と同じ差し替え: 共有の足場が`setattr`・`patch`で差し替える名前を、テストのファイルも差し替える。持ち主
   （モジュール・クラス・値）が決まる差し替えは持ち主と名前で、足場の側で持ち主が引数・変数で決まらない差し替えは
   名前だけで突き合わせる。差し替えたいときは足場の口（fixture の引数・`indirect`等）を通す。
3. 足場の式の写し: 共有の足場の中で、呼び出しの引数に呼び出しが入れ子になった式（3段以上）と同じ式を、テストのファイルが
   書く（`asyncpg.connect(asyncpg_dsn(postgis_database_url()))`のように、足場が組み立てて配るものを自分で組む形）。

**判定しない形**: 関数の中の定義と、1つの呼び出しの名付け（`client = TestClient(app)`等。葉が5つ未満）。
`pytestmark`（pytest がファイルごとに読む宣言）。名前の違う同じ形の値のうち葉が5つ未満のもの。足場の式と同じ形でも
引数の違う式（足場の`asyncpg.connect(asyncpg_dsn(url))`と`asyncpg.connect(asyncpg_dsn(postgis_database_url()))`）。

ここで見ないもの:
- frontend の同じ写し → `frontend/src/structure/scaffoldCopies.test.ts`
- `app.domain`の関数・クラスの差し替え → `test_domain_not_replaced.py`
"""

from __future__ import annotations

import ast
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

from tests.structure.source_symbols import Scope, SourceTree, Symbol, replacement_calls

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
MIN_VALUE_LEAVES = 5
MIN_COPIES = 3
MIN_NESTED_CALLS = 3


def _sources(root: Path) -> list[Path]:
    tests = root / "tests"
    return [
        path for path in sorted(tests.rglob("*.py"))
        if "structure" not in path.relative_to(tests).parts and path.name != "__init__.py"
    ]


def _is_scaffold(path: Path) -> bool:
    return not path.name.startswith("test_")


def _without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    first = body[0] if body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        return body[1:]
    return body


def _leaves(node: ast.AST) -> int:
    return sum(isinstance(n, (ast.Constant, ast.Name)) for n in ast.walk(node))


def _definitions(tree: ast.Module) -> Iterator[tuple[str, int, str]]:
    """最上位の定義の (名前, 行, 本体の形)。値は葉が`MIN_VALUE_LEAVES`以上のものだけ。"""
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            shape = ast.dump(type(stmt)(**{
                **{field: getattr(stmt, field) for field in stmt._fields},
                "name": "_", "body": _without_docstring(stmt.body),
            }))
            yield stmt.name, stmt.lineno, shape
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None:
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if names and names != ["pytestmark"] and _leaves(stmt.value) >= MIN_VALUE_LEAVES:
                yield names[0], stmt.lineno, ast.dump(stmt.value)


def copied_definitions(root: Path) -> list[str]:
    """3つ以上のファイルに同じ本体で現れる最上位の定義（`パス:行: 名前`）。"""
    places: dict[str, dict[str, str]] = defaultdict(dict)
    for path in _sources(root):
        for name, line, shape in _definitions(ast.parse(path.read_text(encoding="utf-8"))):
            places[shape].setdefault(path.relative_to(root).as_posix(), f"{line}: {name}")
    return sorted(
        f"{file}:{where}（{len(files)}ファイル）"
        for files in places.values() if len(files) >= MIN_COPIES for file, where in files.items()
    )


def _owner_key(owner: Symbol) -> tuple[str, str, int]:
    return owner.kind, owner.module, getattr(owner.node, "lineno", 0)


def _replacements(source: SourceTree, path: Path, tree: ast.Module) -> Iterator[tuple[int, tuple | None, str]]:
    """差し替えの (行, 持ち主の鍵（決まらなければNone）, 名前)。名前が文字列で書かれたものだけ。"""
    scope = Scope(source, source.module_of(path), tree)
    for call, _ in replacement_calls(tree):
        first = call.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            split = source.dotted(first.value)
            if split is not None:
                yield call.lineno, _owner_key(split[0]), split[1]
            continue
        if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant) and isinstance(call.args[1].value, str):
            owner = scope.resolve(first)
            yield call.lineno, _owner_key(owner) if owner else None, call.args[1].value


def scaffold_replacements_repeated(root: Path) -> list[str]:
    """共有の足場が差し替える名前を、テストのファイルも差し替えている箇所（`パス:行: 名前`）。"""
    source = SourceTree(root)
    trees = {path: ast.parse(path.read_text(encoding="utf-8")) for path in _sources(root)}
    owned: set[tuple[tuple | None, str]] = set()
    for path, tree in trees.items():
        if _is_scaffold(path):
            owned.update((owner, name) for _, owner, name in _replacements(source, path, tree))
    out = []
    for path, tree in trees.items():
        if _is_scaffold(path):
            continue
        for line, owner, name in _replacements(source, path, tree):
            if (None, name) in owned or (owner is not None and (owner, name) in owned):
                out.append(f"{path.relative_to(root).as_posix()}:{line}: {name}")
    return sorted(out)


def _call_depth(node: ast.AST) -> int:
    if not isinstance(node, ast.Call):
        return 0
    return 1 + max((_call_depth(arg) for arg in [*node.args, *(k.value for k in node.keywords)]), default=0)


def _nested_calls(tree: ast.Module) -> Iterator[ast.Call]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_depth(node) >= MIN_NESTED_CALLS:
            yield node


def scaffold_expressions_rewritten(root: Path) -> list[str]:
    """共有の足場が組み立てる入れ子の呼び出しを、テストのファイルが同じ形で書いている箇所（`パス:行: 式`）。"""
    trees = {path: ast.parse(path.read_text(encoding="utf-8")) for path in _sources(root)}
    built = {ast.dump(call) for path, tree in trees.items() if _is_scaffold(path) for call in _nested_calls(tree)}
    return sorted(
        f"{path.relative_to(root).as_posix()}:{call.lineno}: {ast.unparse(call)}"
        for path, tree in trees.items() if not _is_scaffold(path)
        for call in _nested_calls(tree) if ast.dump(call) in built
    )


def test_tests_do_not_copy_definitions_into_three_or_more_files() -> None:
    copies = copied_definitions(BACKEND_ROOT)

    assert copies == [], (
        "同じ本体の最上位の定義が3つ以上のファイルにある。共有の足場（`tests/`の`test_`で始まらないファイル）へ"
        "1つにまとめ、各ファイルはそれを使うこと:\n  " + "\n  ".join(copies)
    )


def test_tests_do_not_replace_what_the_scaffold_replaces() -> None:
    repeated = scaffold_replacements_repeated(BACKEND_ROOT)

    assert repeated == [], (
        "共有の足場が差し替える名前を、テストが自分でも差し替えている。足場の口（fixture・その引数・`indirect`）を"
        "通すこと:\n  " + "\n  ".join(repeated)
    )


def test_tests_do_not_rebuild_what_the_scaffold_builds() -> None:
    rebuilt = scaffold_expressions_rewritten(BACKEND_ROOT)

    assert rebuilt == [], (
        "共有の足場が組み立てる式を、テストが自分で書いている。足場の関数・fixture を使うこと:\n  " + "\n  ".join(rebuilt)
    )


def _backend(tmp_path: Path, files: dict[str, str]) -> Path:
    for relative, text in {
        "app/__init__.py": "",
        "app/store.py": "ROOT = None\n\n\ndef log_call(name):\n    return name\n",
        "tests/__init__.py": "",
        **files,
    }.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(text, encoding="utf-8")
    return tmp_path


def test_detects_definitions_copied_into_three_files_but_not_two(tmp_path: Path) -> None:
    """落とす側は、名前と docstring の違う同じ関数・葉が5つ以上の同じ値の3ファイル。落とさない側は、2ファイルの写し・
    葉が5つ未満の値・`pytestmark`。"""
    helper = 'def {name}(x):\n    """{doc}"""\n    return [x, x + 1]\n'
    table = 'TABLE = ("a", "b", "c", "d", "e")\n'
    twice = "def twice(x):\n    return x * 2\n"
    small = 'pytestmark = ("a", "b", "c", "d", "e")\nSMALL = ("a", "b")\n'
    root = _backend(tmp_path, {
        "tests/test_one.py": helper.format(name="_pair", doc="一") + table + twice + small,
        "tests/test_two.py": helper.format(name="_pair", doc="二") + table + twice + small,
        "tests/support.py": helper.format(name="pair", doc="三") + table + small,
    })

    assert copied_definitions(root) == [
        "tests/support.py:1: pair（3ファイル）",
        "tests/support.py:4: TABLE（3ファイル）",
        "tests/test_one.py:1: _pair（3ファイル）",
        "tests/test_one.py:4: TABLE（3ファイル）",
        "tests/test_two.py:1: _pair（3ファイル）",
        "tests/test_two.py:4: TABLE（3ファイル）",
    ]


def test_detects_tests_replacing_what_the_scaffold_replaces(tmp_path: Path) -> None:
    """落とす側は、足場が持ち主を決めて差し替える名前（文字列の道筋の形も）と、足場が持ち主を引数で受けて差し替える名前を、
    テストが差し替える形。落とさない側は、足場が差し替えない名前と、足場と同じ名前を別の持ち主で差し替える形。"""
    root = _backend(tmp_path, {
        "tests/support.py": (
            "from app import store\n\n\n"
            "def moved(monkeypatch, path):\n    monkeypatch.setattr(store, 'ROOT', path)\n\n\n"
            "def recorded(monkeypatch, module):\n    monkeypatch.setattr(module, 'log_call', print)\n"
        ),
        "tests/test_sample.py": (
            "import os\n\nfrom app import store\n\n\n"
            "def test_x(monkeypatch, tmp_path):\n"
            "    monkeypatch.setattr(store, 'ROOT', tmp_path)\n"
            "    monkeypatch.setattr('app.store.ROOT', tmp_path)\n"
            "    monkeypatch.setattr(os, 'log_call', print)\n"
            "    monkeypatch.setattr(os, 'ROOT', tmp_path)\n"
            "    monkeypatch.setattr(store, 'OTHER', tmp_path)\n"
        ),
    })

    assert scaffold_replacements_repeated(root) == [
        "tests/test_sample.py:7: ROOT",
        "tests/test_sample.py:8: ROOT",
        "tests/test_sample.py:9: log_call",
    ]


def test_detects_tests_rebuilding_a_nested_call_the_scaffold_builds(tmp_path: Path) -> None:
    """落とす側は、足場の3段の入れ子の呼び出しと同じ式。落とさない側は、引数の違う式と2段の入れ子。"""
    root = _backend(tmp_path, {
        "tests/support.py": "def connection():\n    return open(str(url()))\n\n\ndef short():\n    return str(url())\n",
        "tests/test_sample.py": (
            "def test_x():\n    open(str(url()))\n    open(str(other()))\n    str(url())\n"
        ),
    })

    assert scaffold_expressions_rewritten(root) == ["tests/test_sample.py:2: open(str(url()))"]
