"""処理のコードの指紋。**あるモジュールから`import`でたどれる`app`の中のモジュールの中身**から作る。

入力が前回と同じなら処理をしない仕組み（取込: `ingest.py`・派生の段: `derive_cli.py`）は、コードも入力に数える。コードを入れないと、
読み方を直したあとも前回の結果が残る。

たどるのはソースの文（AST）で、関数の中の`import`も数える（重いライブラリを使うときだけ読むモジュールが、
関数の中で読み込む）。`from <パッケージ> import <名前>`は、名前がモジュールならそのモジュールも数える。
パッケージを読むと`__init__.py`が走るので、たどったモジュールの親のパッケージも数える。`app`の外
（標準ライブラリ・依存のライブラリ）はたどらない——ライブラリの版は、使う側が別に数える（`library_versions`）。
"""

import ast
import hashlib
import importlib.metadata
from pathlib import Path

#: `app`のパッケージを置いた場所（`backend/`）。モジュールの名前はここから読むファイルへ移す。
ROOT = Path(__file__).resolve().parents[2]

_PACKAGE = "app"


def _module_file(name: str) -> Path | None:
    """モジュールの名前が指すファイル。モジュールでなければ（クラス・関数の名前）None。"""
    base = ROOT.joinpath(*name.split("."))
    for path in (base / "__init__.py", base.with_suffix(".py")):
        if path.is_file():
            return path
    return None


def _in_app(name: str) -> bool:
    return name == _PACKAGE or name.startswith(f"{_PACKAGE}.")


def _imported(name: str, path: Path) -> set[str]:
    """`path`（モジュール`name`）が読み込む`app`の中のモジュールの名前（モジュールでない名前も混ざる）。"""
    package = name if path.name == "__init__.py" else name.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_bytes(), filename=str(path))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[:len(parts) - node.level + 1])
                module = f"{base}.{node.module}" if node.module else base
            else:
                module = node.module or ""
            found.add(module)
            found.update(f"{module}.{alias.name}" for alias in node.names)
    return {module for module in found if _in_app(module)}


def _with_parents(name: str) -> list[str]:
    parts = name.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts) + 1)]


def reachable_modules(module: str) -> dict[str, Path]:
    """`module`から`import`でたどれる`app`の中のモジュール（`module`と親のパッケージを含む）の名前 → ファイル。"""
    seen: dict[str, Path] = {}
    pending = _with_parents(module)
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        path = _module_file(name)
        if path is None:
            continue
        seen[name] = path
        for imported in _imported(name, path):
            pending.extend(_with_parents(imported))
    return seen


def code_fingerprint(module: str) -> str:
    """`module`からたどれるモジュールの名前と中身のSHA-256。どれか1つの中身が変わると変わる。"""
    digest = hashlib.sha256()
    for name, path in sorted(reachable_modules(module).items()):
        digest.update(name.encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def library_versions() -> list[str]:
    """入っているライブラリの名前と版（`<名前>==<版>`）。"""
    return sorted(f"{dist.metadata['Name']}=={dist.version}" for dist in importlib.metadata.distributions())
