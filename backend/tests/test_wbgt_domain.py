"""`domain/wbgt.py`——暑さ指数から警戒レベルを決める。

取得・キャッシュは`test_wbgt_service.py`、地点の解決は`test_wbgt_points.py`が持つ。

閾値の典拠は環境省サイト掲載の**熱中症予防運動指針**（日本スポーツ協会）。サイクリングは
運動のため、日常生活に関する指針（日本生気象学会、区分の切り方が違う）は使わない。
"""

from datetime import datetime

import pytest

from app.domain.wbgt import PROVISION_END_MONTH, PROVISION_START_MONTH, is_within_provision_period, wbgt_level


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
        """指針の区分は「◯◯以上」。境界を超過で切ると、区分がまるごと1段軽く出る。"""
        assert wbgt_level(value) == expected

    @pytest.mark.parametrize("value", [30.9, 27.9, 24.9, 20.9])
    def test_just_below_a_threshold_falls_to_the_lighter_band(self, value):
        level = wbgt_level(value)

        assert level != wbgt_level(value + 0.2)

    def test_the_mildest_band_is_not_a_warning(self):
        """指針の最も軽い区分「ほぼ安全」はバッジとして意味を持たない。返すと、涼しい日も
        常に何かが表示され続ける。
        """
        assert wbgt_level(20.9) is None
        assert wbgt_level(0.0) is None

    def test_the_bands_get_heavier_as_the_index_rises(self):
        keys = [wbgt_level(v)[0] for v in (21.0, 25.0, 28.0, 31.0)]

        assert len(set(keys)) == 4

    def test_an_extreme_value_stays_in_the_heaviest_band(self):
        assert wbgt_level(99.0) == wbgt_level(31.0)


class TestProvisionPeriod:
    """提供期間の粗い判定。**API呼び出しを省くための事前フィルタ**で、正確性の最終防線
    ではない——期間外に呼んでも取得が失敗し、呼び出し元のfail-openで「表示なし」へ収束する。
    """

    @pytest.mark.parametrize("month", range(PROVISION_START_MONTH, PROVISION_END_MONTH + 1))
    def test_the_provision_months_are_inside(self, month):
        assert is_within_provision_period(datetime(2026, month, 15)) is True

    @pytest.mark.parametrize("month", [1, 2, 3, 11, 12])
    def test_the_other_months_are_outside(self, month):
        assert is_within_provision_period(datetime(2026, month, 15)) is False

    def test_the_judgement_is_by_month_not_by_day(self):
        """開始日・終了日は年ごとに動く（例年4月第4水曜〜10月第3水曜）。日で切ると毎年
        値を直すことになり、直し忘れた年だけ静かにずれる。
        """
        assert is_within_provision_period(datetime(2026, PROVISION_START_MONTH, 1)) is True
        assert is_within_provision_period(datetime(2026, PROVISION_END_MONTH, 31)) is True
