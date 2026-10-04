"""`tests/axis_system_fixture.py`——テストの間だけ`AXIS_DEFINITIONS`を差し替える。

ブロックを抜けても戻らないと、差し替えた軸が後のテストへ漏れ、実行順しだいで結果が変わる。

ここで見ないもの: `axis_definition`（型を満たす値を並べるだけ）
"""

from contextlib import nullcontext

import pytest

from app.domain.axis_definitions import AXIS_DEFINITIONS
from tests.axis_system_fixture import axis_definition, replaced_axis_definitions


@pytest.mark.parametrize("fails", [False, True])
def test_the_axes_are_only_the_given_ones_inside_the_block_and_the_original_ones_after_it(fails):
    before = dict(AXIS_DEFINITIONS)
    original = {"kept": axis_definition("kept")}
    given = {"given": axis_definition("given")}
    AXIS_DEFINITIONS.update(original)
    try:
        with pytest.raises(RuntimeError) if fails else nullcontext():
            with replaced_axis_definitions(given):
                assert AXIS_DEFINITIONS == given
                if fails:
                    raise RuntimeError

        assert AXIS_DEFINITIONS == {**before, **original}
    finally:
        AXIS_DEFINITIONS.clear()
        AXIS_DEFINITIONS.update(before)
