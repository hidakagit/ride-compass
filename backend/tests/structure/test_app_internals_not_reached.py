"""テストが`app`の内部名（`_`で始まる名前）へ入っていないことの検査。

振る舞いはモジュールの公開の入口で確かめ、内部名へ直接入らない（.claude/rules/testing.md「確かめる高さ」）。
内部名へ入ったテストは、実装の途中の形を写したものになり、作り替えを越えられない。

母集団はソースから導く——`backend/tests`配下の全`.py`（この検査のディレクトリを除く）を読み、次の形を数える。
- `from app… import _x`
- `持ち主._x`で、持ち主が import を辿って`app`のもの（モジュール・クラス・最上位の値）に決まる形
- `値._x`で、値がソースから決まらない（インスタンス・引数・呼び出しの結果）形。`_x`が`app`の定義する名前
  （最上位・クラスの本体・関数の中の名前と、`self._x`への代入）にあり、テストの側（そのファイルと、`tests`直下の
  共有の足場）が自分で定義する名前でないときだけ数える。外のライブラリの名前（SQLAlchemy の`Row._mapping`等）は、
  `app`が定義しないので数えない。
- `setattr`・`getattr`・`delattr`・`hasattr`・`patch.object`へ名前を文字列で渡す形と、
  `setattr`・`delattr`・`patch`へ`"app.x._y"`の道筋を渡す形（持ち主は上の2つと同じに見分ける）

**判定しない形**: 名前を変数で渡す形（`setattr(m, name, …)`）と、文字列を組み立てて作る道筋。

ここで見ないもの:
- `app.domain`の関数・クラスを（公開名でも）差し替えること → `test_domain_not_replaced.py`
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path

from tests.structure.source_symbols import Scope, SourceTree

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
APP = "app"
#: 持ち主と名前の文字列を受ける呼び出し（`monkeypatch.setattr`・`patch.object`・組み込みの`getattr`等）。
NAMED_BY_STRING = {"setattr", "getattr", "delattr", "hasattr", "object"}
#: `"app.x.y"`の道筋を受ける呼び出し（`monkeypatch.setattr`・`monkeypatch.delattr`・`patch`）。
NAMED_BY_PATH = {"setattr", "delattr", "patch"}


def _internal(name: str) -> bool:
    return len(name) > 1 and name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _in_app(module: str) -> bool:
    return module == APP or module.startswith(f"{APP}.")


def _defined(tree: ast.AST) -> set[str]:
    """木が定義する名前（関数・クラス・代入・引数と、`self.x`への代入）。"""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            out.add(node.id)
        elif isinstance(node, ast.arg):
            out.add(node.arg)
        elif (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store)
              and isinstance(node.value, ast.Name) and node.value.id == "self"):
            out.add(node.attr)
    return out


def _named_by_string(call: ast.Call, reaches: Callable[[ast.expr, str], bool]) -> str | None:
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
    args = call.args
    if (name in NAMED_BY_STRING and len(args) >= 2 and isinstance(args[1], ast.Constant)
            and isinstance(args[1].value, str) and reaches(args[0], args[1].value)):
        return f"{ast.unparse(args[0])}.{args[1].value}"
    if name in NAMED_BY_PATH and args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
        parts = args[0].value.split(".")
        if parts[0] == APP and any(_internal(part) for part in parts):
            return args[0].value
    return None


def internal_reaches(root: Path) -> list[str]:
    """`root`（`backend`）の`tests`で、`app`の内部名へ入っている箇所。"""
    source = SourceTree(root)
    defined = set().union(*(_defined(ast.parse(path.read_text(encoding="utf-8"))) for path in (root / APP).rglob("*.py")))
    tests = {
        path: ast.parse(path.read_text(encoding="utf-8"))
        for path in sorted((root / "tests").rglob("*.py"))
        if "structure" not in path.relative_to(root / "tests").parts
    }
    shared = set().union(*(_defined(tree) for path, tree in tests.items() if not path.name.startswith("test_")))
    found: list[tuple[str, int, str]] = []
    for path, tree in tests.items():
        module = source.module_of(path)
        scope = Scope(source, module, tree)
        own = shared | _defined(tree)

        def reaches(owner_expr: ast.expr, name: str) -> bool:
            if not _internal(name):
                return False
            owner = scope.resolve(owner_expr)
            if owner is not None:
                return _in_app(owner.module)
            return name in defined and name not in own

        for node in ast.walk(tree):
            text = None
            if isinstance(node, ast.ImportFrom) and _in_app(imported := source.absolute(module, node)):
                text = ", ".join(f"{imported}.{alias.name}" for alias in node.names if _internal(alias.name)) or None
            elif isinstance(node, ast.Attribute) and reaches(node.value, node.attr):
                text = ast.unparse(node)
            elif isinstance(node, ast.Call):
                text = _named_by_string(node, reaches)
            if text is not None:
                found.append((path.relative_to(root).as_posix(), node.lineno, text))
    return [f"{path}:{line}: {text}" for path, line, text in sorted(found)]


def test_tests_do_not_reach_app_internal_names() -> None:
    violations = internal_reaches(BACKEND_ROOT)

    assert violations == [], (
        "`app`の内部名（`_`で始まる名前）へ入っているテストがある。公開の入口で確かめるか、確かめたい計算を公開名にし、"
        "可変の状態は持ち主へ寄せて注入すること（.claude/rules/testing.md「確かめる高さ」）:\n  " + "\n  ".join(violations)
    )


def _backend(tmp_path: Path, test_source: str) -> Path:
    for relative, text in {
        "app/__init__.py": "",
        "app/batch/__init__.py": "",
        "app/batch/rebuild.py": (
            "_WORK = 'w'\n\n\ndef _now():\n    return 0\n\n\n"
            "class Store:\n    _LIMIT = 3\n\n    def __init__(self):\n        self._rows = []\n        self._calls = 0\n"
            "        self.size = 0\n"
        ),
        "app/services/__init__.py": "",
        "app/services/preview.py": "from app.batch.rebuild import _WORK\n\n_cache = {}\n",
        "tests/__init__.py": "",
        "tests/fakes.py": "class FakeRows:\n    def __init__(self):\n        self._calls = []\n",
        "tests/test_sample.py": test_source,
    }.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(text, encoding="utf-8")
    return tmp_path


def test_detects_reaching_app_internal_names_but_not_names_the_tests_or_libraries_own(tmp_path: Path) -> None:
    """検査が効いていること。落とす側は、取り込み・モジュールとクラスの属性・インスタンスの属性・名前の文字列・
    道筋の文字列。落とさない側は、`app`も同じ名前を定義していても、共有の足場とそのファイルが自分で定義する名前・
    `app`が定義しないライブラリの名前・特殊な名前・公開名。"""
    root = _backend(
        tmp_path,
        "from app.batch import rebuild\n"
        "from app.batch.rebuild import Store, _WORK\n"
        "from app.services import preview\n"
        "from tests.fakes import FakeRows\n\n\n"
        "class Clock:\n    def __init__(self):\n        self._now = 0\n\n\n"
        "def test_x(monkeypatch, row):\n"
        "    monkeypatch.setattr(preview, '_cache', {})\n"
        "    monkeypatch.setattr('app.batch.rebuild._WORK', 'x')\n"
        "    assert rebuild._WORK\n"
        "    assert Store._LIMIT\n"
        "    assert Store()._rows == []\n"
        "    assert FakeRows()._calls == []\n"
        "    assert Clock()._now == 0\n"
        "    assert row._mapping\n"
        "    assert rebuild.__name__\n"
        "    assert Store().size == 0\n",
    )

    assert internal_reaches(root) == [
        "tests/test_sample.py:2: app.batch.rebuild._WORK",
        "tests/test_sample.py:13: preview._cache",
        "tests/test_sample.py:14: app.batch.rebuild._WORK",
        "tests/test_sample.py:15: rebuild._WORK",
        "tests/test_sample.py:16: Store._LIMIT",
        "tests/test_sample.py:17: Store()._rows",
    ]
