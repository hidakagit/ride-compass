"""axis_templates.py（改善計画T221 Stage A、T239）のスカラー・numpy配列両モードの検証。

`domain/difficulty.py`・`domain/night.py`側の回帰は既存テスト（test_difficulty.py・
test_night.py・test_traffic.py・test_evaluation.py）がスカラー経路の入出力一致を担保する。
本ファイルはテンプレート自体の性質（両端クランプ・NaN伝播・スカラー/配列の同値性）を検証する。
"""

import numpy as np

from app.domain.axis_templates import (
    evaluate_breakpoint_linear,
    evaluate_categorical,
    evaluate_flag_sum,
    evaluate_recipe_then_breakpoint_linear,
)

BREAKPOINTS = [(0.0, 0.0), (3.0, 25.0), (6.0, 50.0), (9.0, 75.0), (15.0, 100.0)]


def test_evaluate_breakpoint_linear_scalar_clamps_below_and_above_range():
    assert evaluate_breakpoint_linear(-5.0, BREAKPOINTS) == 0.0
    assert evaluate_breakpoint_linear(20.0, BREAKPOINTS) == 100.0


def test_evaluate_breakpoint_linear_scalar_interpolates_midpoint():
    # 3.0→25.0, 6.0→50.0 の中間(4.5)は線形補間で37.5
    assert evaluate_breakpoint_linear(4.5, BREAKPOINTS) == 37.5


def test_evaluate_breakpoint_linear_array_matches_scalar_elementwise():
    values = [-5.0, 0.0, 4.5, 9.0, 20.0]
    scalar_results = [evaluate_breakpoint_linear(v, BREAKPOINTS) for v in values]
    array_result = evaluate_breakpoint_linear(np.array(values), BREAKPOINTS)
    assert list(array_result) == scalar_results


def test_evaluate_breakpoint_linear_array_propagates_nan():
    array_result = evaluate_breakpoint_linear(np.array([1.0, np.nan, 8.0]), BREAKPOINTS)
    assert not np.isnan(array_result[0])
    assert np.isnan(array_result[1])
    assert not np.isnan(array_result[2])


def test_evaluate_recipe_then_breakpoint_linear_is_same_as_breakpoint_linear():
    car_stress_breakpoints = [(1, 0.0), (5, 100.0)]
    assert evaluate_recipe_then_breakpoint_linear(3, car_stress_breakpoints) == evaluate_breakpoint_linear(
        3, car_stress_breakpoints
    )


def test_evaluate_categorical_scalar():
    mapping = {True: 0.0, False: 80.0}
    assert evaluate_categorical(True, mapping) == 0.0
    assert evaluate_categorical(False, mapping) == 80.0


def test_evaluate_categorical_scalar_unmatched_key_returns_default():
    assert evaluate_categorical("unknown", {"a": 1.0}, default=None) is None
    assert evaluate_categorical("unknown", {"a": 1.0}, default=-1.0) == -1.0


def test_evaluate_categorical_array_matches_scalar_and_propagates_nan():
    mapping = {1.0: 0.0, 0.0: 80.0}
    values = np.array([1.0, 0.0, np.nan])
    result = evaluate_categorical(values, mapping)
    assert result[0] == 0.0
    assert result[1] == 80.0
    assert np.isnan(result[2])


def test_evaluate_flag_sum_scalar_sums_and_caps():
    assert evaluate_flag_sum([(True, 50.0), (False, 50.0)]) == 50.0
    assert evaluate_flag_sum([(True, 50.0), (True, 50.0)]) == 100.0
    assert evaluate_flag_sum([(True, 60.0), (True, 60.0)], cap=100.0) == 100.0


def test_evaluate_flag_sum_array_matches_scalar_elementwise():
    flags_a = [True, False, True]
    flags_b = [False, True, True]
    scalar_results = [
        evaluate_flag_sum([(a, 50.0), (b, 50.0)], cap=100.0) for a, b in zip(flags_a, flags_b)
    ]
    array_result = evaluate_flag_sum(
        [(np.array(flags_a), 50.0), (np.array(flags_b), 50.0)], cap=100.0
    )
    assert list(array_result) == scalar_results
