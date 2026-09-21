"""`domain/difficulty.py`——軸ごとの得点と区間ごとの値を、1つの数へ畳む。

ここで見るのは**畳み方**だけ。軸そのものの評価（折れ点補間・欠損の扱い）は
`test_axis_definitions.py`が持つ。
"""

import numpy as np

from app.domain.difficulty import (
    composite_contributions,
    composite_difficulty,
    difficulty_load,
    distance_weighted_difficulty,
    distance_weighted_difficulty_array,
    weighted_mean_by_distance,
)


class TestCompositeDifficulty:
    """(得点, 重み)を加重平均へ畳む。"""

    def test_weights_each_score(self):
        assert composite_difficulty([(0.0, 1.0), (100.0, 3.0)]) == 75.0

    def test_missing_scores_leave_the_denominator(self):
        """欠損した軸は分子からも分母からも抜ける——残りの重みで割り直す。"""
        assert composite_difficulty([(40.0, 1.0), (None, 9.0)]) == 40.0

    def test_no_usable_score_is_none(self):
        assert composite_difficulty([(None, 1.0)]) is None
        assert composite_difficulty([]) is None

    def test_zero_total_weight_is_none(self):
        """得点があっても、重みが全て0なら割れない。0点へ倒さない。"""
        assert composite_difficulty([(50.0, 0.0), (80.0, 0.0)]) is None

    def test_rounds_to_one_decimal(self):
        assert composite_difficulty([(0.0, 1.0), (100.0, 2.0)]) == 66.7


class TestCompositeContributions:
    """加重平均を軸ごとへ分解する。画面の内訳バーがこれを積む。"""

    def test_keeps_the_input_order_and_length(self):
        """入力と同じ並び・同じ長さで返す——呼び出し側が軸と位置で対応づける。"""
        assert composite_contributions([(0.0, 1.0), (None, 2.0), (100.0, 1.0)]) == [0.0, None, 50.0]

    def test_shares_the_denominator_with_the_composite(self):
        """合成と同じ分母で割る。別々に正規化すると内訳が合成と桁で食い違う。"""
        scored = [(40.0, 1.0), (80.0, 3.0)]

        assert sum(c for c in composite_contributions(scored) if c is not None) == composite_difficulty(scored)

    def test_unevaluable_composite_makes_every_contribution_none(self):
        assert composite_contributions([(None, 1.0), (None, 2.0)]) == [None, None]
        assert composite_contributions([(50.0, 0.0)]) == [None]


class TestWeightedMeanByDistance:
    """区間の値を距離で加重平均する。**丸めない**。"""

    def test_does_not_round(self):
        """丸めは呼び出し側が決める——桁の小さい軸の生値が潰れるため。"""
        assert weighted_mean_by_distance([(0.0, 1.0), (100.0, 2.0)]) == 200.0 / 3.0

    def test_missing_values_leave_the_denominator(self):
        assert weighted_mean_by_distance([(40.0, 1.0), (None, 9.0)]) == 40.0

    def test_no_usable_value_or_no_distance_is_none(self):
        assert weighted_mean_by_distance([(None, 1.0)]) is None
        assert weighted_mean_by_distance([(50.0, 0.0)]) is None
        assert weighted_mean_by_distance([]) is None


class TestDistanceWeightedDifficulty:
    """`weighted_mean_by_distance`を0〜100の得点向けに小数1桁へ丸めたもの。"""

    def test_rounds_the_weighted_mean(self):
        assert distance_weighted_difficulty([(0.0, 1.0), (100.0, 2.0)]) == 66.7

    def test_longer_segments_pull_harder(self):
        assert distance_weighted_difficulty([(0.0, 9.0), (100.0, 1.0)]) == 10.0

    def test_missing_values_leave_the_denominator(self):
        assert distance_weighted_difficulty([(40.0, 1.0), (None, 9.0)]) == 40.0

    def test_no_usable_value_or_no_distance_is_none(self):
        assert distance_weighted_difficulty([(None, 1.0)]) is None
        assert distance_weighted_difficulty([(50.0, 0.0)]) is None
        assert distance_weighted_difficulty([]) is None


class TestDifficultyLoad:
    """総量。距離で割らないので、伸ばせばそのまま増える。"""

    def test_grows_with_distance_at_the_same_average(self):
        short = difficulty_load([(50.0, 2.0)])
        long = difficulty_load([(50.0, 4.0)])

        assert long == 2 * short

    def test_a_detour_that_lowers_the_average_still_costs_more(self):
        """平均を下げる遠回りでも、総量では不利に出る。"""
        direct = difficulty_load([(80.0, 2.0)])
        detour = difficulty_load([(80.0, 2.0), (10.0, 3.0)])

        assert detour > direct

    def test_missing_segments_keep_their_distance_in_the_total(self):
        """欠損区間は平均の計算からは抜けるが、**総量の距離には残る**。
        飛ばすと「データが無い区間が多いほど総量が小さい」ことになり、欠損の多い
        ルートが有利に見えてしまう。"""
        assert difficulty_load([(50.0, 2.0), (None, 2.0)]) == 50.0 * 4.0

    def test_no_usable_value_or_no_distance_is_none(self):
        assert difficulty_load([(None, 1.0)]) is None
        assert difficulty_load([(50.0, 0.0)]) is None
        assert difficulty_load([]) is None


class TestDistanceWeightedDifficultyArray:
    """`distance_weighted_difficulty`のnumpy版。欠損はNaNで表す。"""

    def test_matches_the_scalar_version(self):
        segments = [(0.0, 1.0), (100.0, 2.0)]
        array = distance_weighted_difficulty_array(
            np.array([s for s, _ in segments]), np.array([d for _, d in segments])
        )

        assert array == distance_weighted_difficulty(segments)

    def test_nan_elements_leave_the_denominator(self):
        assert distance_weighted_difficulty_array(np.array([40.0, np.nan]), np.array([1.0, 9.0])) == 40.0

    def test_no_usable_element_or_no_distance_is_none(self):
        assert distance_weighted_difficulty_array(np.array([np.nan]), np.array([1.0])) is None
        assert distance_weighted_difficulty_array(np.array([50.0]), np.array([0.0])) is None
        assert distance_weighted_difficulty_array(np.array([]), np.array([])) is None
