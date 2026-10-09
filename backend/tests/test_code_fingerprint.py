"""コードの指紋（`code_fingerprint.py`）が、モジュールから`import`でたどれる`app`の中のモジュールだけを数えること。

コードの置き場（`code_fingerprint.ROOT`）を一時ディレクトリへ移し、そこに小さな`app`を書いて見る。
"""

import pytest

from app.batch import code_fingerprint


@pytest.fixture
def app_root(monkeypatch, tmp_path):
    files = {
        "app/__init__.py": "",
        "app/batch/__init__.py": "",
        # 関数の中の import・相対の import・`from <パッケージ> import <モジュール>` をたどる
        "app/batch/adapter.py": "import json\nfrom app.batch import helper\n\ndef read():\n"
                                "    from .lazy import VALUE\n    return VALUE\n",
        "app/batch/helper.py": "from app.domain.rules import LIMIT\n",
        "app/batch/lazy.py": "VALUE = 1\n",
        "app/domain/__init__.py": "",
        "app/domain/rules.py": "LIMIT = 3\n",
        "app/batch/unrelated.py": "OTHER = 2\n",
    }
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(code_fingerprint, "ROOT", tmp_path)
    return tmp_path


def test_modules_reachable_by_import_are_counted(app_root):
    assert sorted(code_fingerprint.reachable_modules("app.batch.adapter")) == [
        "app", "app.batch", "app.batch.adapter", "app.batch.helper", "app.batch.lazy", "app.domain",
        "app.domain.rules"]


@pytest.mark.parametrize("changed, differs", [
    ("app/batch/lazy.py", True),
    ("app/domain/rules.py", True),
    ("app/batch/unrelated.py", False),
])
def test_the_fingerprint_changes_only_with_a_reachable_module(app_root, changed, differs):
    before = code_fingerprint.code_fingerprint("app.batch.adapter")
    path = app_root / changed
    path.write_text(path.read_text(encoding="utf-8") + "# 直した\n", encoding="utf-8")

    assert (code_fingerprint.code_fingerprint("app.batch.adapter") != before) is differs
