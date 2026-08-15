from app.domain.accident import (
    build_accident_id,
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
