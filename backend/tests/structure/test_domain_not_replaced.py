"""テストが`app.domain`の関数・クラスを差し替えていないことの検査。

自分のdomainの関数・クラスは差し替えずに本物を通す（docs/conventions/testing.md「確かめる高さ」）。
差し替えると、テストは実装の途中の手順を写したものになり、作り替えを越えられない。
差し替えてよい宣言のデータ（`TUNING_VALUES`・`MATERIAL_CATALOG`等）は関数・クラスではないので、ここでは落ちない。

母集団はソースから導く——`backend/tests`配下の全`.py`（この検査のディレクトリを除く）を読み、
`setattr`（`monkeypatch.setattr`・`MonkeyPatch.context()`の`setattr`・組み込み）と`patch`・`patch.object`の
呼び出しで差し替える名前を、import を辿って定義元まで引く。他の層のモジュール越しに差し替える形
（`services`が import した domain の関数を、`services`の名前空間で差し替える）も、定義元で決まる。

**判定しない形**: 差し替える相手（持ち主）を変数・引数で渡す形は、ソースから相手が決まらない。名前だけを
変数で渡す形は、同じ関数の中の文字列リテラルのうち持ち主が持つ名前をすべて候補として判定する。

ここで見ないもの:
- 差し替えたフェイクが本物の署名に合うか → 差し替えるテストが`tests/bound_fake.py: bound`で当てる
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from tests.structure.source_symbols import Scope, SourceTree, Symbol

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
DOMAIN = "app.domain"


def _replacement_calls(tree: ast.Module) -> Iterator[tuple[ast.Call, ast.AST]]:
    """差し替えの呼び出しと、それを含む最上位の定義（関数・クラス。無ければモジュール）。"""
    for top in tree.body:
        for node in ast.walk(top):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
            if name in ("setattr", "patch", "object"):
                yield node, top


def _string_literals(node: ast.AST) -> set[str]:
    return {n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def _replaced(scope: Scope, call: ast.Call, enclosing: ast.AST) -> Iterator[tuple[str, Symbol]]:
    """呼び出しが差し替える名前（`持ち主.名前`）と、その名前が今指しているもの。"""
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        split = scope.source.dotted(first.value)
        if split is None:
            return
        owner, names = split[0], [split[1]]
        owner_text = first.value.rsplit(".", 1)[0]
    else:
        if len(call.args) < 2:
            return
        owner = scope.resolve(first)
        if owner is None:
            return
        owner_text = ast.unparse(first)
        name = call.args[1]
        if isinstance(name, ast.Constant) and isinstance(name.value, str):
            names = [name.value]
        else:
            names = sorted(_string_literals(enclosing))
    for attribute in names:
        target = scope.source.attribute(owner, attribute)
        if target is not None:
            yield f"{owner_text}.{attribute}", target


def domain_replacements(root: Path) -> list[str]:
    """`root`（`backend`）の`tests`で、`app.domain`で定義された関数・クラスを差し替えている箇所。"""
    source = SourceTree(root)
    out: list[str] = []
    for path in sorted((root / "tests").rglob("*.py")):
        if "structure" in path.relative_to(root / "tests").parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        scope = Scope(source, source.module_of(path), tree)
        for call, enclosing in _replacement_calls(tree):
            for text, target in _replaced(scope, call, enclosing):
                if target.kind in ("function", "class") and (
                    target.module == DOMAIN or target.module.startswith(f"{DOMAIN}.")
                ):
                    out.append(f"{path.relative_to(root).as_posix()}:{call.lineno}: {text}（{target.module}）")
    return out


def test_tests_do_not_replace_domain_functions_or_classes() -> None:
    violations = domain_replacements(BACKEND_ROOT)

    assert violations == [], (
        "`app.domain`の関数・クラスを差し替えているテストがある。本物を通し、入力（宣言のデータ・引数）で"
        "条件を作ること（docs/conventions/testing.md「確かめる高さ」）:\n  " + "\n  ".join(violations)
    )


def _backend(tmp_path: Path, test_source: str) -> Path:
    for relative, text in {
        "app/__init__.py": "",
        "app/domain/__init__.py": "",
        "app/domain/speed.py": "TABLE = {}\n\n\ndef cruise():\n    return 1.0\n\n\nclass Model:\n    def run(self):\n        return 0\n",
        "app/services/__init__.py": "",
        "app/services/planner.py": "from app.domain.speed import cruise\n",
        "tests/__init__.py": "",
        "tests/test_sample.py": test_source,
    }.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(text, encoding="utf-8")
    return tmp_path


def test_detects_replaced_domain_functions_and_classes_but_not_declared_data(tmp_path: Path) -> None:
    """検査が効いていること。落とす側は、他の層が import した domain の関数をその層の名前空間で差し替える形・
    文字列の道筋・クラスのメソッド・名前を変数で渡す形。落とさない側は、宣言のデータ（辞書・定数）の差し替え。"""
    root = _backend(
        tmp_path,
        "from app.domain import speed\nfrom app.domain.speed import Model\nfrom app.services import planner\n\n\n"
        "def test_x(monkeypatch):\n"
        "    monkeypatch.setattr(planner, 'cruise', lambda: 2.0)\n"
        "    monkeypatch.setattr('app.domain.speed.cruise', lambda: 2.0)\n"
        "    monkeypatch.setattr(Model, 'run', lambda self: 1)\n"
        "    monkeypatch.setattr(speed, 'TABLE', {'a': 1})\n"
        "    monkeypatch.setitem(speed.TABLE, 'a', 1)\n\n\n"
        "def test_y(monkeypatch):\n"
        "    for name in ('Model',):\n"
        "        monkeypatch.setattr(speed, name, object)\n",
    )

    assert domain_replacements(root) == [
        "tests/test_sample.py:7: planner.cruise（app.domain.speed）",
        "tests/test_sample.py:8: app.domain.speed.cruise（app.domain.speed）",
        "tests/test_sample.py:9: Model.run（app.domain.speed）",
        "tests/test_sample.py:16: speed.Model（app.domain.speed）",
    ]
