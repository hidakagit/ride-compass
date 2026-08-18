"""scripts/measure_axis_correlation.pyの純粋ロジック（相関計算）の検証（改善計画T147）。

DB/GSI API接続自体は実環境が要るため、ここでは対象外（test_measure_axis_stats.pyと
同じ切り分け方針）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from measure_axis_correlation import correlation_matrix, pearson_correlation  # noqa: E402


class TestPearsonCorrelation:
    def test_perfect_positive_correlation(self):
        assert pearson_correlation([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 1.0

    def test_perfect_negative_correlation(self):
        assert pearson_correlation([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]) == -1.0

    def test_no_correlation_when_one_axis_constant(self):
        assert pearson_correlation([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None

    def test_fewer_than_two_points_is_none(self):
        assert pearson_correlation([1.0], [1.0]) is None
        assert pearson_correlation([], []) is None

    def test_mismatched_lengths_is_none(self):
        assert pearson_correlation([1.0, 2.0], [1.0]) is None


class TestCorrelationMatrix:
    def test_computes_all_pairs(self):
        axis_values = {
            "a": [1.0, 2.0, 3.0],
            "b": [1.0, 2.0, 3.0],
            "c": [3.0, 2.0, 1.0],
        }

        matrix = correlation_matrix(axis_values)

        assert matrix[("a", "b")] == 1.0
        assert matrix[("a", "c")] == -1.0
        assert matrix[("b", "c")] == -1.0

    def test_excludes_rows_where_either_axis_is_none(self):
        # 3行目はaがNoneのため、有効な2点(1,1)(2,2)だけで相関を計算する。
        axis_values = {"a": [1.0, 2.0, None], "b": [1.0, 2.0, 100.0]}

        matrix = correlation_matrix(axis_values)

        assert matrix[("a", "b")] == 1.0

    def test_pair_with_insufficient_valid_rows_is_none(self):
        axis_values = {"a": [1.0, None, None], "b": [1.0, 2.0, 3.0]}

        matrix = correlation_matrix(axis_values)

        assert matrix[("a", "b")] is None
