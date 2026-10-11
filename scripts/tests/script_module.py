"""リポジトリの根の`scripts/`の道具（パッケージでない1ファイル）を、テストから読み込む道具。"""

import importlib.util
from pathlib import Path
from types import ModuleType

SCRIPTS = Path(__file__).resolve().parents[1]


def load_script(name: str) -> ModuleType:
    """`scripts/<name>.py`を`<name>`のモジュールとして読み込んで返す。"""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
