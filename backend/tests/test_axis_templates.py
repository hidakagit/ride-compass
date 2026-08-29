"""axis_templates.py（改善計画T221 Stage A、T239）のスカラー・numpy配列両モードの検証。

`domain/difficulty.py`・`domain/night.py`側の回帰は既存テスト（test_difficulty.py・
test_night.py・test_traffic.py・test_evaluation.py）がスカラー経路の入出力一致を担保する。
本ファイルはテンプレート自体の性質（両端クランプ・NaN伝播・スカラー/配列の同値性）を検証する。
"""

import numpy as np

from app.domain.axis_templates import (
    evaluate_breakpoint_linear,
    evaluate_categorical,
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
