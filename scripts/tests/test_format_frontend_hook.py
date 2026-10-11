"""`scripts/hooks/format_frontend.py`のテスト。

フックは Claude Code が標準入力で JSON を渡して打つので、同じく別のプロセスで打つ。prettier は、渡された引数と打たれた場所を
書き残すだけの代役に替える（整形の中身は prettier のもの）。

ここで見ないもの: 書いたファイルが CI の`format:check`を通るか（CI の frontend のジョブが見る）。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / "scripts" / "hooks" / "format_frontend.py"
FAKE_PRETTIER = """
const fs = require("fs");
fs.appendFileSync(process.env.PRETTIER_LOG, JSON.stringify({ cwd: process.cwd(), args: process.argv.slice(2) }) + "\\n");
"""


def _frontend(root: Path, with_prettier: bool = True) -> Path:
    frontend = root / "worktree" / "frontend"
    (frontend / "src").mkdir(parents=True)
    if with_prettier:
        bin_dir = frontend / "node_modules" / "prettier" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "prettier.cjs").write_text(FAKE_PRETTIER, encoding="utf-8")
    return frontend


def _write(tmp_path: Path, path: Path) -> list[dict]:
    """書いたファイルとしてフックへ渡し、prettier が打たれた記録を返す。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("const a=1\n", encoding="utf-8")
    log = tmp_path / "prettier.log"
    subprocess.run(
        [sys.executable, str(HOOK)], input=json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(path)}}),
        check=True, capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PRETTIER_LOG": str(log)},
    )
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


@pytest.mark.parametrize("relative, formatted", [
    ("src/app/page.tsx", True),
    ("src/lib/a.ts", True),
    ("src/app/globals.css", True),
    ("src/lib/a.js", False),
    ("e2e/a.ts", False),
])
def test_formats_what_the_ci_format_check_reads(tmp_path, relative, formatted):
    """CI の`format:check`が見る`src/**/*.{ts,tsx,css}`だけを、frontend の設定（`.prettierrc.json`）が効く場所で整える。"""
    frontend = _frontend(tmp_path)

    calls = _write(tmp_path, frontend / relative)

    assert calls == ([{"cwd": str(frontend), "args": ["--write", "--log-level", "warn", relative]}] if formatted else [])


def test_does_nothing_where_dependencies_are_not_installed(tmp_path):
    frontend = _frontend(tmp_path, with_prettier=False)

    assert _write(tmp_path, frontend / "src" / "a.ts") == []
