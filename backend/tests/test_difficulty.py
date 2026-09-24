"""`domain/difficulty.py`——軸の得点を1区間へ合成する加重平均と、区間をルート1本へまとめる距離加重の集約。

ここで見ないもの:
- どのフィールドをどの集約で作るか（ルート候補への配線） → `test_route_generator.py`
- 区間を約500m単位へ畳むときの丸め方の使い分け → `test_route.py`

値が無い（None・NaN）ものは分母にも入れず、残りで割り直す——この規則は4つの入口
（軸の合成・内訳・距離加重平均・その配列版）がそれぞれ持つので、入口ごとに見る。
"""

import numpy as np
import pytest

from app.domain import difficulty

# ---- 軸の得点の合成（区間1本） ----


def test_composite_is_the_weighted_mean_of_axes_that_have_a_score():
    # (10×1 + 40×2) / 3。得点の無い軸は重みごと外す
    assert difficulty.composite_difficulty([(10.0, 1.0), (None, 5.0), (40.0, 2.0)]) == 30.0


def test_composite_is_rounded_to_one_decimal():
    assert difficulty.composite_difficulty([(10.0, 1.0), (20.0, 2.0)]) == 16.7


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
    assert difficulty.composite_difficulty(scored_weights) is None


def test_contributions_split_the_composite_per_axis_in_the_same_order():
    contributions = difficulty.composite_contributions([(10.0, 1.0), (None, 5.0), (40.0, 2.0)])

    # 得点の無い軸は合成の分母にも入らないので、内訳もNone
    assert contributions == [3.3, None, 26.7]
    assert sum(c for c in contributions if c is not None) == pytest.approx(30.0)


@pytest.mark.parametrize(
    "scored_weights",
    [[(None, 1.0), (None, 2.0)], [(10.0, 0.0), (20.0, 0.0)]],
)
def test_contributions_are_all_missing_when_the_composite_is(scored_weights):
    assert difficulty.composite_contributions(scored_weights) == [None, None]


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
