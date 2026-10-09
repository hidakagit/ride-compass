"""コードの指紋: モジュールと、そこから`import`でたどれる`app`の中のモジュール全部の中身から作るハッシュ。

バッチの処理（派生の段）の出力は、読む入力のほかにその処理のコードで決まる。コードを入力に数えないと、分類器や
しきい値を直したあとも前回の出力を使い続ける。たどるのは`import`の文（関数の中・型のためだけのものも数える）と、
読み込むモジュールの親のパッケージ（`__init__.py`は読み込みのたびに実行される）。`app`の外（標準・外部の
ライブラリ）はたどらない。

中身は構文木で比べる——注釈・空白・docstringを変えただけでは指紋が変わらない（値を変えないので、変わると
入力が同じなのに作り直す）。`__doc__`を読むコードは無い前提で、docstringを中身から外す。
"""

import ast
import hashlib
from pathlib import Path
from types import ModuleType

_PACKAGE = "app"
_SOURCE_ROOT = Path(__file__).resolve().parents[2]


def _module_path(name: str) -> Path | None:
    """`app`の中のモジュール`name`のファイル。`app`の外か、モジュールでない名前（モジュールの中の名前）ならNone。"""
    if name != _PACKAGE and not name.startswith(_PACKAGE + "."):
        return None
    base = _SOURCE_ROOT.joinpath(*name.split("."))
    for path in (base.with_suffix(".py"), base / "__init__.py"):
        if path.is_file():
            return path
    return None


def _imported_names(name: str, path: Path, tree: ast.Module) -> list[str]:
    """モジュール`name`が読み込みうるモジュールの名前（モジュールでない名前も混ざる。`_module_path`が落とす）。"""
    package = name if path.name == "__init__.py" else name.rpartition(".")[0]
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.rsplit(".", node.level - 1)[0] if node.level > 1 else package
                base = f"{anchor}.{base}" if base else anchor
            names.append(base)
            names.extend(f"{base}.{alias.name}" for alias in node.names)
    return names


def _parents(name: str) -> list[str]:
    parts = name.split(".")
    return [".".join(parts[:end]) for end in range(1, len(parts))]


def _without_docstrings(tree: ast.Module) -> ast.Module:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                node.body = node.body[1:] or [ast.Pass()]
    return tree


def code_modules(module: ModuleType) -> dict[str, Path]:
    """`module`と、そこからたどれる`app`の中のモジュール（名前 → ファイル）。"""
    found: dict[str, Path] = {}
    pending = [module.__name__]
    while pending:
        name = pending.pop()
        if name in found:
            continue
        path = _module_path(name)
        if path is None:
            continue
        found[name] = path
        pending.extend(_parents(name))
        pending.extend(_imported_names(name, path, ast.parse(path.read_text(encoding="utf-8"))))
    return found


def code_fingerprint(module: ModuleType) -> str:
    """`module`のコードの指紋（`code_modules`の全部の構文木から作るハッシュ）。"""
    digest = hashlib.sha256()
    for name, path in sorted(code_modules(module).items()):
        tree = _without_docstrings(ast.parse(path.read_text(encoding="utf-8")))
        digest.update(f"{name}\0{ast.dump(tree)}\0".encode())
    return digest.hexdigest()
