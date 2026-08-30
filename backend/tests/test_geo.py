import math

from app.domain.geo import (
    bearing_between,
    compass_label,
    destination_point,
    haversine_distance_km,
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


def test_destination_point_normalizes_longitude_past_antimeridian():
    # 起点が日付変更線付近（例: フィジー近海）にあると、正規化前は経度が180度を
    # 超えCoordinatesのValidationErrorを送出していた（Coordinatesはge=-180/le=180）。
    origin = Coordinates(latitude=-17.7, longitude=179.95)

    result = destination_point(origin, bearing_deg=90, distance_km=10)

    assert -180.0 <= result.longitude <= 180.0
    # 東へ進んだ結果は日付変更線をまたいで-180近辺に折り返されるはず
    assert result.longitude < 0


def test_haversine_distance_km_matches_known_bearing_distance():
    # destination_pointで作った点との距離は、指定したdistance_kmとほぼ一致するはず
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
