"""`config.py: Settings`の各項目が、`config.py`以外の本番コードで読まれていることの検査。

読み手の無い設定項目は、環境変数で値を変えても何も起きないまま残り、読んだ人に「これを
変えれば効く」と思わせる。読み手が消えるのは、その値を使っていた仕組みを撤去したとき
で、撤去の差分には設定の側が現れないため、見落とされやすい。

母集団はソースから導く——`Settings`のフィールドは`model_fields`から、読み手は
`backend/app`と`backend/scripts`（デプロイ・運用で本番環境から実行される）の全`.py`を
ASTで読んで数える。読みとして数えるのは、同じ名前の属性アクセス（`settings.x`）と、同じ
名前の文字列（`getattr(settings, "x")`・`Settings.model_fields["x"]`）。プロパティ
（`cors_allowed_origins_list`等）が読まれていれば、そのプロパティが`self`から読む項目も
読まれているとみなす。
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.config import Settings

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = BACKEND_ROOT / "app" / "config.py"
READER_ROOTS = (BACKEND_ROOT / "app", BACKEND_ROOT / "scripts")


def _property_fields(config_source: str) -> dict[str, set[str]]:
    """`Settings`のプロパティ名→そのプロパティが`self`から読む名前。"""
    tree = ast.parse(config_source)
    out: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == Settings.__name__):
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef):
                continue
            if not any(isinstance(d, ast.Name) and d.id == "property" for d in item.decorator_list):
                continue
            out[item.name] = {
                sub.attr
                for sub in ast.walk(item)
                if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) and sub.value.id == "self"
            }
    return out


def _names_read(sources: list[str]) -> set[str]:
    """ソース群に現れる属性名と文字列の定数。"""
    names: set[str] = set()
    for source in sources:
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names.add(node.value)
    return names


def unread_settings(fields: set[str], properties: dict[str, set[str]], reader_sources: list[str]) -> set[str]:
    """読み手の無い項目。"""
    read = _names_read(reader_sources)
    read |= {field for name, used in properties.items() if name in read for field in used}
    return fields - read


def _reader_sources() -> list[str]:
    return [
        path.read_text(encoding="utf-8")
        for root in READER_ROOTS
        for path in sorted(root.rglob("*.py"))
        if path != CONFIG_PATH
    ]


def test_every_setting_has_a_reader_outside_config() -> None:
    unread = unread_settings(
        set(Settings.model_fields), _property_fields(CONFIG_PATH.read_text(encoding="utf-8")), _reader_sources()
    )

    assert unread == set(), (
        "config.py以外の本番コードで読まれていない設定項目がある（読み手を撤去したなら項目も消す）:\n  "
        + "\n  ".join(sorted(unread))
    )


def test_detects_an_unread_setting_and_counts_every_form_of_read() -> None:
    """検査が効いていること——読み手を1つずつ外した入力で、その項目だけが残る。"""
    properties = {"origins_list": {"origins"}}
    fields = {"by_attribute", "by_string", "origins", "unread"}
    readers = [
        "value = settings.by_attribute",
        "default = Settings.model_fields['by_string'].default",
        "allowed = settings.origins_list",
    ]

    assert unread_settings(fields, properties, readers) == {"unread"}
    assert unread_settings(fields, properties, readers[:2]) == {"origins", "unread"}
