"""`domain/wbgt.py`——暑さ指数から警戒レベルを決める。

取得・キャッシュは`test_wbgt_service.py`、地点の解決は`test_geo.py`（最寄りの点）が持つ。
"""

from datetime import date, datetime

import pytest

from app.domain.wbgt import is_within_provision_period, provision_period, wbgt_level


class TestWbgtLevel:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (31.0, ("emergency_warning", "危険")),
            (28.0, ("severe_warning", "厳重警戒")),
            (25.0, ("warning", "警戒")),
            (21.0, ("advisory", "注意")),
        ],
    )
    def test_each_threshold_is_inclusive(self, value, expected):
        """境界を超過で切ると、区分がまるごと1段軽く出る。"""
        assert wbgt_level(value) == expected

    @pytest.mark.parametrize("value", [30.9, 27.9, 24.9, 20.9])
    def test_just_below_a_threshold_falls_to_the_lighter_band(self, value):
        level = wbgt_level(value)

        assert level != wbgt_level(value + 0.2)

    def test_the_mildest_band_is_not_a_warning(self):
        """返すと、涼しい日も常に何かが表示され続ける。"""
        assert wbgt_level(20.9) is None
        assert wbgt_level(0.0) is None

    def test_an_extreme_value_stays_in_the_heaviest_band(self):
        assert wbgt_level(99.0) == wbgt_level(31.0)


class TestProvisionPeriod:

    @pytest.mark.parametrize(
        ("year", "announced"),
        [
            # 環境省の報道発表（熱中症特別警戒アラート等の運用開始）が載せた運用期間。
            (2024, (date(2024, 4, 24), date(2024, 10, 23))),
            (2025, (date(2025, 4, 23), date(2025, 10, 22))),
            (2026, (date(2026, 4, 22), date(2026, 10, 21))),
        ],
    )
    def test_the_period_matches_the_announced_one(self, year, announced):
        """ずれると、期間の端で配信元の値が無いのに「取得できませんでした」が出るか、値があるのに出さない。"""
        assert provision_period(year) == announced

    @pytest.mark.parametrize(
        ("at", "expected"),
        [
            (datetime(2026, 4, 21, 23, 59), False),
            (datetime(2026, 4, 22, 0, 0), True),
            (datetime(2026, 10, 21, 23, 59), True),
            (datetime(2026, 10, 22, 0, 0), False),
        ],
    )
    def test_both_end_days_are_inside(self, at, expected):
        assert is_within_provision_period(at) is expected

    @pytest.mark.parametrize("month", [1, 2, 3, 11, 12])
    def test_the_other_months_are_outside(self, month):
        assert is_within_provision_period(datetime(2026, month, 15)) is False
