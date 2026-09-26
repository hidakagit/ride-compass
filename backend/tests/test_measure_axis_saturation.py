"""`scripts/measure_axis_saturation.py`の集計（延長で重み付けた分位点・上端下端の割合・張り付きの原因）。

DBアクセスを伴う部分は軸スタジオの分布プレビューと同じ経路のため、ここでは
「本数ではなく延長で重み付ける」という本質だけを固定する。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from app.services.axis_preview_service import weighted_quantiles  # noqa: E402
from measure_axis_saturation import (  # noqa: E402
    _QUANTILES,
    largest_single_input_share,
    saturation_cause,
    share_at_or_above,
    share_at_or_below,
)


def _quantiles(pairs):
    """このスクリプトが使う目標・丸め桁での分位点（共有実装を通す）。"""
    return weighted_quantiles(pairs, _QUANTILES, digits=1)


def test_quantiles_weight_by_length_not_by_way_count():
    """短い道が何本あっても、長い道1本の値が中央値を決める。

    本数で数えると「細い路地が大多数だから軸は効いている」と読み違える——実際に走る
    距離のほとんどが1本の幹線なら、その値がルート選択を支配する。
    """
    pairs = [(10.0, 0.0), (10.0, 0.0), (10.0, 0.0), (10_000.0, 100.0)]

    assert _quantiles(pairs)["p50"] == 100.0


def test_quantiles_fill_the_upper_tail_with_the_largest_value():
    """累積が最後の要素で打ち切られても、上側の分位点が欠けない。"""
    result = _quantiles([(1.0, 3.0), (1.0, 7.0)])

    assert result["p99"] == 7.0


def test_quantiles_of_an_empty_sample_are_empty():
    assert _quantiles([]) == {}


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
    assert largest_single_input_share([]) == 0.0


def test_an_axis_that_is_not_saturated_has_no_cause():
    rows = [(1000.0, 100.0, 9.0), (1000.0, 50.0, 5.0), (1000.0, 0.0, 0.0)]

    assert saturation_cause(rows) is None


def test_distinct_raw_values_clamped_at_the_top_are_a_breakpoint_problem():
    """異なる生値が上端で100へ潰れている。折れ点の最終区間を広げれば散る。"""
    rows = [(1000.0, 100.0, 12.0), (1000.0, 100.0, 15.0), (1000.0, 100.0, 30.0), (1000.0, 20.0, 2.0)]

    assert saturation_cause(rows) == "breakpoints"


def test_a_top_made_of_one_raw_value_cannot_be_spread_by_breakpoints():
    """張り付いた道がすべて同じ生値なら、どの折れ点でも同じ難易度になる。"""
    rows = [(9700.0, 100.0, 0.0), (300.0, 0.0, -4.0)]

    assert saturation_cause(rows) == "single_value"


def test_the_bottom_is_judged_by_the_same_rule():
    one_value = [(9500.0, 0.0, 0.0), (500.0, 60.0, 6.0)]
    spread = [(3200.0, 0.0, 0.1), (3200.0, 0.0, 0.2), (3100.0, 0.0, 0.3), (500.0, 60.0, 6.0)]

    assert saturation_cause(one_value) == "single_value"
    assert saturation_cause(spread) == "breakpoints"


def test_the_largest_single_value_is_measured_in_length_among_all_evaluated_ways():
    # 値"a"は本数では1本だが延長で最多。対応表の軸の値（文字列）もそのまままとめる。
    rows = [(3000.0, 0.0, "a"), (500.0, 0.0, "b"), (500.0, 0.0, "b"), (1000.0, 40.0, "c")]

    assert largest_single_input_share(rows) == 0.6
    assert largest_single_input_share(rows, lambda score: score >= 40.0) == 0.2
