from app.domain.recipe import (
    cycleway_values,
    parse_lanes,
    parse_maxspeed,
    tag_value_is,
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


class TestTagValueIs:
    def test_exact_match(self):
        assert tag_value_is({"motor_vehicle": "no"}, "motor_vehicle", "no") is True

    def test_case_and_whitespace_insensitive(self):
        assert tag_value_is({"lit": " YES "}, "lit", "yes") is True

    def test_missing_tag_is_false(self):
        assert tag_value_is({}, "lit", "yes") is False

    def test_different_value_is_false(self):
        assert tag_value_is({"lit": "no"}, "lit", "yes") is False
