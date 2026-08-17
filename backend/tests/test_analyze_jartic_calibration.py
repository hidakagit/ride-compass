"""scripts/analyze_jartic_calibration.pyの純粋ロジック（LTS段階別グルーピング・分布サマリ・
単調性判定）の検証。DB接続自体は対象外（test_measure_axis_stats.pyと同じ切り分け方針）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from analyze_jartic_calibration import (  # noqa: E402
    group_volumes_by_level,
    is_monotonic_by_level,
    summarize_group,
)


def test_group_volumes_by_level_buckets_by_level():
    rows = [(1, 100.0), (2, 200.0), (1, 150.0), (3, 50.0)]
    grouped = group_volumes_by_level(rows)
    assert grouped == {1: [100.0, 150.0], 2: [200.0], 3: [50.0]}


def test_group_volumes_by_level_excludes_none_level():
    rows = [(1, 100.0), (None, 999.0)]
    grouped = group_volumes_by_level(rows)
    assert grouped == {1: [100.0]}


def test_group_volumes_by_level_empty_input():
    assert group_volumes_by_level([]) == {}


def test_summarize_group_computes_stats():
    summary = summarize_group([10.0, 20.0, 30.0])
    assert summary == {"count": 3, "mean": 20.0, "median": 20.0, "min": 10.0, "max": 30.0}


def test_is_monotonic_by_level_true_for_increasing_means():
    grouped = {1: [10.0], 2: [20.0], 3: [30.0]}
    assert is_monotonic_by_level(grouped) is True


def test_is_monotonic_by_level_true_for_equal_means():
    grouped = {1: [10.0], 2: [10.0]}
    assert is_monotonic_by_level(grouped) is True


def test_is_monotonic_by_level_false_when_a_later_level_dips():
    grouped = {1: [10.0], 2: [30.0], 3: [20.0]}
    assert is_monotonic_by_level(grouped) is False


def test_is_monotonic_by_level_true_for_single_or_empty_group():
    assert is_monotonic_by_level({}) is True
    assert is_monotonic_by_level({1: [10.0]}) is True
