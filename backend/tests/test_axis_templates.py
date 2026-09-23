"""`domain/axis_templates.py`——軸の得点を作る2つの変換と、配列版の丸め。

ここで見ないもの:
- どの材料をどの変換へ通すか（軸の宣言と評価） → `test_axis_definitions.py`
- 軸が軸を参照するときの並べ替え → `test_axis_hierarchy.py`
"""

import math

import numpy as np
import pytest

from app.domain import axis_templates

BREAKPOINTS = [(0.0, 0.0), (10.0, 100.0)]


class TestEvaluateBreakpointLinear:
    @pytest.mark.parametrize(("value", "expected"), [(5.0, 50.0), (-5.0, 0.0), (15.0, 100.0)])
    def test_scalar_interpolates_and_clamps_at_both_ends(self, value, expected):
        assert axis_templates.evaluate_breakpoint_linear(value, BREAKPOINTS) == expected

    def test_array_keeps_missing_values_missing(self):
        result = axis_templates.evaluate_breakpoint_linear(np.array([np.nan, 5.0, 20.0]), BREAKPOINTS)

        assert math.isnan(result[0])
        assert result[1:].tolist() == [50.0, 100.0]


class TestEvaluateCategorical:
    MAPPING = {"b": 20.0, "a": 10.0}

    @pytest.mark.parametrize(("value", "expected"), [("a", 10.0), ("z", None), (None, None)])
    def test_scalar_looks_up_the_value_and_leaves_the_rest_unevaluated(self, value, expected):
        assert axis_templates.evaluate_categorical(value, self.MAPPING) == expected

    def test_array_of_strings_scores_only_registered_values(self):
        """未登録の値は、並べたキーのどこに落ちても（先頭より前・間・末尾より後）一致させない。
        欠損は検索のために先頭キーへ置き換えるが、それでも一致させない。"""
        values = np.array(["b", "a", "0", "aa", "z", None], dtype=object)

        result = axis_templates.evaluate_categorical(values, self.MAPPING)

        assert result[:2].tolist() == [20.0, 10.0]
        assert np.isnan(result[2:]).all()

    def test_array_of_booleans_scores_both_values(self):
        result = axis_templates.evaluate_categorical(np.array([True, False]), {False: 0.0, True: 30.0})

        assert result.tolist() == [30.0, 0.0]

    def test_numeric_array_of_a_flag_scores_both_values_and_keeps_missing_values_missing(self):
        """欠損を「不明」とする真偽の材料は、1.0/0.0と欠損NaNの数値配列で届く。"""
        result = axis_templates.evaluate_categorical(np.array([1.0, 0.0, np.nan]), {False: 0.0, True: 30.0})

        assert result[:2].tolist() == [30.0, 0.0]
        assert math.isnan(result[2])


class TestRound1Array:
    def test_agrees_with_python_round_on_values_that_sit_on_a_half(self):
        """`np.round`は0.15・0.35を0.2・0.4へ上げるが、10進の正しい丸めは0.1・0.3
        （2進では0.1499…・0.3499…のため）。0.25は2進で正確に表せるので偶数へ丸める。"""
        result = axis_templates.round1_array(np.array([0.15, 0.25, 0.35]))

        assert result.tolist() == [0.1, 0.2, 0.3]

    def test_rounds_ordinary_values_and_keeps_missing_values_missing(self):
        result = axis_templates.round1_array(np.array([1.04, 2.26, np.nan]))

        assert result[:2].tolist() == [1.0, 2.3]
        assert math.isnan(result[2])
