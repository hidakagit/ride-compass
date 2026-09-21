"""webアプリが読む層が、バッチ専用の依存を連鎖で引き込んでいないことの検査。

`app.batch`配下はバッチ実行時にしか要らない重い依存（ラスタ・OSM系）を読む。web層が
モジュールトップでこれをimportすると、本番のwebだけが起動できなくなる（依存が入っていない
ため）。共有したい値は`domain/`へ置くか、import自体を関数内へ遅延させる。

母集団はソースから導く——`backend/app`配下（`app/batch`自身を除く）の全`.py`をASTで読み、
**モジュール直下の**import文だけを見る（関数内の遅延importは対象外）。
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent.parent / "app"
BATCH_PACKAGE = "app.batch"


def _imported_modules(node: ast.stmt, module_parts: tuple[str, ...]) -> list[str]:
    """import文が指すモジュール名（相対importは絶対形へ直して返す）。"""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        if node.level == 0:
            base = node.module or ""
        else:
            # `from .. import x` は呼び出し元のパッケージ位置から解決する
            base_parts = module_parts[: len(module_parts) - node.level]
            base = ".".join([*base_parts, node.module] if node.module else list(base_parts))
        return [base] + [f"{base}.{alias.name}" for alias in node.names]
    return []


def web_layer_batch_imports(root: Path) -> list[str]:
    """web層がモジュール直下で`app.batch`をimportしている箇所を返す。"""
    out: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if path.is_relative_to(root / "batch"):
            continue
        module_parts = ("app", *path.relative_to(root).with_suffix("").parts)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:  # モジュール直下だけ
            hit = next(
                (
                    name
                    for name in _imported_modules(node, module_parts)
                    if name == BATCH_PACKAGE or name.startswith(f"{BATCH_PACKAGE}.")
                ),
                None,
            )
            if hit is not None:  # 1つのimport文につき1件
                out.append(f"{path.relative_to(root.parent).as_posix()}:{node.lineno}: {hit}")
    return out


def test_web_layer_does_not_import_batch_at_module_level() -> None:
    violations = web_layer_batch_imports(APP_ROOT)

    assert violations == [], (
        "webアプリが読む層が`app.batch`をモジュール直下でimportしている"
        "（バッチ専用依存を連鎖で引き込み、本番のwebだけ起動できなくなる）:\n  "
        + "\n  ".join(violations)
    )


def test_detects_a_module_level_batch_import(tmp_path: Path) -> None:
    """検査が効いていること（わざと1件置いて捕まえる）。"""
    root = tmp_path / "app"
    (root / "services").mkdir(parents=True)
    (root / "batch").mkdir()
    (root / "services" / "sample.py").write_text(
        "from app.batch.ingest import run\n", encoding="utf-8"
    )
    (root / "batch" / "ingest.py").write_text("from app.batch import x\n", encoding="utf-8")

    found = web_layer_batch_imports(root)

    assert found == ["app/services/sample.py:1: app.batch.ingest"], found
