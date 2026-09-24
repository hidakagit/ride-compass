"""`domain/jma_amedas.py`——アメダスの風向コードの読み替えと、体感温度の計算。

ここで見ないもの:
- 観測値の取得と最寄り観測所の選び方 → `test_jma_amedas_service.py`
- 応答の形（`AmedasObservation`） → 型が保証する
"""

import pytest

from app.domain import jma_amedas


# ---- 風向コード（0=静穏、1〜16=16方位） ----


@pytest.mark.parametrize("code", [None, 0])
def test_calm_or_missing_has_no_direction(code):
    assert jma_amedas.wind_direction_from_jma_code(code) is None


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (4, (90.0, "東")),
        (8, (180.0, "南")),
        (12, (270.0, "西")),
        (16, (0.0, "北")),  # 一周して360度ではなく0度（北）
    ],
)
def test_the_cardinal_codes_point_the_way_the_jma_table_says(code, expected):
    assert jma_amedas.wind_direction_from_jma_code(code) == expected


def test_the_sixteen_codes_go_round_clockwise_in_equal_steps_with_distinct_names():
    directions = [jma_amedas.wind_direction_from_jma_code(code) for code in range(1, 17)]

    angles = [angle for angle, _ in directions]
    # 1（北北東）から時計回りに等間隔で進み、16で北（0度）へ戻る
    assert angles[:-1] == sorted(angles[:-1])
    assert len({round(b - a, 6) for a, b in zip(angles[:-1], angles[1:-1])}) == 1
    assert angles[-1] == 0.0
    assert len({label for _, label in directions}) == 16


# ---- 体感温度 ----


@pytest.mark.parametrize("missing", ["temperature_c", "humidity_percent", "wind_speed_ms"])
def test_apparent_temperature_needs_all_three_readings(missing):
    readings = {"temperature_c": 25.0, "humidity_percent": 60.0, "wind_speed_ms": 2.0, missing: None}

    assert jma_amedas.apparent_temperature_from_amedas(**readings) is None


def test_humid_air_feels_hotter():
    dry = jma_amedas.apparent_temperature_from_amedas(30.0, 30.0, 1.0)
    humid = jma_amedas.apparent_temperature_from_amedas(30.0, 80.0, 1.0)

    assert humid > dry


def test_each_metre_per_second_of_wind_feels_seven_tenths_of_a_degree_cooler():
    calm = jma_amedas.apparent_temperature_from_amedas(20.0, 50.0, 0.0)
    windy = jma_amedas.apparent_temperature_from_amedas(20.0, 50.0, 10.0)

    # 豪州気象局の式は風速について線形（係数0.70）
    assert calm - windy == pytest.approx(7.0)


def test_dry_calm_air_feels_four_degrees_cooler_than_the_thermometer():
    # 水蒸気圧0・風速0では、式の定数項（−4.00）だけが残る
    assert jma_amedas.apparent_temperature_from_amedas(20.0, 0.0, 0.0) == pytest.approx(16.0)
