from app.domain.traffic import (
    classify_bicycle_infrastructure,
    classify_stop_poi,
    distance_weighted_bicycle_infra_score,
    distance_weighted_intersection_density,
    distance_weighted_stop_density,
    is_dedicated_bicycle_infra,
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


class TestClassifyStopPoi:
    def test_traffic_signals(self):
        assert classify_stop_poi({"highway": "traffic_signals"}) == "traffic_signals"

    def test_crossing(self):
        assert classify_stop_poi({"highway": "crossing"}) == "crossing"

    def test_stop(self):
        assert classify_stop_poi({"highway": "stop"}) == "stop"

    def test_give_way(self):
        assert classify_stop_poi({"highway": "give_way"}) == "give_way"

    def test_level_crossing(self):
        assert classify_stop_poi({"railway": "level_crossing"}) == "level_crossing"

    def test_level_crossing_takes_priority_over_highway(self):
        # 踏切と横断歩道タグが同一nodeに同居する場合、踏切側を優先する（一時停止義務が強いため）
        assert classify_stop_poi({"highway": "crossing", "railway": "level_crossing"}) == "level_crossing"

    def test_case_and_whitespace_insensitive(self):
        assert classify_stop_poi({"highway": " Traffic_Signals "}) == "traffic_signals"

    def test_missing_tags_is_none(self):
        assert classify_stop_poi({}) is None

    def test_unrelated_highway_value_is_none(self):
        assert classify_stop_poi({"highway": "residential"}) is None


class TestDistanceWeightedStopDensity:
    def test_sums_counts_over_total_distance(self):
        # 2区間: 1kmに2回、3kmに2回 -> 合計4回/合計4km = 1.0回/km
        assert distance_weighted_stop_density([(1.0, 2), (3.0, 2)]) == 1.0

    def test_is_total_ratio_not_average_of_rates(self):
        # 単純平均(2.0回/kmと0回/kmの平均=1.0)ではなく、合計count/合計distanceになる
        # 0.1kmに2回(20回/km相当)＋9.9kmに0回 -> 2/10.0 = 0.2回/km
        assert distance_weighted_stop_density([(0.1, 2), (9.9, 0)]) == 0.2

    def test_zero_total_distance_returns_none(self):
        assert distance_weighted_stop_density([(0.0, 3)]) is None

    def test_empty_returns_none(self):
        assert distance_weighted_stop_density([]) is None

    def test_no_stops_is_zero(self):
        assert distance_weighted_stop_density([(5.0, 0)]) == 0.0

    def test_none_counts_are_excluded_not_treated_as_zero(self):
        # データ未取得(None)の区間は実測0とは区別し、集計から除外する（残り区間で再正規化）
        assert distance_weighted_stop_density([(1.0, 2), (9.0, None)]) == 2.0

    def test_all_none_counts_return_none(self):
        assert distance_weighted_stop_density([(1.0, None), (2.0, None)]) is None


class TestDistanceWeightedIntersectionDensity:
    # distance_weighted_stop_densityと同じ集約ロジック（_density_per_km共有）のため
    # 基本ケースのみ確認する。詳細な境界値は上のTestDistanceWeightedStopDensity参照。
    def test_sums_counts_over_total_distance(self):
        assert distance_weighted_intersection_density([(1.0, 1), (3.0, 1)]) == 0.5

    def test_none_counts_are_excluded_not_treated_as_zero(self):
        assert distance_weighted_intersection_density([(1.0, 2), (9.0, None)]) == 2.0

    def test_empty_returns_none(self):
        assert distance_weighted_intersection_density([]) is None


class TestIsDedicatedBicycleInfra:
    def test_separated_is_dedicated(self):
        assert is_dedicated_bicycle_infra("separated") is True

    def test_lane_is_dedicated(self):
        assert is_dedicated_bicycle_infra("lane") is True

    def test_roadway_is_not_dedicated(self):
        assert is_dedicated_bicycle_infra("roadway") is False

    def test_shared_pedestrian_is_not_dedicated(self):
        assert is_dedicated_bicycle_infra("shared_pedestrian") is False

    def test_none_passthrough(self):
        assert is_dedicated_bicycle_infra(None) is None

    def test_unknown_is_treated_as_none_not_false(self):
        # classify_bicycle_infrastructureは判定不能(highway等が無い)場合Noneではなく
        # "unknown"を返す。ここでFalse扱いすると「データ欠損」が
        # distance_weighted_bicycle_infra_scoreの分母に「非専用インフラ確定」として
        # 混入してしまう(ORSエンジンでway_tagsの空間マッチに失敗した区間で発生しうる)。
        assert is_dedicated_bicycle_infra("unknown") is None


class TestDistanceWeightedBicycleInfraScore:
    def test_distance_weighted_percent_of_dedicated_infra(self):
        # 3kmが専用インフラ・1kmが非専用 -> 75%
        assert distance_weighted_bicycle_infra_score([(3.0, True), (1.0, False)]) == 75.0

    def test_all_dedicated_is_100_percent(self):
        assert distance_weighted_bicycle_infra_score([(5.0, True)]) == 100.0

    def test_unknown_segments_excluded_from_denominator(self):
        # Noneの区間(5km)は分母から除外し、残り2区間だけで計算する -> 1km/(1km+1km) = 50%
        assert distance_weighted_bicycle_infra_score([(1.0, True), (1.0, False), (5.0, None)]) == 50.0

    def test_all_unknown_returns_none(self):
        assert distance_weighted_bicycle_infra_score([(1.0, None), (2.0, None)]) is None

    def test_zero_known_distance_returns_none(self):
        assert distance_weighted_bicycle_infra_score([]) is None
