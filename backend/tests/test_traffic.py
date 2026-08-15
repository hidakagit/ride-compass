from app.domain.traffic import (
    classify_bicycle_infrastructure,
    parse_lanes,
    parse_maxspeed,
    smoothness_score,
    traffic_stress_level,
)


class TestSmoothnessScore:
    def test_excellent_is_100(self):
        assert smoothness_score({"smoothness": "excellent"}) == 100.0

    def test_horrible_is_0(self):
        assert smoothness_score({"smoothness": "horrible"}) == 0.0

    def test_case_and_whitespace_insensitive(self):
        assert smoothness_score({"smoothness": " Good "}) == 85.0

    def test_missing_tag_is_none(self):
        assert smoothness_score({}) is None

    def test_unknown_value_is_none(self):
        assert smoothness_score({"smoothness": "mystery"}) is None


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


class TestClassifyBicycleInfrastructure:
    def test_highway_cycleway_is_separated(self):
        assert classify_bicycle_infrastructure({}, "cycleway") == "separated"

    def test_cycleway_track_is_separated(self):
        assert classify_bicycle_infrastructure({"cycleway": "track"}, "primary") == "separated"

    def test_cycleway_left_right_are_normalized(self):
        assert classify_bicycle_infrastructure({"cycleway:left": "track"}, "primary") == "separated"
        assert classify_bicycle_infrastructure({"cycleway:right": "lane"}, "primary") == "lane"

    def test_cycleway_lane_is_lane(self):
        assert classify_bicycle_infrastructure({"cycleway": "lane"}, "primary") == "lane"

    def test_shared_busway_or_shared_lane(self):
        assert classify_bicycle_infrastructure({"cycleway": "share_busway"}, "primary") == "shared_busway"
        assert classify_bicycle_infrastructure({"cycleway": "shared_lane"}, "primary") == "shared_busway"

    def test_footway_with_bicycle_designated_is_shared_pedestrian(self):
        assert classify_bicycle_infrastructure({"bicycle": "designated"}, "footway") == "shared_pedestrian"

    def test_path_with_bicycle_no_tag_is_roadway_not_shared(self):
        # bicycle=yes/designated/permissiveの明示が無ければ共用歩道扱いにしない
        assert classify_bicycle_infrastructure({}, "path") == "roadway"

    def test_bicycle_no_is_prohibited(self):
        assert classify_bicycle_infrastructure({"bicycle": "no"}, "residential") == "prohibited"

    def test_plain_highway_is_roadway(self):
        assert classify_bicycle_infrastructure({}, "residential") == "roadway"

    def test_no_highway_no_tags_is_unknown(self):
        assert classify_bicycle_infrastructure({}, None) == "unknown"

    def test_dedicated_cycleway_wins_over_bicycle_no(self):
        # 分離自転車道タグがある場合はbicycle=noより優先される（優先順位: separated>prohibited）
        assert classify_bicycle_infrastructure({"bicycle": "no"}, "cycleway") == "separated"


class TestTrafficStressLevel:
    def test_cycleway_base_is_1(self):
        assert traffic_stress_level("cycleway", {}) == 1

    def test_residential_base_is_2(self):
        assert traffic_stress_level("residential", {}) == 2

    def test_tertiary_base_is_3(self):
        assert traffic_stress_level("tertiary", {}) == 3

    def test_primary_base_is_4(self):
        assert traffic_stress_level("primary", {}) == 4

    def test_unknown_highway_is_none(self):
        assert traffic_stress_level("motorway", {}) is None
        assert traffic_stress_level(None, {}) is None

    def test_motor_vehicle_no_overrides_to_1_regardless_of_highway(self):
        assert traffic_stress_level("primary", {"motor_vehicle": "no"}) == 1

    def test_separated_cycleway_tag_reduces_by_2(self):
        assert traffic_stress_level("primary", {"cycleway": "track"}) == 2  # 4-2

    def test_cycleway_lane_reduces_by_1(self):
        assert traffic_stress_level("primary", {"cycleway": "lane"}) == 3  # 4-1

    def test_low_maxspeed_reduces_by_1(self):
        assert traffic_stress_level("primary", {"maxspeed": "30"}) == 3  # 4-1

    def test_high_maxspeed_increases_by_1(self):
        assert traffic_stress_level("tertiary", {"maxspeed": "60"}) == 4  # 3+1

    def test_many_lanes_increases_by_1(self):
        assert traffic_stress_level("tertiary", {"lanes": "4"}) == 4  # 3+1

    def test_result_is_clamped_to_1_4_range(self):
        # cycleway基本値1から更に-2しても1未満にはならない
        assert traffic_stress_level("cycleway", {"cycleway": "track", "maxspeed": "20"}) == 1
        # primary基本値4に複数の増加要因が重なっても4を超えない
        assert traffic_stress_level("primary", {"maxspeed": "80", "lanes": "6"}) == 4

    def test_unset_tags_do_not_apply_corrections(self):
        # 補正はタグが実際にある場合のみ適用する（unknownは補正しない）
        assert traffic_stress_level("tertiary", {}) == 3
