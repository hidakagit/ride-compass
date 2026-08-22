from datetime import datetime

from app.domain.wbgt import is_within_provision_period, wbgt_level


def test_wbgt_level_returns_none_below_21():
    assert wbgt_level(20.9) is None
    assert wbgt_level(0.0) is None


def test_wbgt_level_advisory_boundary():
    assert wbgt_level(21.0) == ("advisory", "注意")
    assert wbgt_level(24.9) == ("advisory", "注意")


def test_wbgt_level_warning_boundary():
    assert wbgt_level(25.0) == ("warning", "警戒")
    assert wbgt_level(27.9) == ("warning", "警戒")


def test_wbgt_level_severe_warning_boundary():
    assert wbgt_level(28.0) == ("severe_warning", "厳重警戒")
    assert wbgt_level(30.9) == ("severe_warning", "厳重警戒")


def test_wbgt_level_emergency_warning_boundary():
    assert wbgt_level(31.0) == ("emergency_warning", "危険")
    assert wbgt_level(40.0) == ("emergency_warning", "危険")


def test_is_within_provision_period_true_for_april_through_october():
    assert is_within_provision_period(datetime(2026, 4, 1))
    assert is_within_provision_period(datetime(2026, 8, 22))
    assert is_within_provision_period(datetime(2026, 10, 31))


def test_is_within_provision_period_false_outside_april_through_october():
    assert not is_within_provision_period(datetime(2026, 3, 31))
    assert not is_within_provision_period(datetime(2026, 11, 1))
    assert not is_within_provision_period(datetime(2026, 1, 1))
