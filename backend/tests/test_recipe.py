import pytest

from app.domain.recipe import (
    clamp_level,
    cycleway_adjustment,
    cycleway_class,
    cycleway_values,
    flag_adjustment,
    parse_lanes,
    parse_maxspeed,
    tag_value_is,
    threshold_adjustment,
    validate_threshold_order,
)


class TestParseLanes:
    def test_parses_integer_string(self):
        assert parse_lanes({"lanes": "2"}) == 2

    def test_truncates_decimal_values(self):
        assert parse_lanes({"lanes": "2.5"}) == 2

    def test_missing_tag_is_none(self):
        assert parse_lanes({}) is None

    def test_non_numeric_is_none(self):
        assert parse_lanes({"lanes": "many"}) is None

    def test_zero_or_negative_is_none(self):
        assert parse_lanes({"lanes": "0"}) is None
        assert parse_lanes({"lanes": "-1"}) is None


class TestParseMaxspeed:
    def test_parses_integer_string(self):
        assert parse_maxspeed({"maxspeed": "40"}) == 40

    def test_missing_tag_is_none(self):
        assert parse_maxspeed({}) is None

    def test_unit_suffixed_value_is_none(self):
        # 日本のOSMはkm/h数値表記が主。"30 mph"のような単位付きはパース対象外(unknown安全)
        assert parse_maxspeed({"maxspeed": "30 mph"}) is None

    def test_non_numeric_is_none(self):
        assert parse_maxspeed({"maxspeed": "walk"}) is None


class TestCyclewayValues:
    def test_collects_all_four_keys(self):
        tags = {"cycleway": "lane", "cycleway:left": "track", "cycleway:right": "shared_lane", "cycleway:both": "no"}
        assert cycleway_values(tags) == ["lane", "track", "shared_lane", "no"]

    def test_missing_keys_are_skipped(self):
        assert cycleway_values({"cycleway:left": "track"}) == ["track"]

    def test_no_keys_is_empty(self):
        assert cycleway_values({}) == []


class TestCyclewayClass:
    def test_track_takes_priority(self):
        assert cycleway_class({"cycleway": "lane", "cycleway:left": "track"}) == "track"

    def test_lane(self):
        assert cycleway_class({"cycleway": "lane"}) == "lane"

    def test_shared_lane_or_share_busway_is_shared(self):
        assert cycleway_class({"cycleway": "shared_lane"}) == "shared"
        assert cycleway_class({"cycleway": "share_busway"}) == "shared"

    def test_unrelated_value_is_none(self):
        assert cycleway_class({"cycleway": "no"}) is None

    def test_no_tags_is_none(self):
        assert cycleway_class({}) is None


class TestClampLevel:
    def test_within_range_is_unchanged(self):
        assert clamp_level(3, 1, 5) == 3

    def test_above_max_is_clamped(self):
        assert clamp_level(7, 1, 5) == 5

    def test_below_min_is_clamped(self):
        assert clamp_level(-1, 1, 5) == 1

    def test_boundary_values_are_unchanged(self):
        assert clamp_level(1, 1, 5) == 1
        assert clamp_level(5, 1, 5) == 5


class TestThresholdAdjustment:
    def test_none_value_is_zero(self):
        assert threshold_adjustment(None, 30, -1, 60, 1) == 0

    def test_at_or_below_low_threshold_returns_low_adjustment(self):
        assert threshold_adjustment(30, 30, -1, 60, 1) == -1
        assert threshold_adjustment(10, 30, -1, 60, 1) == -1

    def test_at_or_above_high_threshold_returns_high_adjustment(self):
        assert threshold_adjustment(60, 30, -1, 60, 1) == 1
        assert threshold_adjustment(80, 30, -1, 60, 1) == 1

    def test_between_thresholds_is_zero(self):
        assert threshold_adjustment(45, 30, -1, 60, 1) == 0

    def test_low_threshold_none_disables_low_direction(self):
        # domain/safety.py: safety_breakdownのlanes（high方向のみ採用、少車線側は見送り）と
        # 同じ使い方。低い値でも0のまま。
        assert threshold_adjustment(1, None, -1, 4, 1) == 0
        assert threshold_adjustment(4, None, -1, 4, 1) == 1

    def test_high_threshold_none_disables_high_direction(self):
        assert threshold_adjustment(100, 1, -1, None, 1) == 0


class TestCyclewayAdjustment:
    def test_track(self):
        assert cycleway_adjustment({"cycleway": "track"}, -2, -1, -1) == -2

    def test_lane(self):
        assert cycleway_adjustment({"cycleway": "lane"}, -2, -1, -1) == -1

    def test_shared(self):
        assert cycleway_adjustment({"cycleway": "shared_lane"}, -2, -1, -1) == -1

    def test_no_match_is_zero(self):
        assert cycleway_adjustment({}, -2, -1, -1) == 0


class TestFlagAdjustment:
    def test_present_returns_adjustment(self):
        assert flag_adjustment(True, -1) == -1

    def test_absent_returns_zero(self):
        assert flag_adjustment(False, -1) == 0


class TestTagValueIs:
    def test_exact_match(self):
        assert tag_value_is({"motor_vehicle": "no"}, "motor_vehicle", "no") is True

    def test_case_and_whitespace_insensitive(self):
        assert tag_value_is({"lit": " YES "}, "lit", "yes") is True

    def test_missing_tag_is_false(self):
        assert tag_value_is({}, "lit", "yes") is False

    def test_different_value_is_false(self):
        assert tag_value_is({"lit": "no"}, "lit", "yes") is False


class TestValidateThresholdOrder:
    def test_low_less_than_high_does_not_raise(self):
        validate_threshold_order(30, 60, "maxspeed")

    def test_low_equal_to_high_raises(self):
        with pytest.raises(ValueError, match="maxspeed_low_threshold"):
            validate_threshold_order(30, 30, "maxspeed")

    def test_low_greater_than_high_raises(self):
        with pytest.raises(ValueError, match="lanes_low_threshold"):
            validate_threshold_order(5, 1, "lanes")
