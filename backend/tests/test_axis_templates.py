"""テンプレート自体の性質（両端クランプ・NaN伝播・スカラー/配列の同値性）の検証。"""

import numpy as np

from app.domain.axis_templates import (
    evaluate_breakpoint_linear,
    evaluate_categorical,
    round1_array,
)

BREAKPOINTS = [(0.0, 0.0), (3.0, 25.0), (6.0, 50.0), (9.0, 75.0), (15.0, 100.0)]


def _round1_reference(values: np.ndarray) -> np.ndarray:
    """Python組み込み`round()`を要素ごとに適用する参照実装。ベクトル化した`round1_array`
    とのビット一致を確認するテスト専用のオラクル。
    """
    return np.array([round(float(v), 1) if not np.isnan(v) else np.nan for v in values])


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


def test_evaluate_categorical_array_str_keys_with_missing_and_unmatched_values():
    # 配列版は欠損(None)を検索用にmappingの実在キーへ一時的に差し替えるため、差し替えた
    # だけで「一致した」ことにならないかをここで見る。
    mapping = {"separated": -2.0, "lane": -1.0, "roadway": 1.0}
    values = np.array(["separated", "lane", "roadway", None, "unknown_value"], dtype=object)

    result = evaluate_categorical(values, mapping)

    assert result[0] == -2.0
    assert result[1] == -1.0
    assert result[2] == 1.0
    assert np.isnan(result[3])  # None（欠損）はmappingの最初のキーへ誤マッチしないこと
    assert np.isnan(result[4])  # mapping未登録の値


def test_evaluate_categorical_array_resolves_bool_keys():
    # bool材料はfloatへ変換せずboolのまま引く。
    mapping = {True: 0.0, False: 80.0}
    values = np.array([True, False, True])

    result = evaluate_categorical(values, mapping)

    assert result[0] == 0.0
    assert result[1] == 80.0
    assert result[2] == 0.0


def test_round1_array_matches_reference_on_uniform_random_0_to_1000():
    rng = np.random.default_rng(20260905)
    values = rng.uniform(0.0, 1000.0, size=200_000)
    assert np.array_equal(round1_array(values), _round1_reference(values), equal_nan=True)


def test_round1_array_matches_reference_on_uniform_random_negative_100_to_100():
    rng = np.random.default_rng(20260906)
    values = rng.uniform(-100.0, 100.0, size=50_000)
    assert np.array_equal(round1_array(values), _round1_reference(values), equal_nan=True)


def test_round1_array_matches_reference_on_dot_x5_boundaries_from_round2():
    rng = np.random.default_rng(20260907)
    values = np.round(rng.uniform(-1000.0, 1000.0, size=50_000), 2)
    assert np.array_equal(round1_array(values), _round1_reference(values), equal_nan=True)


def test_round1_array_matches_reference_on_dot_x5_boundaries_from_round3():
    rng = np.random.default_rng(20260908)
    values = np.round(rng.uniform(-1000.0, 1000.0, size=50_000), 3)
    assert np.array_equal(round1_array(values), _round1_reference(values), equal_nan=True)


def test_round1_array_matches_reference_on_known_boundary_values():
    values = np.array(
        [
            385.95,
            385.949999999999988,
            41.25,
            41.35,
            0.25,
            0.75,
            1.25,
            -0.25,
            -1.25,
            2.675,
            1e15 + 0.25,
            0.0,
            -0.0,
            np.nan,
            1e-9,
            123456.05,
            123456.15,
        ]
    )
    assert np.array_equal(round1_array(values), _round1_reference(values), equal_nan=True)


def test_round1_array_handles_empty_array():
    result = round1_array(np.array([]))
    assert result.shape == (0,)


def test_round1_array_handles_list_input():
    result = round1_array([41.25, 0.25, np.nan])
    reference = _round1_reference(np.array([41.25, 0.25, np.nan]))
    assert np.array_equal(result, reference, equal_nan=True)
