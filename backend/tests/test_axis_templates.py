"""axis_templates.py（改善計画T221 Stage A、T239）のスカラー・numpy配列両モードの検証。

`domain/difficulty.py`・`domain/night.py`側の回帰は既存テスト（test_difficulty.py・
test_night.py・test_traffic.py・test_evaluation.py）がスカラー経路の入出力一致を担保する。
本ファイルはテンプレート自体の性質（両端クランプ・NaN伝播・スカラー/配列の同値性）を検証する。
"""

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
    # コードレビュー指摘の修正確認(finding #5): 配列版をnp.searchsortedベースの
    # 二分探索へ書き換えた際、欠損(None)を検索用に一時的にkeys[0]（=mappingの実在キー）
    # へ差し替える実装だと、置き換えただけで「一致した」ことになってしまいNoneの区間が
    # keys[0]のスコアへ誤って解決される回帰が実装中に見つかった（`missing`マスクで
    # 検索結果と無関係に不一致へ強制する形で修正済み）。この回帰を固定する。
    mapping = {"separated": -2.0, "lane": -1.0, "roadway": 1.0}
    values = np.array(["separated", "lane", "roadway", None, "unknown_value"], dtype=object)

    result = evaluate_categorical(values, mapping)

    assert result[0] == -2.0
    assert result[1] == -1.0
    assert result[2] == 1.0
    assert np.isnan(result[3])  # None（欠損）はmappingの最初のキーへ誤マッチしないこと
    assert np.isnan(result[4])  # mapping未登録の値


def test_evaluate_categorical_array_bool_keys_matches_scalar():
    # コードレビュー指摘の修正確認: bool材料をfloatキー(1.0/0.0)へ変換する特別扱いを
    # 撤去した後も、bool配列に対する結果がスカラー版と一致すること。
    mapping = {True: 0.0, False: 80.0}
    values = np.array([True, False, True])

    result = evaluate_categorical(values, mapping)

    assert result[0] == evaluate_categorical(True, mapping) == 0.0
    assert result[1] == evaluate_categorical(False, mapping) == 80.0
    assert result[2] == 0.0


def test_evaluate_breakpoint_linear_sums_boolean_terms_like_flag_sum():
    # 改善計画T396: 旧evaluate_flag_sumはboolean材料の重み付き和＋クランプの特殊形で、
    # breakpoints=[(0, 0), (cap, cap)]のevaluate_breakpoint_linearと等価だった。
    breakpoints = [(0.0, 0.0), (100.0, 100.0)]

    def combine(a: bool, b: float, weight_a: float, weight_b: float) -> float:
        return evaluate_breakpoint_linear(a * weight_a + b * weight_b, breakpoints)

    assert combine(True, False, 50.0, 50.0) == 50.0
    assert combine(True, True, 50.0, 50.0) == 100.0
    assert combine(True, True, 60.0, 60.0) == 100.0  # capでクランプ


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
