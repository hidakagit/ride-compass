import math

import numpy as np

from app.domain.geo import bearing_between, bearing_between_array, compass_label, haversine_distance_km
from app.domain.route import Coordinates
from tests.geo_fixtures import destination_point

EQUATOR = Coordinates(latitude=0.0, longitude=0.0)


def test_haversine_distance_km_matches_known_bearing_distance():
    # destination_point（テスト専用ヘルパー、tests/geo_fixtures.py）で作った点との距離は、
    # 指定したdistance_kmとほぼ一致するはず
    point = destination_point(EQUATOR, bearing_deg=90, distance_km=111.2)

    assert math.isclose(haversine_distance_km(EQUATOR, point), 111.2, abs_tol=0.1)


def test_haversine_distance_km_zero_for_same_point():
    assert math.isclose(haversine_distance_km(EQUATOR, EQUATOR), 0.0, abs_tol=1e-9)


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


def test_bearing_between_array_matches_scalar_version():
    # 改善計画T554: bearing_between_arrayはbearing_betweenのベクトル化版で、同じ
    # (origin, destination)ペアに対して同じ値を返すはず。
    points = [
        destination_point(EQUATOR, bearing_deg=deg, distance_km=111.2) for deg in (0, 90, 225)
    ]
    lat = np.array([p.latitude for p in points])
    lon = np.array([p.longitude for p in points])

    result = bearing_between_array(EQUATOR, lat, lon)

    for value, point in zip(result, points):
        assert math.isclose(value, bearing_between(EQUATOR, point), abs_tol=0.01)


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
