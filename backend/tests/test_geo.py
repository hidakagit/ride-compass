import math

import numpy as np

import pytest

from app.domain.geo import (
    bearing_between,
    bearing_between_array,
    compass_label,
    curvature_deg_per_km,
    haversine_distance_km,
)
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


# frontendの二重実装（WindBearingSlider.tsx: cardinalLabel）と丸め規則を突き合わせる
# ドリフト検知。区分の境界はすべて上の区分へ倒す（half-up）——偶数丸めだと22.5°→「北」・
# 67.5°→「東」のように、同じ境界でも角度によって上下どちらへ倒れるかが変わる。
@pytest.mark.parametrize(
    ("bearing_deg", "expected"),
    [
        (22.5, "北東"),
        (67.5, "東"),
        (112.5, "南東"),
        (157.5, "南"),
        (202.5, "南西"),
        (247.5, "西"),
        (292.5, "北西"),
        (337.5, "北"),
    ],
)
def test_compass_label_rounds_boundaries_half_up(bearing_deg, expected):
    assert compass_label(bearing_deg) == expected


def test_compass_label_rounds_to_nearest_direction():
    # 69度は 北東(45) より 東(90) に近い（90との差21 < 45との差24）
    assert compass_label(69) == "東"
    # 20度は 北東(45) より 北(0) に近い（0との差20 < 45との差25）
    assert compass_label(20) == "北"


def test_curvature_is_zero_for_a_straight_line_and_large_for_a_zigzag():
    straight = [(35.700, 139.700), (35.710, 139.700), (35.720, 139.700)]
    zigzag = [(35.700, 139.700), (35.701, 139.701), (35.702, 139.700), (35.703, 139.701)]

    assert curvature_deg_per_km(straight, 2224.0) == pytest.approx(0.0, abs=0.5)
    assert curvature_deg_per_km(zigzag, 450.0) > 100


def test_curvature_is_practically_the_same_in_both_directions():
    """蛇行は方位変化の絶対値の累積のため、fwd/bwdのEdgeは実質同じ値になる。

    厳密には一致しない——大圏航路ではA→Bの初期方位とB→Aの逆方位がずれるため
    （`build_road_graph`がbearing_forward/backwardを+180度の反転ではなく別々に求めて
    いるのと同じ理由）。ずれは相対1e-4未満で、度/kmの目盛りでは無視できる。
    """
    points = [(35.700, 139.700), (35.701, 139.701), (35.702, 139.700), (35.703, 139.701)]

    forward = curvature_deg_per_km(points, 450.0)
    backward = curvature_deg_per_km(list(reversed(points)), 450.0)

    assert forward == pytest.approx(backward, rel=1e-4)


def test_curvature_is_none_when_it_cannot_be_measured():
    """頂点3点未満・距離0は0ではなくNone（「まっすぐ」と「測れない」を混同しない——
    0にすると未計算の区間が「まっすぐな良い道」として評価に混ざる）。"""
    assert curvature_deg_per_km([(35.70, 139.70), (35.71, 139.70)], 1112.0) is None
    assert curvature_deg_per_km([(35.70, 139.70), (35.71, 139.70), (35.72, 139.70)], 0.0) is None
    # 連続する同一頂点は方位が定まらないため間引く（残り2点になればNone）。
    assert curvature_deg_per_km([(35.70, 139.70), (35.70, 139.70), (35.70, 139.70)], 100.0) is None
