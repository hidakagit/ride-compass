from app.domain.accident import latitude_from_raw, longitude_from_raw


class TestDmsConversion:
    def test_latitude_matches_known_sample(self):
        # 本票CSVの実データ1行目の値（北海道札幌方面、43.169度付近）。
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
