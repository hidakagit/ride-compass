"""`scripts/measure_axis_saturation.py`の集計（延長で重み付けた分位点・上端下端の割合）。

DBアクセスを伴う部分は軸スタジオの分布プレビューと同じ経路のため、ここでは
「本数ではなく延長で重み付ける」という本質だけを固定する。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from measure_axis_saturation import (  # noqa: E402
    share_at_or_above,
    share_at_or_below,
    weighted_quantiles,
)


def test_quantiles_weight_by_length_not_by_way_count():
    """短い道が何本あっても、長い道1本の値が中央値を決める。

    本数で数えると「細い路地が大多数だから軸は効いている」と読み違える——実際に走る
    距離のほとんどが1本の幹線なら、その値がルート選択を支配する。
    """
    pairs = [(10.0, 0.0), (10.0, 0.0), (10.0, 0.0), (10_000.0, 100.0)]

    assert weighted_quantiles(pairs)["p50"] == 100.0


def test_quantiles_fill_the_upper_tail_with_the_largest_value():
    """累積が最後の要素で打ち切られても、上側の分位点が欠けない。"""
    result = weighted_quantiles([(1.0, 3.0), (1.0, 7.0)])

    assert set(result) == {"p10", "p50", "p90", "p99"}
    assert result["p99"] == 7.0


def test_quantiles_of_an_empty_sample_are_empty():
    assert weighted_quantiles([]) == {}


def test_shares_are_measured_in_length_and_are_inclusive_of_the_threshold():
    # 延長1kmが100、延長3kmが0。本数では半々だが、延長では上端25%・下端75%。
    pairs = [(1000.0, 100.0), (3000.0, 0.0)]

    assert share_at_or_above(pairs, 95.0) == 0.25
    assert share_at_or_below(pairs, 5.0) == 0.75
    # しきい値ちょうどを含める（「95以上」の定義どおり）。
    assert share_at_or_above([(1.0, 95.0)], 95.0) == 1.0
    assert share_at_or_below([(1.0, 5.0)], 5.0) == 1.0


def test_shares_of_an_empty_sample_are_zero_not_a_division_error():
    assert share_at_or_above([], 95.0) == 0.0
    assert share_at_or_below([], 5.0) == 0.0
