"""backendのデプロイ対象から外したファイルが、本番で読まれていないことの検査。

`scripts/deploy_backend_gate.py`の`DEPLOY_PATHS`は、本番プロセスに届かない変更でコンテナを
入れ替えないよう、一部のファイルを`!`で外している。外したファイルを本番側のコードが
importすると、**そのファイルの変更だけが本番へ届かなくなる**。エラーにはならず、古い値で
動き続ける。

母集団はその一覧とDockerfileから導く。外したパターンのうちイメージへ入るコード
（DockerfileがCOPYするディレクトリ配下の`.py`）に当たるものについて、外していない同じ
範囲の`.py`からの参照（関数内の遅延importと、モジュール名を文字列で渡す形を含む）を探す。
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent

_SPEC = importlib.util.spec_from_file_location("deploy_backend_gate", REPO / "scripts" / "deploy_backend_gate.py")
_GATE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_GATE)


def _excluded_patterns() -> list[str]:
    return [p[1:] for p in _GATE.DEPLOY_PATHS if p.startswith("!")]


def _image_code_dirs() -> list[Path]:
    """DockerfileがCOPYするもののうちディレクトリ（イメージへ入るコードの置き場）。"""
    dirs = []
    for line in (BACKEND / "Dockerfile").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if parts[:1] == ["COPY"]:
            dirs += [BACKEND / src for src in parts[1:-1] if (BACKEND / src).is_dir()]
    return dirs


def _excluded_files() -> dict[str, list[Path]]:
    # pathlibの`**`はディレクトリにしか当たらない（GitHubの`**`は配下のファイルにも当たる）。
    return {
        pattern: sorted(p for p in REPO.glob(pattern + "/*" if pattern.endswith("**") else pattern) if p.is_file())
        for pattern in _excluded_patterns()
    }


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(BACKEND).with_suffix("").parts)


def _referenced_names(tree: ast.Module, module_parts: tuple[str, ...]) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                base_parts = module_parts[: len(module_parts) - node.level]
                base = ".".join([*base_parts, node.module] if node.module else list(base_parts))
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value)
    return names


def test_every_excluded_pattern_matches_a_file() -> None:
    """消えたファイルを外したまま残すと、同じ名前で作り直したときに黙ってデプロイ対象外になる。"""
    assert [pattern for pattern, files in _excluded_files().items() if not files] == []


def test_excluded_code_in_the_image_is_not_referenced_by_production_code() -> None:
    image_dirs = _image_code_dirs()
    excluded = {path for files in _excluded_files().values() for path in files}
    excluded_in_image = {
        _module_name(path): path
        for path in excluded
        if path.suffix == ".py" and any(path.is_relative_to(d) for d in image_dirs)
    }

    violations = []
    for directory in image_dirs:
        for path in sorted(directory.rglob("*.py")):
            if path in excluded:
                continue
            module_parts = tuple(_module_name(path).split("."))
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for name in sorted(_referenced_names(tree, module_parts) & excluded_in_image.keys()):
                violations.append(f"{path.relative_to(BACKEND).as_posix()} -> {name}")

    assert violations == [], (
        "deploy_backend_gate.pyのDEPLOY_PATHSで外したモジュールを本番側のコードが参照している。"
        "参照を残すならDEPLOY_PATHSの除外を外す:\n" + "\n".join(violations)
    )
