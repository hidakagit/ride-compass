"""scripts/measure_axis_stats.pyの純粋ロジック（相関計算・丸め損失・補正発火率集計）の検証。

DB接続自体はasyncpg依存かつ実DBが要るため、ここでは対象外（test_measure_tag_coverage.pyの
PBF切り分け方針・test_import_pbf.pyと同じ考え方）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from measure_axis_stats import (  # noqa: E402
    AdjustmentFiringCounter,
    RoundingLossCounter,
    adjustment_field_names,
    highway_accident_density,
    pearson_correlation,
    raw_pre_clamp_level,
    spearman_correlation,
)

from app.domain.safety import SafetyBreakdown  # noqa: E402
from app.domain.traffic import CarStressBreakdown  # noqa: E402


def _car_stress_breakdown(**overrides) -> CarStressBreakdown:
    defaults = dict(
        base=2,
        cycleway_adjustment=0,
        maxspeed_adjustment=0,
        lanes_adjustment=0,
        designation_adjustment=0,
        motor_vehicle_no_override=False,
        level=2,
    )
    defaults.update(overrides)
    return CarStressBreakdown(**defaults)


def _safety_breakdown(**overrides) -> SafetyBreakdown:
    defaults = dict(
        base=2,
        cycleway_adjustment=0,
        maxspeed_adjustment=0,
        lanes_adjustment=0,
        lit_adjustment=0,
        tunnel_adjustment=0,
        designation_adjustment=0,
        motor_vehicle_no_override=False,
        level=2,
    )
    defaults.update(overrides)
    return SafetyBreakdown(**defaults)


class TestPearsonCorrelation:
    def test_perfect_positive_correlation(self):
        assert pearson_correlation([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0

    def test_perfect_negative_correlation(self):
        assert pearson_correlation([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0

    def test_no_variance_is_none(self):
        assert pearson_correlation([1, 1, 1], [1, 2, 3]) is None

    def test_fewer_than_two_points_is_none(self):
        assert pearson_correlation([1], [1]) is None

    def test_mismatched_lengths_is_none(self):
        assert pearson_correlation([1, 2], [1, 2, 3]) is None

    def test_weighted_correlation_favors_heavier_points(self):
        # (1,1)と(2,2)は完全相関、(3,10)は外れ値。外れ値の重みを極小にすると
        # 完全相関側に近づくはず。
        xs, ys = [1, 2, 3], [1, 2, 10]
        unweighted = pearson_correlation(xs, ys)
        weighted = pearson_correlation(xs, ys, weights=[100.0, 100.0, 0.01])
        assert weighted is not None and unweighted is not None
        assert weighted > unweighted


class TestSpearmanCorrelation:
    def test_monotonic_nonlinear_relationship_is_perfect(self):
        # 非線形だが単調増加なため、Pearsonは1未満でもSpearmanは1.0になる
        xs, ys = [1, 2, 3, 4], [1, 4, 9, 16]
        assert spearman_correlation(xs, ys) == 1.0
        assert pearson_correlation(xs, ys) < 1.0

    def test_ties_use_average_rank(self):
        # 同順位2件を含んでいても計算が破綻しない（例外を出さず値を返す）ことを確認
        result = spearman_correlation([1, 1, 2, 3], [1, 2, 2, 3])
        assert result is not None

    def test_fewer_than_two_points_is_none(self):
        assert spearman_correlation([1], [1]) is None


class TestRawPreClampLevel:
    def test_sums_base_and_adjustments(self):
        breakdown = _car_stress_breakdown(base=4, cycleway_adjustment=-2, maxspeed_adjustment=1, lanes_adjustment=1)
        assert raw_pre_clamp_level(breakdown) == 4

    def test_unregistered_highway_is_none(self):
        breakdown = _car_stress_breakdown(base=None, level=None)
        assert raw_pre_clamp_level(breakdown) is None

    def test_motor_vehicle_override_is_none(self):
        breakdown = _car_stress_breakdown(motor_vehicle_no_override=True, level=1)
        assert raw_pre_clamp_level(breakdown) is None

    def test_works_for_safety_breakdown_too(self):
        breakdown = _safety_breakdown(base=3, lit_adjustment=-1, tunnel_adjustment=1)
        assert raw_pre_clamp_level(breakdown) == 3


class TestAdjustmentFieldNames:
    def test_car_stress_fields_exclude_base_and_level(self):
        fields = adjustment_field_names(CarStressBreakdown)
        assert "cycleway_adjustment" in fields
        assert "motor_vehicle_no_override" in fields
        assert "base" not in fields
        assert "level" not in fields

    def test_safety_fields_include_lit_tunnel(self):
        fields = adjustment_field_names(SafetyBreakdown)
        assert {"lit_adjustment", "tunnel_adjustment"} <= set(fields)


class TestRoundingLossCounter:
    def test_counts_above_max_by_count_and_distance(self):
        counter = RoundingLossCounter(1, 5)
        counter.add(6, distance_km=10.0)
        counter.add(3, distance_km=90.0)

        assert counter.above_max_count == 1
        assert counter.above_max_distance_km == 10.0
        assert counter.total_count == 2
        assert counter.total_distance_km == 100.0

    def test_counts_below_min(self):
        counter = RoundingLossCounter(1, 5)
        counter.add(0, distance_km=5.0)
        counter.add(3, distance_km=5.0)

        assert counter.below_min_count == 1
        assert counter.below_min_distance_km == 5.0

    def test_report_lines_include_percentages(self):
        counter = RoundingLossCounter(1, 5)
        counter.add(6, distance_km=10.0)
        counter.add(3, distance_km=10.0)

        lines = counter.report_lines("テスト軸")
        assert any("上限超過" in line and "50.0%" in line for line in lines)


class TestAdjustmentFiringCounter:
    def test_counts_nonzero_adjustment_as_fired(self):
        counter = AdjustmentFiringCounter(["tunnel_adjustment", "lit_adjustment"])
        counter.add(_safety_breakdown(tunnel_adjustment=1, lit_adjustment=0), distance_km=10.0)
        counter.add(_safety_breakdown(tunnel_adjustment=0, lit_adjustment=0), distance_km=10.0)

        assert counter.fired_count["tunnel_adjustment"] == 1
        assert counter.fired_count["lit_adjustment"] == 0
        assert counter.fired_distance_km["tunnel_adjustment"] == 10.0

    def test_counts_true_boolean_override_as_fired(self):
        counter = AdjustmentFiringCounter(["motor_vehicle_no_override"])
        counter.add(_car_stress_breakdown(motor_vehicle_no_override=True, level=1), distance_km=5.0)
        counter.add(_car_stress_breakdown(motor_vehicle_no_override=False), distance_km=5.0)

        assert counter.fired_count["motor_vehicle_no_override"] == 1

    def test_report_lines_flag_dead_adjustment(self):
        # 改善計画T124の動機（死に補正の検出）: 一度も発火しないフィールドは0%で報告される
        # （実例: shoulder_adjustmentは実測0.0%で「死に補正」と判明し、T122で撤去された）
        counter = AdjustmentFiringCounter(["tunnel_adjustment"])
        counter.add(_safety_breakdown(tunnel_adjustment=0), distance_km=10.0)

        lines = counter.report_lines("安全度")
        assert any("tunnel_adjustment: 0件（0.0%）" in line for line in lines)


class TestHighwayAccidentDensity:
    def test_computes_density_per_highway(self):
        rows = [("residential", 10.0, 5.0), ("primary", 20.0, 40.0)]
        result = highway_accident_density(rows, years_covered=2)

        assert result["residential"] == 0.25  # 5.0 / 10.0 / 2
        assert result["primary"] == 1.0  # 40.0 / 20.0 / 2

    def test_zero_years_covered_is_none(self):
        result = highway_accident_density([("residential", 10.0, 5.0)], years_covered=0)
        assert result["residential"] is None
