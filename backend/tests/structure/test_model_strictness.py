"""`backend/app`配下のPydanticモデルが、未知フィールドの扱いを明示していることの検査。

`extra`の既定は`ignore`で、モデルが知らないフィールドは例外にならず捨てられる
（`domain/strict_model.py`のdocstringに、そのとき何が起きるかを書いてある）。
既定のまま素の`BaseModel`を継承すると、その選択がコードのどこにも現れない。

母集団はソースから導く——`backend/app`配下の全`.py`をASTで読み、`BaseModel`を**直接**
継承するクラスを数える。`StrictModel`経由の継承は対象外（あちらが`forbid`を宣言している）。
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent.parent / "app"


def _model_config_declares_extra(node: ast.ClassDef) -> bool:
    """クラス本体で`model_config = ConfigDict(extra=...)`を宣言しているか。"""
    for stmt in node.body:
        targets = stmt.targets if isinstance(stmt, ast.Assign) else []
        if isinstance(stmt, ast.AnnAssign):
            targets = [stmt.target]
        if not any(isinstance(t, ast.Name) and t.id == "model_config" for t in targets):
            continue
        value = stmt.value
        if isinstance(value, ast.Call) and any(kw.arg == "extra" for kw in value.keywords):
            return True
        if isinstance(value, ast.Dict) and any(
            isinstance(k, ast.Constant) and k.value == "extra" for k in value.keys
        ):
            return True
    return False


def bare_basemodel_classes(root: Path) -> list[str]:
    """`BaseModel`を直接継承し、`extra`を宣言していないクラスを返す。"""
    out: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            inherits_bare = any(
                (isinstance(b, ast.Name) and b.id == "BaseModel")
                or (isinstance(b, ast.Attribute) and b.attr == "BaseModel")
                for b in node.bases
            )
            if inherits_bare and not _model_config_declares_extra(node):
                out.append(f"{path.relative_to(root.parent).as_posix()}: {node.name}")
    return out


def test_pydantic_models_declare_how_unknown_fields_are_treated() -> None:
    violations = bare_basemodel_classes(APP_ROOT)

    assert violations == [], (
        "素の`BaseModel`を継承していて`extra`を宣言していないモデルがある。"
        "`StrictModel`（domain/strict_model.py）を継承するか、外部ペイロードを直接受けるなら"
        "そのクラスで`extra`を明示して理由を書くこと:\n  " + "\n  ".join(violations)
    )


def test_detects_a_bare_model(tmp_path: Path) -> None:
    """検査が効いていること（わざと素のBaseModelを1件置いて捕まえる）。"""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "sample.py").write_text(
        "from pydantic import BaseModel\n\n\nclass Loose(BaseModel):\n    name: str\n",
        encoding="utf-8",
    )

    assert bare_basemodel_classes(tmp_path / "app") == ["app/sample.py: Loose"]
