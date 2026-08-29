import pytest

from app.domain.jma_amedas import (
    apparent_temperature_from_amedas,
    wind_direction_degrees_from_jma_code,
    wind_direction_label_from_jma_code,
)


def test_wind_direction_label_calm_and_none_return_none():
    assert wind_direction_label_from_jma_code(0) is None
    assert wind_direction_label_from_jma_code(None) is None


def test_wind_direction_label_maps_known_codes():
    assert wind_direction_label_from_jma_code(1) == "北北東"
    assert wind_direction_label_from_jma_code(16) == "北"
    assert wind_direction_label_from_jma_code(8) == "南"


def test_wind_direction_degrees_maps_known_codes():
    assert wind_direction_degrees_from_jma_code(0) is None
    assert wind_direction_degrees_from_jma_code(None) is None
    assert wind_direction_degrees_from_jma_code(1) == pytest.approx(22.5)
    assert wind_direction_degrees_from_jma_code(16) == 0
    assert wind_direction_degrees_from_jma_code(8) == pytest.approx(180.0)


def test_apparent_temperature_returns_none_when_any_input_missing():
    assert apparent_temperature_from_amedas(None, 70, 3.5) is None
    assert apparent_temperature_from_amedas(26.5, None, 3.5) is None
    assert apparent_temperature_from_amedas(26.5, 70, None) is None


def test_apparent_temperature_matches_bom_formula():
    # BOM Apparent Temperature式: AT = Ta + 0.33e - 0.70*ws - 4.00
    # e = (rh/100) * 6.105 * exp(17.27*Ta / (237.7+Ta))
    result = apparent_temperature_from_amedas(temperature_c=26.5, humidity_percent=70, wind_speed_ms=3.5)
    assert result == pytest.approx(28.0, abs=0.5)
