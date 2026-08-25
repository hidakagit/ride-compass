import pytest

from app.domain.accident import (
    build_accident_id,
    distance_weighted_accident_density,
    involves_bicycle,
    is_fatal,
    is_kanto_prefecture,
    latitude_from_raw,
    longitude_from_raw,
)


class TestIsKantoPrefecture:
    def test_tokyo_is_kanto(self):
        assert is_kanto_prefecture("30") is True

    def test_hokkaido_is_not_kanto(self):
        assert is_kanto_prefecture("10") is False

    def test_strips_whitespace(self):
        assert is_kanto_prefecture(" 45 ") is True


class TestInvolvesBicycle:
    def test_party_a_bicycle(self):
        assert involves_bicycle("51", "03") is True

    def test_party_b_e_assist_bicycle(self):
        assert involves_bicycle("03", "52") is True

    def test_neither_is_bicycle(self):
        assert involves_bicycle("03", "76") is False

    def test_other_light_vehicle_is_not_bicycle(self):
        # 59=軽車両－その他（手押し車等）は自転車ではない
        assert involves_bicycle("59", "76") is False


class TestIsFatal:
    def test_zero_is_not_fatal(self):
        assert is_fatal("000") is False

    def test_positive_is_fatal(self):
        assert is_fatal("001") is True

    def test_non_numeric_is_not_fatal(self):
        assert is_fatal("") is False


class TestBuildAccidentId:
    def test_composes_year_prefecture_station_number(self):
        assert build_accident_id("10", "059", "0001", 2023) == "2023-10-059-0001"


class TestDmsConversion:
    def test_latitude_matches_known_sample(self):
        # honhyo_2023.csv実データ1行目（2026-08-16実機確認、北海道札幌方面 43.169度付近）
        value = latitude_from_raw("431007628")
        assert value is not None
        assert round(value, 4) == round(43 + 10 / 60 + 7.628 / 3600, 4)

    def test_longitude_matches_known_sample(self):
        value = longitude_from_raw("1410328320")
        assert value is not None
        assert round(value, 4) == round(141 + 3 / 60 + 28.320 / 3600, 4)

    def test_all_zero_is_none(self):
        assert latitude_from_raw("000000000") is None
        assert longitude_from_raw("0000000000") is None

    def test_non_numeric_is_none(self):
        assert latitude_from_raw("") is None
        assert longitude_from_raw("abc") is None

    def test_out_of_japan_range_is_none(self):
        # 度部分だけ極端な値にした不正データ
        assert latitude_from_raw("990007628") is None

    def test_invalid_minutes_or_seconds_is_none(self):
        # 分が60以上は不正値（度分秒として成立しない）
        assert latitude_from_raw("436907628") is None


class TestDistanceWeightedAccidentDensity:
    def test_years_covered_zero_is_none(self):
        assert distance_weighted_accident_density([(10.0, 5.0)], years_covered=0) is None

    def test_years_covered_negative_is_none(self):
        assert distance_weighted_accident_density([(10.0, 5.0)], years_covered=-1) is None

    def test_empty_segments_is_none(self):
        assert distance_weighted_accident_density([], years_covered=1) is None

    def test_all_counts_none_is_none(self):
        # count=Noneは「データ未取得」を表し、集計から除外される。除外後に1区間も
        # 残らなければNone。
        segments = [(10.0, None), (5.0, None)]
        assert distance_weighted_accident_density(segments, years_covered=1) is None

    def test_distance_sum_zero_is_none(self):
        assert distance_weighted_accident_density([(0.0, 5.0)], years_covered=1) is None

    def test_distance_sum_negative_is_none(self):
        assert distance_weighted_accident_density([(-1.0, 5.0)], years_covered=1) is None

    def test_none_count_segment_excluded_from_both_distance_and_count_sum(self):
        # count=Noneの区間はcountだけでなくdistanceも集計から除外される
        # （分母distance_sumに含めない）。
        segments = [(1.0, 2.0), (100.0, None)]
        result = distance_weighted_accident_density(segments, years_covered=1)
        assert result == pytest.approx(2.0 / 1.0)

    def test_zero_count_segment_is_distinct_from_none_and_included(self):
        # count=0（実測で対象無し）はNoneと区別され、集計に含まれる。
        segments = [(2.0, 0.0)]
        assert distance_weighted_accident_density(segments, years_covered=1) == 0.0

    def test_computes_density_normalized_by_years_and_rounded_to_two_decimals(self):
        # 1.0件 / 3.0km / 2年 = 0.16666... -> 0.17
        result = distance_weighted_accident_density([(3.0, 1.0)], years_covered=2)
        assert result == pytest.approx(0.17)

    def test_aggregates_multiple_available_segments(self):
        segments = [(2.0, 1.0), (3.0, 2.0)]
        # count_sum=3.0, distance_sum=5.0, years_covered=1 -> 0.6
        result = distance_weighted_accident_density(segments, years_covered=1)
        assert result == pytest.approx(0.6)
