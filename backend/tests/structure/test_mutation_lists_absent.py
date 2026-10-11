"""変異テストの一覧の口（`backend/scripts/mutation/`の`only.txt`・`recheck.txt`・`baseline.txt`）がチェックアウトに無いことの検査。

一覧の口は、作業ブランチを測る版に渡してその一覧だけを回すためのもの。masterへ入ると、以後の定期の測りが一覧の分しか回らず、
当て直しと見直しの段も走らない。変異テストの台本は`tests/structure`を外してテストを回す（`backend/scripts/mutation/setup.cfg`）ので、
測りの中で台本が一覧を書いても、この検査は変異の判定に混ざらない。
"""

from pathlib import Path

import pytest

MUTATION_DIR = Path(__file__).resolve().parents[2] / "scripts" / "mutation"

#: 台本が隣にあれば読む一覧（`backend/scripts/mutation/plan.py: BASELINE`・`backend/scripts/mutation/runner.py: RECHECK_FILE`と、
#: plan.pyが同じ並びで読む`only.txt`）。
LISTS = ("only.txt", "recheck.txt", "baseline.txt")


@pytest.mark.parametrize("name", LISTS)
def test_no_mutation_list_is_checked_in(name):
    assert not (MUTATION_DIR / name).exists(), (
        f"backend/scripts/mutation/{name} が残っている。一覧の口は測りに渡す作業ブランチでだけ置き、Pull Request の前に消す"
    )
