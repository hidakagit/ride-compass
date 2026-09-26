"""`domain/difficulty.py`——軸の得点を1区間へ合成する加重平均と、区間をルート1本へまとめる距離加重の集約。

ここで見ないもの:
- どのフィールドをどの集約で作るか（ルート候補への配線） → `test_route_generator.py`
- 区間を約500m単位へ畳むときの丸め方の使い分け → `test_route.py`

値が無い（None・NaN）ものは分母にも入れず、残りで割り直す。軸の合成と内訳は配列版1本
（区間1本も長さ1で通す）、距離加重平均はPythonの値の並びと配列の2本がそれぞれ持つので、入口ごとに見る。
"""

import numpy as np
import pytest

from app.domain import difficulty

# ---- 軸の得点の合成（区間1本） ----


def _composite(scored_weights):
    """(得点, 重み)の並びを、軸id→得点・軸id→重みにして合成する。"""
    scores = {f"axis{i}": score for i, (score, _) in enumerate(scored_weights)}
    weights = {f"axis{i}": weight for i, (_, weight) in enumerate(scored_weights)}
    composite, contributions = difficulty.composite_difficulty(scores, weights)
    return composite, list(contributions.values())


def test_composite_is_the_weighted_mean_of_axes_that_have_a_score():
    # (10×1 + 40×2) / 3。得点の無い軸は重みごと外す
    assert _composite([(10.0, 1.0), (None, 5.0), (40.0, 2.0)])[0] == 30.0


def test_composite_is_rounded_to_one_decimal():
    assert _composite([(10.0, 1.0), (20.0, 2.0)])[0] == 16.7


@pytest.mark.parametrize(
    "scored_weights",
    [
        [],
        [(None, 1.0), (None, 2.0)],
        # 得点はあるが重みが全部0（利用者が全軸の重みを0にした）
        [(10.0, 0.0), (20.0, 0.0)],
    ],
)
def test_composite_is_missing_when_nothing_can_be_averaged(scored_weights):
    assert _composite(scored_weights)[0] is None


def test_contributions_split_the_composite_per_axis_in_the_same_order():
    contributions = _composite([(10.0, 1.0), (None, 5.0), (40.0, 2.0)])[1]

    # 得点の無い軸は合成の分母にも入らないので、内訳もNone
    assert contributions == [3.3, None, 26.7]
    assert sum(c for c in contributions if c is not None) == pytest.approx(30.0)


@pytest.mark.parametrize(
    "scored_weights",
    [[(None, 1.0), (None, 2.0)], [(10.0, 0.0), (20.0, 0.0)]],
)
def test_contributions_are_all_missing_when_the_composite_is(scored_weights):
    assert _composite(scored_weights)[1] == [None, None]


def test_the_composite_leaves_out_an_axis_only_where_it_has_no_score():
    """区間ごとに欠損の軸が違っても、その区間で得点のある軸の重みだけで割る。"""
    axis_arrays = {"a": np.array([10.0, 10.0]), "b": np.array([40.0, np.nan])}

    composite, weight_sums = difficulty.composite_difficulty_array(axis_arrays, {"a": 1.0, "b": 2.0}, 2)

    assert composite.tolist() == [30.0, 10.0]
    assert weight_sums.tolist() == [3.0, 1.0]


def test_precomputed_sums_of_the_other_axes_give_the_same_composite():
    """時刻で変わらない軸の和を先に求めて渡しても、全軸を一度に合成したのと同じ値になる。"""
    fixed = {"a": np.array([10.0, np.nan])}
    varying = {"b": np.array([40.0, 25.0])}
    weights = {"a": 1.0, "b": 2.0}

    split = difficulty.composite_difficulty_array(
        varying, weights, 2, static_sums=difficulty.axis_weighted_sums(fixed, weights, 2)
    )
    whole = difficulty.composite_difficulty_array({**fixed, **varying}, weights, 2)

    assert split[0].tolist() == whole[0].tolist() == [30.0, 25.0]


# ---- 区間からルート1本への距離加重 ----


def test_distance_weighted_mean_skips_segments_without_a_value_and_is_not_rounded():
    mean = difficulty.weighted_mean_by_distance([(10.0, 1.0), (None, 9.0), (20.0, 2.0)])

    assert mean == pytest.approx(50.0 / 3)


@pytest.mark.parametrize(
    "segments",
    [
        [],
        [(None, 1.0)],
        # 値はあるが長さの無い区間だけ
        [(10.0, 0.0)],
    ],
)
def test_distance_weighted_mean_is_missing_when_nothing_can_be_averaged(segments):
    assert difficulty.weighted_mean_by_distance(segments) is None


def test_distance_weighted_difficulty_is_rounded_to_one_decimal():
    assert difficulty.distance_weighted_difficulty([(10.0, 1.0), (20.0, 2.0)]) == 16.7


def test_distance_weighted_difficulty_is_missing_when_no_segment_has_one():
    assert difficulty.distance_weighted_difficulty([(None, 1.0)]) is None


def test_difficulty_load_multiplies_the_average_by_the_whole_route_length():
    # 平均は値のある区間だけの30.0。掛けるのは値の無い区間も含めた全長4km——
    # 値の無い区間を飛ばすと、データの無い区間が多いルートほど総量が小さく見える
    assert difficulty.difficulty_load([(10.0, 1.0), (None, 1.0), (40.0, 2.0)]) == 120.0


def test_difficulty_load_uses_the_displayed_average():
    # 平均は小数1桁（16.7）へ丸めてから掛ける——画面の「平均×距離」と一致させる
    assert difficulty.difficulty_load([(10.0, 1.0), (20.0, 2.0)]) == 50.1


def test_difficulty_load_is_missing_when_the_average_is():
    assert difficulty.difficulty_load([(None, 1.0), (None, 2.0)]) is None


# ---- 配列版（bbox全体の区間） ----


def test_array_mean_skips_nan_and_is_rounded_to_one_decimal():
    values = np.array([10.0, np.nan, 20.0])
    distance_m = np.array([1000.0, 9000.0, 2000.0])

    assert difficulty.distance_weighted_difficulty_array(values, distance_m) == 16.7


@pytest.mark.parametrize(
    ("values", "distance_m"),
    [
        ([np.nan, np.nan], [1000.0, 2000.0]),
        ([10.0, 20.0], [0.0, 0.0]),
    ],
)
def test_array_mean_is_missing_when_nothing_can_be_averaged(values, distance_m):
    assert difficulty.distance_weighted_difficulty_array(np.array(values), np.array(distance_m)) is None
