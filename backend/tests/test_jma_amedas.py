"""`domain/jma_amedas.py`——アメダスの風向コードの読み替え・体感温度。

入口は`wind_direction_from_jma_code`・`apparent_temperature_from_amedas`。

ここで見ないもの:
- 実測から天気コードを導く規則（`domain/weather.py: derive_observed_weather_code`） → `test_weather_service.py`。
  観測値と推計気象分布の空がその規則へ渡り、応答に出ること → `test_jma_amedas_service.py`
- 16方位の呼び名の並び（`domain/geo.py: SIXTEEN_POINT_LABELS`） → `test_geo.py`
- 観測値を集めて組み立てること → `test_jma_amedas_service.py`
"""

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.jma_amedas import apparent_temperature_from_amedas, wind_direction_from_jma_code


@pytest.mark.parametrize(
    ("code", "deg", "label"),
    [(1, 22.5, "北北東"), (16, 0.0, "北")],
)
def test_jma_wind_codes_read_as_the_direction_the_wind_comes_from(code, deg, label):
    """気象庁の番号は1=北北東から時計回りで16=北。北は360度ではなく0度。"""
    direction = wind_direction_from_jma_code(code)
    assert direction is not None
    assert (direction.deg, direction.label) == (deg, label)


@pytest.mark.parametrize("code", [None, 0, 17])
def test_calm_missing_and_out_of_range_codes_have_no_direction(code):
    """0は静穏（方位不定）。範囲外を別の方位として出すと向かい風と追い風を取り違えさせる。"""
    assert wind_direction_from_jma_code(code) is None


def test_the_sixteen_codes_go_round_clockwise_in_equal_steps():
    degrees = [wind_direction_from_jma_code(code).deg for code in range(1, 17)]  # type: ignore[union-attr]
    steps = [(later - earlier) % 360 for earlier, later in zip(degrees, degrees[1:] + degrees[:1], strict=True)]
    assert steps == [22.5] * 16


@pytest.mark.parametrize(
    ("temperature", "humidity", "wind"), [(None, 50.0, 1.0), (20.0, None, 1.0), (20.0, 50.0, None)]
)
def test_apparent_temperature_needs_all_three_observations(temperature, humidity, wind):
    assert apparent_temperature_from_amedas(temperature, humidity, wind) is None


temperatures = st.floats(min_value=-20, max_value=40)
humidities = st.floats(min_value=0, max_value=100)
winds = st.floats(min_value=0, max_value=30)


@given(temperature=temperatures, humidity=humidities, wind=winds, more_wind=st.floats(min_value=0, max_value=10))
def test_each_metre_per_second_of_wind_lowers_apparent_temperature_by_0_7(temperature, humidity, wind, more_wind):
    """BOMの式の風の項は-0.70×風速。"""
    calm = apparent_temperature_from_amedas(temperature, humidity, wind)
    windier = apparent_temperature_from_amedas(temperature, humidity, wind + more_wind)
    assert calm is not None and windier is not None
    assert math.isclose(calm - windier, 0.7 * more_wind, abs_tol=1e-9)


@given(temperature=temperatures, wind=winds)
def test_bone_dry_air_feels_four_degrees_colder_than_the_wind_alone_makes_it(temperature, wind):
    """湿度0では水蒸気圧の項が消え、AT = Ta - 0.70×風速 - 4.00 だけが残る。"""
    apparent = apparent_temperature_from_amedas(temperature, 0.0, wind)
    assert apparent is not None
    assert math.isclose(apparent, temperature - 0.7 * wind - 4.0, abs_tol=1e-9)


@given(temperature=temperatures, humidity=humidities, more=st.floats(min_value=1, max_value=50), wind=winds)
def test_more_humid_air_feels_warmer(temperature, humidity, more, wind):
    drier = apparent_temperature_from_amedas(temperature, humidity, wind)
    humid = apparent_temperature_from_amedas(temperature, min(humidity + more, 100.0), wind)
    assert drier is not None and humid is not None
    assert humid >= drier


def test_saturated_still_air_matches_the_published_saturation_vapour_pressure():
    """湿度100%・無風では水蒸気圧が飽和水蒸気圧になる。30℃の飽和水蒸気圧は表の値で42.46hPa
    （水面上）で、AT = 30 + 0.33×42.46 - 4.00。"""
    assert apparent_temperature_from_amedas(30.0, 100.0, 0.0) == pytest.approx(30 + 0.33 * 42.46 - 4.0, abs=0.1)

