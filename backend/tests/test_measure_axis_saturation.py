"""`scripts/measure_axis_saturation.py`の集計（上端下端の割合・張り付きの原因・最多の値の割合）。

ここで見ないもの:
- 延長で重み付けた分位点と標本の作り方 → `test_value_distribution.py`（軸スタジオの分布プレビューと共有する実装）
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from measure_axis_saturation import (
    largest_single_input_share,
    saturation_cause,
    share_at_or_above,
    share_at_or_below,
)


def test_shares_are_measured_in_length_and_are_inclusive_of_the_threshold():
    # 延長1kmが100、延長3kmが0。本数では半々だが、延長では上端25%・下端75%。
    pairs = [(1000.0, 100.0), (3000.0, 0.0)]

    assert share_at_or_above(pairs, 95.0) == 0.25
    assert share_at_or_below(pairs, 5.0) == 0.75
    # しきい値ちょうどを含める（「95以上」の定義どおり）。
    assert share_at_or_above([(1.0, 95.0)], 95.0) == 1.0
    assert share_at_or_below([(1.0, 5.0)], 5.0) == 1.0


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        pytest.param([(1000.0, 100.0, 9.0), (1000.0, 50.0, 5.0), (1000.0, 0.0, 0.0)], None, id="not_saturated"),
        # 異なる生値が上端で100へ潰れている。折れ点の最終区間を広げれば散る。
        pytest.param([(1000.0, 100.0, 12.0), (1000.0, 100.0, 15.0), (1000.0, 100.0, 30.0), (1000.0, 20.0, 2.0)],
                     "breakpoints", id="top_spread"),
        # 張り付いた道がすべて同じ生値なら、どの折れ点でも同じ難易度になる。
        pytest.param([(9700.0, 100.0, 0.0), (300.0, 0.0, -4.0)], "single_value", id="top_one_value"),
        pytest.param([(9500.0, 0.0, 0.0), (500.0, 60.0, 6.0)], "single_value", id="bottom_one_value"),
    ],
)
def test_the_cause_of_saturation(rows, expected):
    assert saturation_cause(rows) == expected


def test_the_largest_single_value_is_measured_in_length_among_all_evaluated_ways():
    # 値"a"は本数では1本だが延長で最多。対応表の軸の値（文字列）もそのまままとめる。
    rows = [(3000.0, 0.0, "a"), (500.0, 0.0, "b"), (500.0, 0.0, "b"), (1000.0, 40.0, "c")]

    assert largest_single_input_share(rows) == 0.6
    assert largest_single_input_share(rows, lambda score: score >= 40.0) == 0.2
