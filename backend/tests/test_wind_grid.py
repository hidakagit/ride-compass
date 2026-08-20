import pytest

from app.domain.wind_grid import WIND_GRID_BBOX, WIND_GRID_SPACING_DEG, WindGridPoint, generate_wind_grid_points


def test_generate_wind_grid_points_covers_bbox_bounds():
    points = generate_wind_grid_points()

    lats = [p.latitude for p in points]
    lons = [p.longitude for p in points]
    min_lon, min_lat, max_lon, max_lat = WIND_GRID_BBOX

    assert min(lats) == min_lat
    assert min(lons) == min_lon
    assert max(lats) <= max_lat
    assert max(lons) <= max_lon


def test_generate_wind_grid_points_uses_expected_spacing():
    points = generate_wind_grid_points()
    lats = sorted({p.latitude for p in points})

    assert len(lats) >= 2
    assert lats[1] - lats[0] == pytest.approx(WIND_GRID_SPACING_DEG)


def test_generate_wind_grid_points_is_deterministic():
    assert generate_wind_grid_points() == generate_wind_grid_points()


def test_generate_wind_grid_points_custom_bbox_and_spacing():
    points = generate_wind_grid_points(bbox=(139.0, 35.0, 140.0, 36.0), spacing_deg=0.5)

    # 経度: 139.0, 139.5, 140.0（3点）、緯度: 35.0, 35.5, 36.0（3点） -> 9点
    assert len(points) == 9
    assert {p.longitude for p in points} == {139.0, 139.5, 140.0}
    assert {p.latitude for p in points} == {35.0, 35.5, 36.0}


def test_wind_grid_point_model_round_trip():
    point = WindGridPoint(
        latitude=35.68,
        longitude=139.77,
        times=["2026-08-20T12:00"],
        wind_speed_ms=[2.5],
        wind_direction_deg=[90.0],
    )
    assert point.model_dump()["latitude"] == 35.68
