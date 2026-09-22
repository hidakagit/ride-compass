"""`domain/axis_templates.py`——評価軸が還元される2つのプリミティブと、配列版の丸め。

**スカラー経路とベクトル経路で同じ答えになる**ことがここの要。
"""

import numpy as np
import pytest

from app.domain.axis_templates import evaluate_breakpoint_linear, evaluate_categorical, round1_array

LINE = [(0.0, 0.0), (10.0, 100.0)]


class TestEvaluateBreakpointLinear:

    def test_a_value_between_breakpoints_is_interpolated(self):
        assert evaluate_breakpoint_linear(2.5, LINE) == 25.0

    def test_values_outside_the_range_clamp_to_the_declared_ends(self):
        """0・100ではなく、宣言した端の値で止まる。"""
        line = [(0.0, 10.0), (10.0, 50.0)]

        assert evaluate_breakpoint_linear(-5.0, line) == 10.0
        assert evaluate_breakpoint_linear(99.0, line) == 50.0

    def test_a_scalar_comes_back_as_a_plain_float(self):
        """numpyのスカラーで返すと、呼び出し側のJSON化・比較で型が揺れる。"""
        result = evaluate_breakpoint_linear(2.5, LINE)

        assert type(result) is float

    def test_an_array_comes_back_as_an_array(self):
        result = evaluate_breakpoint_linear(np.array([0.0, 2.5, 10.0]), LINE)

        assert isinstance(result, np.ndarray)
        assert result.tolist() == [0.0, 25.0, 100.0]

    def test_a_missing_element_stays_missing(self):
        """欠損が「最良」の点数に化ける。"""
        result = evaluate_breakpoint_linear(np.array([np.nan, 2.5]), LINE)

        assert np.isnan(result[0])
        assert result[1] == 25.0

    def test_both_paths_agree(self):
        values = [-1.0, 0.0, 3.3, 10.0, 12.0]
        scalar = [evaluate_breakpoint_linear(v, LINE) for v in values]

        assert evaluate_breakpoint_linear(np.array(values), LINE).tolist() == scalar

    def test_a_single_breakpoint_returns_that_value_everywhere(self):
        assert evaluate_breakpoint_linear(5.0, [(1.0, 42.0)]) == 42.0


class TestEvaluateCategorical:

    BOOL_MAP = {True: 0.0, False: 80.0}
    STR_MAP = {"a": 1.0, "b": 2.0, "c": 3.0}

    def test_a_scalar_is_looked_up_in_the_table(self):
        assert evaluate_categorical(True, self.BOOL_MAP) == 0.0
        assert evaluate_categorical("b", self.STR_MAP) == 2.0

    def test_a_scalar_that_is_not_in_the_table_falls_back(self):
        assert evaluate_categorical("zzz", self.STR_MAP) is None
        assert evaluate_categorical("zzz", self.STR_MAP, default=9.0) == 9.0

    def test_an_array_is_looked_up_element_by_element(self):
        result = evaluate_categorical(np.array(["a", "c", "b"], dtype=object), self.STR_MAP)

        assert result.tolist() == [1.0, 3.0, 2.0]

    def test_boolean_arrays_are_looked_up_too(self):
        result = evaluate_categorical(np.array([True, False]), self.BOOL_MAP)

        assert result.tolist() == [0.0, 80.0]

    def test_an_unlisted_value_falls_back(self):
        """未登録値を0（最良）へ倒さない。倒すと、評価できない道が最良の色で塗られる。"""
        result = evaluate_categorical(np.array(["a", "zzz"], dtype=object), self.STR_MAP)

        assert result[0] == 1.0
        assert np.isnan(result[1])

    def test_a_missing_element_falls_back_even_when_it_looks_like_the_first_key(self):
        """差し替えの痕跡が残ると、欠損が先頭キーの点数を受け取る。"""
        result = evaluate_categorical(np.array([None, "a"], dtype=object), self.STR_MAP)

        assert np.isnan(result[0])
        assert result[1] == 1.0

    def test_a_missing_element_uses_the_given_default(self):
        result = evaluate_categorical(np.array([None], dtype=object), self.STR_MAP, default=7.0)

        assert result.tolist() == [7.0]

    def test_an_empty_table_falls_back_for_every_element(self):
        """キーが1つも無いと二分探索の配列が作れない。先に倒す。"""
        result = evaluate_categorical(np.array(["a", "b"], dtype=object), {}, default=5.0)

        assert result.tolist() == [5.0, 5.0]

        assert np.isnan(evaluate_categorical(np.array(["a"], dtype=object), {})).all()

    def test_both_paths_agree(self):
        values = ["a", "c", "zzz"]
        scalar = [evaluate_categorical(v, self.STR_MAP, default=-1.0) for v in values]

        result = evaluate_categorical(np.array(values, dtype=object), self.STR_MAP, default=-1.0)

        assert result.tolist() == scalar

    def test_a_numeric_array_propagates_its_missing_marker(self):
        """片方だけ扱うと、もう片方が「一致しない値」として既定へ倒れる。"""
        result = evaluate_categorical(np.array([1.0, 0.0, np.nan]), {1.0: 0.0, 0.0: 80.0})

        assert result[0] == 0.0
        assert result[1] == 80.0
        assert np.isnan(result[2])

    def test_many_keys_are_still_looked_up_correctly(self):
        """走査から二分探索へ置き換えたときに、並び順の取り違えが起きやすい。"""
        mapping = {f"k{i:03d}": float(i) for i in range(200)}
        picks = ["k000", "k117", "k199"]

        result = evaluate_categorical(np.array(picks, dtype=object), mapping)

        assert result.tolist() == [0.0, 117.0, 199.0]


class TestRound1Array:

    def test_it_rounds_to_one_decimal(self):
        assert round1_array(np.array([1.04, 1.06, -2.34])).tolist() == [1.0, 1.1, -2.3]

    def test_it_matches_the_builtin_on_exact_halves(self):
        values = [0.05, 0.15, 0.25, 0.35, 0.45, 2.55, -0.05, -0.15]

        result = round1_array(np.array(values))

        assert result.tolist() == [round(v, 1) for v in values]

    def test_it_matches_the_builtin_on_ordinary_values(self):
        values = [0.0, 1.2345, -9.8765, 123.456, 1e-9]

        assert round1_array(np.array(values)).tolist() == [round(v, 1) for v in values]

    def test_missing_elements_stay_missing(self):
        result = round1_array(np.array([np.nan, 1.04]))

        assert np.isnan(result[0])
        assert result[1] == 1.0

    def test_it_accepts_a_plain_list(self):
        assert round1_array([1.04, 1.06]).tolist() == [1.0, 1.1]

    def test_an_empty_array_comes_back_empty(self):
        assert round1_array(np.array([])).shape == (0,)

    @pytest.mark.parametrize(
        ("seed", "values_of"),
        [
            # 一様乱数。手で選んだ数点では、境界に当たらないまま通ってしまう。
            (20260905, lambda rng: rng.uniform(0.0, 1000.0, size=200_000)),
            (20260906, lambda rng: rng.uniform(-100.0, 100.0, size=50_000)),
            # 小数2桁・3桁へ丸めた値は.X5の境界を大量に含む——食い違いが出るのはそこだけ。
            (20260907, lambda rng: np.round(rng.uniform(-1000.0, 1000.0, size=50_000), 2)),
            (20260908, lambda rng: np.round(rng.uniform(-1000.0, 1000.0, size=50_000), 3)),
        ],
    )
    def test_it_matches_the_builtin_over_a_large_sample(self, seed, values_of):
        values = values_of(np.random.default_rng(seed))
        reference = np.array([round(float(v), 1) for v in values])

        assert np.array_equal(round1_array(values), reference, equal_nan=True)
