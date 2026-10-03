"""`domain/difficulty.py`——軸の得点を合成した難易度と、区間からルートへの集約。

入口は丸め（`round_difficulty`・`round_difficulty_array`）、合成（`composite_difficulty_array`・
`axis_weighted_sums`・`axis_contributions_at_row`・`composite_difficulty`）、重みの割合（`weight_share`）、
距離での集約（`weighted_mean_by_distance`・`distance_weighted_difficulty`・`overall_difficulty`・
`distance_weighted_difficulty_array`）。同じ計算を持つ2つの道（スカラーと配列・先に和を求めるかどうか）は、
同じ入力で同じ答えになることを確かめる。

期待値は素直な計算（Pythonの`round`・重み付き平均）から作る。性質の入力は、和と商が2進で正確に求まる
整数の得点・重み・距離にする——実数の乱数では、計算の順序の違いが丸めの境界をまたいだかどうかを見分けられない。

ここで見ないもの:
- 軸の得点そのもの → `test_axis_definitions.py`
- 候補を難易度で並べること → `test_route_generator.py`
"""

import math

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.difficulty import (
    axis_contributions_at_row,
    axis_weighted_sums,
    composite_difficulty,
    composite_difficulty_array,
    distance_weighted_difficulty,
    distance_weighted_difficulty_array,
    overall_difficulty,
    round_difficulty,
    round_difficulty_array,
    weight_share,
    weighted_mean_by_distance,
)

# 丸めの中点に乗る値（×10がちょうど.5）。2進で正確に表せる中点（0.25等）と表せない中点（0.15等）の両方を含む。
_on_a_midpoint = st.integers(min_value=-200_000, max_value=200_000).map(lambda n: (2 * n + 1) / 20)
# 丸めた得点を重み0.5ずつで足した値。合成でよく現れる。
_half_of_rounded_sum = st.tuples(
    st.integers(min_value=0, max_value=1000), st.integers(min_value=0, max_value=1000)
).map(lambda pair: pair[0] / 10 * 0.5 + pair[1] / 10 * 0.5)
_any_value = st.floats(min_value=-1e6, max_value=1e6)


@given(values=st.lists(st.one_of(_on_a_midpoint, _half_of_rounded_sum, _any_value), min_size=1, max_size=30))
def test_rounding_an_array_agrees_with_rounding_each_value(values):
    """配列で丸めた区間と1つずつ丸めた値が食い違うと、同じ難易度の候補の並びが経路によって変わる。"""
    rounded = round_difficulty_array(np.array(values))

    assert rounded.tolist() == [round_difficulty(value) for value in values]


def test_rounding_keeps_a_missing_value_missing():
    assert math.isnan(round_difficulty_array(np.array([math.nan, 1.25]))[0])


def test_the_share_of_a_weight_is_taken_from_the_sum_of_all_weights():
    assert weight_share(1.0, [1.0, 2.0]) == 0.25
    assert weight_share(0.0, [0.0, 0.0]) is None


_scores = st.one_of(st.integers(min_value=0, max_value=100).map(float), st.just(math.nan))
_weights = st.integers(min_value=0, max_value=5).map(float)


@st.composite
def _axes(draw):
    """区間の数・軸ごとの得点（欠損あり）・重み。重みを持たない軸も混ぜる。"""
    length = draw(st.integers(min_value=1, max_value=8))
    count = draw(st.integers(min_value=0, max_value=5))
    arrays = {
        f"axis_{i}": np.array(draw(st.lists(_scores, min_size=length, max_size=length))) for i in range(count)
    }
    weights = {axis_id: draw(_weights) for axis_id in arrays if draw(st.booleans())}
    return length, arrays, weights


def _mean_of_axes_with_data(arrays, weights, row) -> float:
    scored = [(weights.get(a, 0.0), arr[row]) for a, arr in arrays.items() if not math.isnan(arr[row])]
    total = sum(w for w, _ in scored)
    return math.nan if total == 0 else sum(w * s for w, s in scored) / total


@given(axes=_axes())
def test_the_composite_is_the_mean_of_the_axes_with_data_weighted_and_rounded(axes):
    """欠損の軸はその区間だけ分母からも外し、データのある軸の重みで割り直す。重みの無い軸は数えない。"""
    length, arrays, weights = axes

    composite, weight_sums = composite_difficulty_array(arrays, weights, length)

    expected = [_mean_of_axes_with_data(arrays, weights, row) for row in range(length)]
    np.testing.assert_array_equal(composite, [value if math.isnan(value) else round(value, 1) for value in expected])
    assert weight_sums.tolist() == [
        sum(weights.get(a, 0.0) for a, arr in arrays.items() if not math.isnan(arr[row])) for row in range(length)
    ]


@given(axes=_axes(), data=st.data())
def test_summing_some_axes_first_gives_the_same_composite(axes, data):
    """変わらない軸の和を先に求めて使い回す合成は、全軸をまとめて合成したものと一致する。"""
    length, arrays, weights = axes
    first = data.draw(st.sets(st.sampled_from(sorted(arrays))) if arrays else st.just(set()))

    whole = composite_difficulty_array(arrays, weights, length)
    static_sums = axis_weighted_sums({a: arrays[a] for a in first}, weights, length)
    split = composite_difficulty_array({a: v for a, v in arrays.items() if a not in first}, weights, length, static_sums)

    np.testing.assert_array_equal(split[0], whole[0])
    np.testing.assert_array_equal(split[1], whole[1])


@given(axes=_axes(), data=st.data())
def test_the_contributions_of_a_row_add_up_to_its_unrounded_composite(axes, data):
    length, arrays, weights = axes
    row = data.draw(st.integers(min_value=0, max_value=length - 1))
    _, weight_sums = composite_difficulty_array(arrays, weights, length)

    contributions = axis_contributions_at_row(arrays, weights, weight_sums, row)

    mean = _mean_of_axes_with_data(arrays, weights, row)
    if math.isnan(mean):
        assert contributions == {}
    else:
        assert set(contributions) == {a for a, arr in arrays.items() if not math.isnan(arr[row])}
        assert sum(contributions.values()) == pytest.approx(mean)


def test_a_segment_composite_names_every_axis_and_leaves_axes_without_a_score_empty():
    composite, contributions = composite_difficulty({"a": 33.0, "b": None, "c": 66.0}, {"a": 1.0, "b": 5.0, "c": 2.0})

    assert composite == 55.0
    assert contributions == {"a": 11.0, "b": None, "c": 44.0}


def test_contributions_of_a_segment_are_rounded_and_may_not_add_up_to_the_composite():
    composite, contributions = composite_difficulty({"a": 1.0, "b": 1.0, "c": 1.0}, {"a": 1.0, "b": 1.0, "c": 1.0})

    assert composite == 1.0
    assert contributions == {"a": 0.3, "b": 0.3, "c": 0.3}


@pytest.mark.parametrize(
    ("scores", "weights"),
    [({"a": None}, {"a": 1.0}), ({"a": 50.0}, {"a": 0.0}), ({}, {})],
    ids=["得点が無い", "重みの合計が0", "軸が無い"],
)
def test_a_segment_without_a_composite_has_no_contributions(scores, weights):
    assert composite_difficulty(scores, weights) == (None, {axis_id: None for axis_id in scores})


def test_the_mean_by_distance_skips_segments_without_a_value_and_is_not_rounded():
    assert weighted_mean_by_distance([(10.0, 1.0), (None, 5.0), (20.0, 2.0)]) == pytest.approx(50.0 / 3.0)


@pytest.mark.parametrize(
    "segments",
    [[], [(None, 1.0)], [(10.0, 0.0), (None, 3.0)]],
    ids=["区間が無い", "値が無い", "値のある区間の距離が0"],
)
def test_the_mean_by_distance_is_missing_without_a_measured_distance(segments):
    assert weighted_mean_by_distance(segments) is None
    assert distance_weighted_difficulty(segments) is None
    assert overall_difficulty(segments) is None


def test_the_difficulty_by_distance_is_rounded():
    assert distance_weighted_difficulty([(10.0, 1.0), (20.0, 2.0)]) == 16.7


def test_the_load_of_a_route_is_its_rounded_average_over_every_segment_including_those_without_a_value():
    """欠損の区間を飛ばして積むと、データの無い区間が多いルートほど楽に見える。"""
    overall = overall_difficulty([(10.0, 1.0), (None, 1.0), (20.0, 2.0)])

    assert overall is not None
    # 平均 50/3 は 16.7 に丸め、総量はその 16.7 に全区間の 4km を掛ける（丸める前の平均なら 66.7）。
    assert (overall.average, overall.load) == (16.7, 66.8)


_segments = st.lists(
    st.tuples(
        st.one_of(st.integers(min_value=0, max_value=100).map(float), st.none()),
        st.integers(min_value=0, max_value=5000).map(float),
    ),
    max_size=20,
)


@given(segments=_segments)
def test_the_array_difficulty_by_distance_agrees_with_the_list(segments):
    """ルート全体（区間の並び）と探索範囲の配列（区間の配列）で、同じ区間から同じ難易度になる。"""
    difficulty = np.array([math.nan if value is None else value for value, _ in segments], dtype=float)
    distance = np.array([distance for _, distance in segments], dtype=float)

    assert distance_weighted_difficulty_array(difficulty, distance) == distance_weighted_difficulty(segments)
