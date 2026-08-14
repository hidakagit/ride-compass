import math

from app.domain.wind import WindCalculator


def test_headwind_gives_maximum_positive_penalty():
    # 北(0)に向かって走行中、北から風が吹いてくる＝真正面からの向かい風
    penalty = WindCalculator.wind_penalty(wind_speed_ms=5.0, wind_direction_deg=0, travel_bearing_deg=0)

    assert math.isclose(penalty, 5.0, abs_tol=1e-9)


def test_tailwind_gives_maximum_negative_penalty():
    # 北(0)に向かって走行中、南から風が吹いてくる＝背後からの追い風
    penalty = WindCalculator.wind_penalty(wind_speed_ms=5.0, wind_direction_deg=180, travel_bearing_deg=0)

    assert math.isclose(penalty, -5.0, abs_tol=1e-9)


def test_crosswind_gives_zero_penalty():
    # 北(0)に向かって走行中、東から風が吹いてくる＝真横からの風
    penalty = WindCalculator.wind_penalty(wind_speed_ms=5.0, wind_direction_deg=90, travel_bearing_deg=0)

    assert math.isclose(penalty, 0.0, abs_tol=1e-9)


def test_no_wind_gives_zero_penalty_regardless_of_direction():
    penalty = WindCalculator.wind_penalty(wind_speed_ms=0.0, wind_direction_deg=45, travel_bearing_deg=270)

    assert penalty == 0.0
