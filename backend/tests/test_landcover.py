from app.domain.landcover import (
    LULC_BUILT,
    LULC_CLOUDS,
    LULC_TREES,
    LULC_WATER,
    MIN_VALID_PIXELS,
    class_percentages,
)


def test_class_percentages_all_clouds_returns_none():
    assert class_percentages({LULC_CLOUDS: 100}) is None


def test_class_percentages_below_min_valid_pixels_returns_none():
    counts = {LULC_TREES: MIN_VALID_PIXELS - 1}
    assert class_percentages(counts) is None


def test_class_percentages_all_built_gives_hundred_percent_built():
    counts = {LULC_BUILT: 100}
    result = class_percentages(counts)
    assert result is not None
    assert result.valid_pixels == 100
    assert result.built_percent == 100.0
    assert result.trees_percent == 0.0
    assert result.water_percent == 0.0


def test_class_percentages_excludes_clouds_and_no_data_from_denominator():
    counts = {LULC_TREES: 50, LULC_WATER: 50, LULC_CLOUDS: 100, 0: 100}
    result = class_percentages(counts)
    assert result is not None
    # 有効画素はTrees+Waterの100のみ（Clouds・No Dataは分母から除外）。
    assert result.valid_pixels == 100
    assert result.trees_percent == 50.0
    assert result.water_percent == 50.0


def test_class_percentages_mixed_classes_sum_to_hundred():
    counts = {LULC_TREES: 30, LULC_BUILT: 20, LULC_WATER: 50}
    result = class_percentages(counts)
    assert result is not None
    total = (
        result.water_percent
        + result.trees_percent
        + result.flooded_veg_percent
        + result.crops_percent
        + result.built_percent
        + result.bare_percent
        + result.snow_ice_percent
        + result.rangeland_percent
    )
    assert total == 100.0
