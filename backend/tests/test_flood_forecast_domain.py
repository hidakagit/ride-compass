from app.domain.flood_forecast import extract_active_flood_forecast


def _entry(code: str, *, class20_codes=None, class10_codes=None, river_name="神田川", river_code="830304004400"):
    return {
        "reportDatetime": "2026-08-22T17:50:00+09:00",
        "item": {"name": "レベル４氾濫危険警報", "code": code, "condition": "レベル４氾濫危険警報（発表）"},
        "riverCode": river_code,
        "riverName": river_name,
        "class20Codes": class20_codes if class20_codes is not None else ["1310100"],
        "class10Codes": class10_codes if class10_codes is not None else ["130010"],
    }


def test_extract_returns_none_for_cleared_code():
    assert extract_active_flood_forecast(_entry("10"), "1310100", "130010") is None


def test_extract_returns_none_for_unknown_code():
    assert extract_active_flood_forecast(_entry("99"), "1310100", "130010") is None


def test_extract_returns_none_when_area_does_not_match():
    result = extract_active_flood_forecast(_entry("40"), "9999999", "999999")
    assert result is None


def test_extract_matches_via_class20_code():
    result = extract_active_flood_forecast(_entry("40"), "1310100", "999999")
    assert result is not None
    assert result.level == 4
    assert result.badge_level == "severe_warning"
    assert result.label == "神田川氾濫危険警報"
    assert result.river_code == "830304004400"


def test_extract_matches_via_class10_code_fallback():
    result = extract_active_flood_forecast(_entry("40"), "9999999", "130010")
    assert result is not None
    assert result.level == 4


def test_extract_level2_maps_to_advisory():
    result = extract_active_flood_forecast(_entry("21"), "1310100", "130010")
    assert result.level == 2
    assert result.badge_level == "advisory"
    assert result.label == "神田川氾濫注意報"


def test_extract_level3_maps_to_warning():
    result = extract_active_flood_forecast(_entry("31"), "1310100", "130010")
    assert result.level == 3
    assert result.badge_level == "warning"


def test_extract_level5_maps_to_emergency_warning():
    result = extract_active_flood_forecast(_entry("51"), "1310100", "130010")
    assert result.level == 5
    assert result.badge_level == "emergency_warning"
    assert result.label == "神田川氾濫特別警報"


def test_extract_level5_flood_water_forecast_variant_also_maps():
    result = extract_active_flood_forecast(_entry("53"), "1310100", "130010")
    assert result.level == 5
    assert result.badge_level == "emergency_warning"
