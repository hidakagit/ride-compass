"""単体で実行できるベンチマークが、どのコードを測ったかを出力へ残すことの検査（`benchmarks/revision.py`）。"""

import re
from pathlib import Path


def _benchmark_entry_modules() -> list[Path]:
    """単体で実行できる（`__main__`を持つ）ベンチマークのモジュール。"""
    root = Path(__file__).resolve().parents[2] / "benchmarks"
    return sorted(p for p in root.glob("*.py")
                  if 'if __name__ == "__main__":' in p.read_text(encoding="utf-8"))


def test_every_benchmark_entry_states_which_revision_it_measured():
    # 数字はタスクエントリへ「実測」として引用される。どのコードを測ったかが数字と
    # 一緒に出ない実行口が1つでもあると、そこから引かれた数字だけ素性が分からなくなる。
    modules = _benchmark_entry_modules()
    assert modules, "実行口を持つベンチマークが1つも無い（母集団の導出が壊れている）"
    missing = [
        p.name for p in modules
        if not re.search(r"^\s+(?:announce_revision|require_current_revision)\(\)$",
                         p.read_text(encoding="utf-8"), re.M)
    ]
    assert not missing, f"素性を出さない実行口: {missing}"
