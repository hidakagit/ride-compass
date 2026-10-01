"""`domain/geo.py`——球面上の距離・方位角と、方位の呼び名。

ここで見ないもの:
- 距離・方位を使う側（A*のヒューリスティック・風の向かい風成分）→ それぞれの持ち主のテスト

地点は`LatLonPoint`（このモジュールが持つ最小の緯度経度の型）で与える。期待値は球面幾何の事実
（赤道上の東西・子午線上の南北・4分の1周・対蹠点）から作り、式を書き写さない。
"""

import math
from typing import NamedTuple

import numpy as np
import pytest

from app.domain import geo

P = geo.LatLonPoint


# ---- 方位の呼び名 ----


def test_the_compass_names_are_all_different():
    assert len(set(geo.COMPASS_LABELS)) == len(geo.COMPASS_LABELS)


@pytest.mark.parametrize(("bearing", "name"), [(0.0, "北"), (90.0, "東"), (180.0, "南"), (270.0, "西")])
def test_the_four_cardinal_bearings_have_their_names(bearing, name):
    assert geo.compass_label(bearing) == name


@pytest.mark.parametrize("turns", [-2, -1, 1, 3])
def test_a_bearing_outside_one_turn_is_read_within_one_turn(turns):
    for bearing in (0.0, 45.0, 200.0):
        assert geo.compass_label(bearing + 360.0 * turns) == geo.compass_label(bearing)


def test_every_name_is_the_centre_of_its_own_sector():
    width = 360 / len(geo.COMPASS_LABELS)

    assert [geo.compass_label(i * width) for i in range(len(geo.COMPASS_LABELS))] == geo.COMPASS_LABELS


@pytest.mark.parametrize("sector", range(len(geo.COMPASS_LABELS)))
def test_a_bearing_exactly_on_a_sector_boundary_goes_to_the_next_sector(sector):
    # 偶数丸め（組み込みのround）だと、半分の区分の境界で下の区分へ倒れるものが出る
    width = 360 / len(geo.COMPASS_LABELS)
    boundary = sector * width + width / 2
    following = geo.COMPASS_LABELS[(sector + 1) % len(geo.COMPASS_LABELS)]

    assert geo.compass_label(boundary) == following
    assert geo.compass_label(boundary - 1e-9) == geo.COMPASS_LABELS[sector]


# ---- 方位角 ----


@pytest.mark.parametrize(
    ("destination", "bearing"),
    [
        (P(1.0, 0.0), 0.0),  # 子午線を北へ
        (P(0.0, 1.0), 90.0),  # 赤道を東へ
        (P(-1.0, 0.0), 180.0),
        (P(0.0, -1.0), 270.0),  # 西は負の角度にせず一周の内側で返す
    ],
)
def test_the_bearing_is_clockwise_from_north(destination, bearing):
    assert geo.bearing_between(P(0.0, 0.0), destination) == pytest.approx(bearing)


def test_a_point_seen_from_itself_is_due_north():
    assert geo.bearing_between(P(35.0, 139.0), P(35.0, 139.0)) == 0.0


def test_the_bearing_is_the_initial_direction_of_the_great_circle():
    # 北半球で真東の同緯度の地点へ向かう大円は、出発点では少し北を向く（等角航路の90度ではない）
    bearing = geo.bearing_between(P(35.0, 139.0), P(35.0, 140.0))

    assert 85.0 < bearing < 90.0


# ---- 距離 ----


def test_a_point_is_zero_away_from_itself():
    assert geo.haversine_distance_km(P(35.0, 139.0), P(35.0, 139.0)) == 0.0


def test_the_distance_is_the_same_both_ways():
    a, b = P(35.0, 139.0), P(34.2, 140.3)

    assert geo.haversine_distance_km(a, b) == pytest.approx(geo.haversine_distance_km(b, a))


@pytest.mark.parametrize(
    ("a", "b", "fraction_of_a_turn"),
    [
        (P(0.0, 0.0), P(90.0, 0.0), 0.25),  # 赤道から極まで
        (P(0.0, 0.0), P(0.0, 90.0), 0.25),  # 赤道を4分の1周
        (P(0.0, 0.0), P(0.0, 180.0), 0.5),  # 対蹠点
    ],
)
def test_distances_along_great_circles_are_fractions_of_the_circumference(a, b, fraction_of_a_turn):
    circumference = 2 * math.pi * geo.EARTH_RADIUS_KM

    assert geo.haversine_distance_km(a, b) == pytest.approx(circumference * fraction_of_a_turn)


def test_a_degree_along_the_equator_is_about_111_km():
    # 地球を平均半径6371kmの球とみなしたときの値。半径や単位（km）を取り違えると外れる
    assert geo.haversine_distance_km(P(0.0, 139.0), P(0.0, 140.0)) == pytest.approx(111.195, abs=0.001)


def test_the_rough_length_of_a_degree_of_latitude_is_close_to_the_true_one():
    # 目安の用途（索引の区切り・打ち切り）の値が、正確な距離から1%以上ずれていない
    true_length = geo.haversine_distance_km(P(0.0, 0.0), P(1.0, 0.0))

    assert geo.KM_PER_DEGREE_LATITUDE == pytest.approx(true_length, rel=0.01)


# ---- 緯度経度を持つ任意の型 ----


class _Node(NamedTuple):
    node_id: int
    latitude: float
    longitude: float


def test_anything_with_a_latitude_and_a_longitude_can_be_measured():
    assert geo.haversine_distance_km(_Node(1, 0.0, 0.0), P(0.0, 1.0)) == pytest.approx(
        geo.haversine_distance_km(P(0.0, 0.0), P(0.0, 1.0))
    )
    assert geo.bearing_between(_Node(1, 0.0, 0.0), _Node(2, 0.0, 1.0)) == pytest.approx(90.0)


# ---- 最寄りの点 ----


def test_nearest_point_matches_the_great_circle_nearest():
    """格子で候補を絞っても、全点と比べた球面の最寄りと同じ点になる。地点を密に撒き、候補が2つ以上
    残る格子（最寄りの境目の近く）にも多く当てる。"""
    rng = np.random.default_rng(0)
    station_lat = rng.uniform(34.0, 37.0, 300)
    station_lon = rng.uniform(138.0, 141.0, 300)
    lat = rng.uniform(34.5, 36.5, 20000)
    lon = rng.uniform(138.5, 140.5, 20000)

    phi1, phi2 = np.radians(lat)[:, None], np.radians(station_lat)[None, :]
    dphi = phi2 - phi1
    dlmb = np.radians(station_lon)[None, :] - np.radians(lon)[:, None]
    haversine = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlmb / 2) ** 2
    expected = np.argmin(haversine, axis=1)

    assert (geo.nearest_point_indices(lat, lon, station_lat, station_lon) == expected).all()


def _nearest(latitude, longitude, points):
    return geo.nearest_point_index(
        latitude, longitude, np.array([p.latitude for p in points]), np.array([p.longitude for p in points])
    )


def test_the_closest_point_is_chosen():
    assert _nearest(35.1, 139.1, [P(40.0, 145.0), P(35.0, 139.0)]) == 1


def test_an_empty_list_has_no_nearest_point():
    """既定の点へ倒さない——無関係な土地の観測値が出る。"""
    assert _nearest(35.0, 139.0, []) is None


def test_longitude_differences_shrink_with_latitude():
    """緯度45度では経度1度は緯度1度の約0.71倍の距離しかない。緯度経度の差をそのまま比べると
    両者は同距離に見え、先に並んでいる北の点が選ばれてしまう。
    """
    assert _nearest(45.0, 140.0, [P(46.0, 140.0), P(45.0, 141.0)]) == 1


def test_points_at_the_same_distance_go_to_the_one_listed_first():
    """赤道では経度1度と緯度1度が同じ距離になる。"""
    assert _nearest(0.0, 0.0, [P(1.0, 0.0), P(0.0, 1.0)]) == 0
    assert _nearest(0.0, 0.0, [P(0.0, 1.0), P(1.0, 0.0)]) == 0
