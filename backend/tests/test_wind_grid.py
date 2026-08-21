import pytest

from app.domain.wind_grid import (
    WIND_GRID_BBOX,
    WIND_GRID_DETAIL_SPACING_DEG,
    WIND_GRID_SPACING_DEG,
    WindGridPoint,
    generate_wind_grid_detail_points,
    generate_wind_grid_points,
)


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


# 改善計画T180: 詳細格子（wind-grid-detail）のテスト。最も重要な性質は「bboxの角ではなく
# 固定原点からのラティスで座標を決める」ことによるキャッシュ共有効果なので、それを直接検証する。


def test_generate_wind_grid_detail_points_lattice_is_independent_of_query_bbox():
    # 格子点の絶対座標がbboxの角ではなく固定原点（WIND_GRID_BBOX）基準で決まることを、
    # 「小さいbboxの結果が、それを包含するより大きいbboxの結果に同じ座標で含まれる」
    # ことで確認する（＝2人のユーザーが少しずれた表示範囲を見ていても、重なる領域では
    # 同じ絶対座標の格子点になり、weather_client.pyのcache_keyでキャッシュを共有できる）。
    small = generate_wind_grid_detail_points((139.75, 35.75, 139.80, 35.80))
    large = generate_wind_grid_detail_points((139.70, 35.70, 139.90, 35.90))

    assert len(small) > 0
    large_coords = {(p.latitude, p.longitude) for p in large}
    for p in small:
        assert (p.latitude, p.longitude) in large_coords


def test_generate_wind_grid_detail_points_uses_expected_spacing():
    points = generate_wind_grid_detail_points((139.70, 35.70, 139.90, 35.90))
    lats = sorted({p.latitude for p in points})

    assert len(lats) >= 2
    assert lats[1] - lats[0] == pytest.approx(WIND_GRID_DETAIL_SPACING_DEG)


def test_generate_wind_grid_detail_points_clips_to_wind_grid_bbox():
    min_lon, min_lat, max_lon, max_lat = WIND_GRID_BBOX
    # WIND_GRID_BBOXを大きくはみ出すbboxを渡しても、範囲外の座標は含まれない。
    points = generate_wind_grid_detail_points((min_lon - 5, min_lat - 5, min_lon + 0.1, min_lat + 0.1))

    assert all(p.longitude >= min_lon and p.latitude >= min_lat for p in points)
    assert all(p.longitude <= max_lon and p.latitude <= max_lat for p in points)


def test_generate_wind_grid_detail_points_empty_bbox_outside_coverage_returns_empty():
    min_lon, min_lat, _max_lon, _max_lat = WIND_GRID_BBOX
    points = generate_wind_grid_detail_points((min_lon - 5, min_lat - 5, min_lon - 4, min_lat - 4))

    assert points == []


def test_generate_wind_grid_detail_points_is_deterministic():
    bbox = (139.70, 35.70, 139.90, 35.90)
    assert generate_wind_grid_detail_points(bbox) == generate_wind_grid_detail_points(bbox)


def test_wind_grid_point_model_round_trip():
    point = WindGridPoint(
        latitude=35.68,
        longitude=139.77,
        times=["2026-08-20T12:00"],
        wind_speed_ms=[2.5],
        wind_direction_deg=[90.0],
        precipitation_mm=[0.5],
    )
    assert point.model_dump()["latitude"] == 35.68
    assert point.model_dump()["precipitation_mm"] == [0.5]
