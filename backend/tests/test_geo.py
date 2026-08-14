import math

from app.domain.geo import (
    bearing_between,
    compass_label,
    destination_point,
    haversine_distance_km,
    sample_indices,
    sample_line_coordinates,
    sample_line_points,
)
from app.domain.route import Coordinates

EQUATOR = Coordinates(latitude=0.0, longitude=0.0)


def test_destination_point_north_moves_latitude_by_expected_amount():
    # 赤道上から北(bearing=0)に約111km進むと、緯度は約1度増える（1度 ≈ 地球周長/360 ≈ 111.2km）
    result = destination_point(EQUATOR, bearing_deg=0, distance_km=111.2)

    assert math.isclose(result.latitude, 1.0, abs_tol=0.01)
    assert math.isclose(result.longitude, 0.0, abs_tol=0.01)


def test_destination_point_east_moves_longitude_only():
    result = destination_point(EQUATOR, bearing_deg=90, distance_km=111.2)

    assert math.isclose(result.latitude, 0.0, abs_tol=0.01)
    assert math.isclose(result.longitude, 1.0, abs_tol=0.01)


def test_destination_point_zero_distance_returns_same_point():
    result = destination_point(EQUATOR, bearing_deg=45, distance_km=0)

    assert math.isclose(result.latitude, EQUATOR.latitude, abs_tol=1e-9)
    assert math.isclose(result.longitude, EQUATOR.longitude, abs_tol=1e-9)


def test_haversine_distance_km_matches_known_bearing_distance():
    # destination_pointで作った点との距離は、指定したdistance_kmとほぼ一致するはず
    point = destination_point(EQUATOR, bearing_deg=90, distance_km=111.2)

    assert math.isclose(haversine_distance_km(EQUATOR, point), 111.2, abs_tol=0.1)


def test_haversine_distance_km_zero_for_same_point():
    assert math.isclose(haversine_distance_km(EQUATOR, EQUATOR), 0.0, abs_tol=1e-9)


def make_line_geometry(count: int) -> dict:
    # 緯度・経度として有効な範囲(-90〜90 / -180〜180)に収まるよう、インデックスを小さく刻む
    # （このテストの目的はサンプリングのインデックス計算の検証であり、実在の座標である必要はない）。
    return {"type": "LineString", "coordinates": [[i * 0.5, i * 0.5] for i in range(count)]}


def test_sample_line_coordinates_includes_start_and_end():
    geometry = make_line_geometry(100)

    samples = sample_line_coordinates(geometry, sample_count=12)

    assert samples[0].longitude == 0.0
    assert samples[-1].longitude == 49.5
    assert len(samples) <= 12


def test_sample_line_coordinates_returns_all_points_when_fewer_than_sample_count():
    geometry = make_line_geometry(5)

    samples = sample_line_coordinates(geometry, sample_count=12)

    assert len(samples) == 5


def test_sample_indices_includes_first_and_last():
    indices = sample_indices(point_count=100, sample_count=12)

    assert indices[0] == 0
    assert indices[-1] == 99
    assert len(indices) <= 12


def test_sample_indices_returns_all_when_fewer_than_sample_count():
    indices = sample_indices(point_count=5, sample_count=12)

    assert indices == [0, 1, 2, 3, 4]


def test_sample_line_points_indices_match_sample_line_coordinates():
    geometry = make_line_geometry(100)

    coords = sample_line_coordinates(geometry, sample_count=12)
    indexed = sample_line_points(geometry, sample_count=12)

    assert [c for _, c in indexed] == coords
    assert [i for i, _ in indexed] == sample_indices(100, 12)


def test_bearing_between_matches_destination_point_north():
    point = destination_point(EQUATOR, bearing_deg=0, distance_km=111.2)

    assert math.isclose(bearing_between(EQUATOR, point), 0.0, abs_tol=0.01)


def test_bearing_between_matches_destination_point_east():
    point = destination_point(EQUATOR, bearing_deg=90, distance_km=111.2)

    assert math.isclose(bearing_between(EQUATOR, point), 90.0, abs_tol=0.01)


def test_bearing_between_matches_destination_point_southwest():
    point = destination_point(EQUATOR, bearing_deg=225, distance_km=111.2)

    assert math.isclose(bearing_between(EQUATOR, point), 225.0, abs_tol=0.01)


def test_bearing_between_zero_distance_is_zero():
    assert bearing_between(EQUATOR, EQUATOR) == 0.0


def test_compass_label_cardinal_directions():
    assert compass_label(0) == "北"
    assert compass_label(90) == "東"
    assert compass_label(180) == "南"
    assert compass_label(270) == "西"


def test_compass_label_wraps_around_360():
    assert compass_label(360) == "北"
    assert compass_label(-45 % 360) == "北西"


def test_compass_label_rounds_to_nearest_direction():
    # 69度は 北東(45) より 東(90) に近い（90との差21 < 45との差24）
    assert compass_label(69) == "東"
    # 20度は 北東(45) より 北(0) に近い（0との差20 < 45との差25）
    assert compass_label(20) == "北"
