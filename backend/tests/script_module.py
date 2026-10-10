"""リポジトリの根の`scripts/`の道具（パッケージでない1ファイル）を、テストから読み込む道具。"""

import importlib.util
from pathlib import Path
from types import ModuleType

# 根は`.git`を持つ祖先で決める。このファイルからの段数で決めると、変異テストが`backend`を写した作業場
# （`backend/mutants/`）から読んだときに`backend`を根と取り違える。
SCRIPTS = next(p for p in Path(__file__).resolve().parents if (p / ".git").exists()) / "scripts"


def load_script(name: str) -> ModuleType:
    """`scripts/<name>.py`を`<name>`のモジュールとして読み込んで返す。"""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
