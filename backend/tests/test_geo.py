"""`domain/geo.py`——球面の距離・方位・方位の呼び名と、多数の地点それぞれの最寄りの点。

入口は`km_per_degree_longitude`・`degrees_covering_m`・`compass_label`・`bearing_between`（と配列版）・`haversine_distance_km`（と配列版）・
`nearest_point_indices`・`nearest_point_index`。距離の性質（同じ点で0・三角不等式）・方位が別の道で求めた向きと合うこと・最寄りが本当に最も近いことは
hypothesisで任意の地点について確かめ、絶対値は公開の事実（子午線の4分の1はおよそ1万km）と突き合わせる。

ここで見ないもの:
- 方位の呼び名と距離を画面の計算と揃えること → 生成物`geo-expectations.json`を通す画面のテスト
- 最寄りの点を雨・アメダス・暑さ指数の値へ使うこと → それぞれのサービスのテスト
"""

import math
from typing import NamedTuple

import numpy as np
import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from app.domain import geo


class Point(NamedTuple):
    latitude: float
    longitude: float


latitudes = st.floats(min_value=-89.0, max_value=89.0)
longitudes = st.floats(min_value=-180.0, max_value=180.0)
points = st.builds(Point, latitude=latitudes, longitude=longitudes)


# --- km_per_degree_longitude ---


@given(latitude=st.floats(min_value=-80.0, max_value=80.0))
def test_the_rough_length_of_a_degree_stays_within_one_percent_of_the_true_distance(latitude):
    """目安の値（索引の区切り・矩形の余白）が、実際の距離から1%以上ずれない。赤道上の経度1度は緯度1度と同じ長さなので、
    緯度1度の目安もここで見る。"""
    true_km = geo.haversine_distance_km(Point(latitude, 0.0), Point(latitude, 1.0))

    assert geo.km_per_degree_longitude(latitude) == pytest.approx(true_km, rel=0.01)



# --- degrees_covering_m ---

# WGS84の楕円体（PostGISのgeographyが距離を測る面）の長半径（m）と離心率の2乗。
_WGS84_SEMI_MAJOR_M = 6378137.0
_WGS84_ECCENTRICITY_SQUARED = 0.00669437999014


def _wgs84_degree_lengths_m(latitude: float) -> tuple[float, float]:
    """楕円体の上の、緯度`latitude`での緯度1度・経度1度の長さ（m）。"""
    phi = math.radians(latitude)
    denominator = 1 - _WGS84_ECCENTRICITY_SQUARED * math.sin(phi) ** 2
    meridian_m = _WGS84_SEMI_MAJOR_M * (1 - _WGS84_ECCENTRICITY_SQUARED) / denominator ** 1.5
    prime_vertical_m = _WGS84_SEMI_MAJOR_M / math.sqrt(denominator)
    return math.radians(1) * meridian_m, math.radians(1) * prime_vertical_m * math.cos(phi)


@given(latitude=st.floats(min_value=-geo.COVERED_LATITUDE_LIMIT, max_value=geo.COVERED_LATITUDE_LIMIT))
@example(latitude=0.0)
@example(latitude=geo.COVERED_LATITUDE_LIMIT)
def test_the_box_in_degrees_is_no_narrower_than_the_radius_up_to_the_latitude_limit(latitude):
    """箱が距離より狭いと、SQLの前置フィルタが距離の判定の内側の行を黙って落とす。緯度1度は赤道で、
    経度1度は上限の緯度で最も短い。"""
    radius_m = 100.0
    degrees = geo.degrees_covering_m(radius_m)
    latitude_degree_m, longitude_degree_m = _wgs84_degree_lengths_m(latitude)

    assert degrees * latitude_degree_m >= radius_m
    assert degrees * longitude_degree_m >= radius_m


# --- compass_label ---


@pytest.mark.parametrize(
    ("bearing", "label"),
    [
        (90.0, "東"),
        (22.4, "北"),
        (22.5, "北東"),  # 区分の境界ちょうどは上の区分へ倒す
        (337.5, "北"),
        (360.0, "北"),
    ],
)
def test_compass_label_names_the_eight_point_sector(bearing, label):
    assert geo.compass_label(bearing) == label


def test_every_sixteen_point_name_is_different():
    """同じ呼び名が2つあると、違う向きが画面で同じ名前になる（8方位の呼び名はこの1つおき）。"""
    assert len(set(geo.SIXTEEN_POINT_LABELS)) == len(geo.SIXTEEN_POINT_LABELS)


# --- bearing_between ---


def tangent_plane_direction(origin: Point, destination: Point) -> tuple[float, float]:
    """方位を球面三角法の式とは別の道で求める: 目的地の位置ベクトルを、出発地で地面に接する平面の北向き・東向きの
    単位ベクトルへ射影した成分（北, 東）。長さは2点の中心角の正弦で、向きが定まらない出発地・対蹠点の近くでは0へ縮む。"""
    lat, lon = np.radians(origin.latitude), np.radians(origin.longitude)
    north = np.array([-np.sin(lat) * np.cos(lon), -np.sin(lat) * np.sin(lon), np.cos(lat)])
    east = np.array([-np.sin(lon), np.cos(lon), 0.0])
    to_lat, to_lon = np.radians(destination.latitude), np.radians(destination.longitude)
    target = np.array([np.cos(to_lat) * np.cos(to_lon), np.cos(to_lat) * np.sin(to_lon), np.sin(to_lat)])
    return float(target @ north), float(target @ east)


@given(origin=points, destinations=st.lists(points, min_size=1, max_size=10))
# 斜めの向きと緯度の違う2点（東西南北だけでは、式の掛け算を割り算にしても、引き算を足し算にしても答えが変わらない）。
@example(origin=Point(35.0, 139.0), destinations=[Point(36.0, 140.0), Point(34.0, 138.0), Point(35.0, 149.0)])
def test_the_bearing_agrees_with_the_direction_on_the_tangent_plane(origin, destinations):
    """向かい風・追い風の分け方は、走る向きの方位で決まる。斜めの向き・緯度の違う2点でも、北から時計回りの角度が
    別の道で求めた向きと合う（向きの定まらない2点は、比べる成分がどちらも0へ縮むので外さずに比べる）。"""
    bearings = geo.bearing_between_array(
        origin, np.array([p.latitude for p in destinations]), np.array([p.longitude for p in destinations])
    )

    assert bearings.shape == (len(destinations),)
    for destination, bearing in zip(destinations, bearings, strict=True):
        toward_north, toward_east = tangent_plane_direction(origin, destination)
        length = np.hypot(toward_north, toward_east)
        angle = np.radians(bearing)
        assert (length * np.cos(angle), length * np.sin(angle)) == pytest.approx((toward_north, toward_east), abs=1e-9)


def test_bearing_between_the_same_point_is_north():
    assert geo.bearing_between(Point(35.0, 139.0), Point(35.0, 139.0)) == 0.0


# --- haversine_distance_km ---


def test_a_quarter_meridian_is_about_ten_thousand_kilometers():
    """メートルは子午線の赤道から極までを1万kmとして決められた（球で近似するので1%以内で合わせる）。"""
    assert geo.haversine_distance_km(Point(0.0, 0.0), Point(90.0, 0.0)) == pytest.approx(10000.0, rel=0.01)


def test_haversine_distance_km_array_answers_each_point_in_the_shape_given():
    distances = geo.haversine_distance_km_array(np.array([0.0, 90.0]), np.array([0.0, 0.0]), Point(0.0, 0.0))

    np.testing.assert_allclose(distances, [0.0, geo.haversine_distance_km(Point(90.0, 0.0), Point(0.0, 0.0))])


@given(a=points)
def test_the_distance_from_a_point_to_itself_is_zero(a):
    """経路探索の見積もり（目的地までの球面距離）は、目的地で0でなければならない。"""
    assert geo.haversine_distance_km(a, a) == 0.0


@given(a=points, b=points, c=points)
def test_distance_satisfies_the_triangle_inequality(a, b, c):
    """経路探索の見積もりが、寄り道した見積もりより大きくならない（崩れると探索が最短を取り逃す）。"""
    assert geo.haversine_distance_km(a, c) <= geo.haversine_distance_km(a, b) + geo.haversine_distance_km(b, c) + 1e-6


# --- nearest_point_indices・nearest_point_index ---


# 最寄りは単位ベクトルの内積で比べるため、約10cmより近い差は区別しない（観測所の間隔に比べて無視できる）。
RESOLUTION_KM = 0.001


def brute_force_nearest_km(location: Point, candidates: list[Point]) -> float:
    return min(geo.haversine_distance_km(location, candidate) for candidate in candidates)


def chosen_km(location: Point, candidates: list[Point], index: int) -> float:
    return geo.haversine_distance_km(location, candidates[index])


def nearest(locations: list[Point], candidates: list[Point]) -> np.ndarray:
    return geo.nearest_point_indices(
        np.array([p.latitude for p in locations]),
        np.array([p.longitude for p in locations]),
        np.array([p.latitude for p in candidates]),
        np.array([p.longitude for p in candidates]),
    )


@given(locations=st.lists(points, min_size=1, max_size=40), candidates=st.lists(points, min_size=1, max_size=40))
# 日付変更線の向こうが最寄り。
@example(locations=[Point(0.0, 179.99)], candidates=[Point(0.0, -179.99), Point(0.0, 179.0)])
def test_each_location_gets_a_point_no_farther_than_any_other_anywhere_on_the_globe(locations, candidates):
    indices = nearest(locations, candidates)

    assert indices.shape == (len(locations),)
    for location, index in zip(locations, indices, strict=True):
        assert chosen_km(location, candidates, index) == pytest.approx(brute_force_nearest_km(location, candidates), abs=RESOLUTION_KM)


# 観測所の並び（十数km間隔）で、格子（0.01度）より細かく散らばる地点。最寄りが格子ごとに入れ替わる場面を作る。
dense_locations = st.builds(
    Point, latitude=st.floats(min_value=35.0, max_value=35.5), longitude=st.floats(min_value=139.0, max_value=139.5)
)


@given(locations=st.lists(dense_locations, min_size=1, max_size=200), candidates=st.lists(dense_locations, min_size=1, max_size=30))
# 地点が格子（35.00〜35.01度・139.00〜139.01度）の北東の角にあり、最寄りの点が角の外に、格子の中心に最も近い点が
# 南西にある。格子ごとの候補の余白が格子の1辺では最寄りを落とし、2辺で拾う。
@example(locations=[Point(35.0099, 139.0099)], candidates=[Point(35.004, 139.004), Point(35.0135, 139.0145)])
# 地点が格子の東の端にあり、最寄りの点が東の隣の格子のさらに外に、遠い点が西の隣の格子の中心にある（候補の余白を
# 地点の格子の中心から測らないと最寄りを落とす）。
@example(locations=[Point(35.005, 139.0099)], candidates=[Point(35.005, 138.995), Point(35.005, 139.021)])
def test_each_location_gets_the_nearest_point_where_points_are_dense(locations, candidates):
    indices = nearest(locations, candidates)

    for location, index in zip(locations, indices, strict=True):
        assert chosen_km(location, candidates, index) == pytest.approx(brute_force_nearest_km(location, candidates), abs=RESOLUTION_KM)


def test_locations_spread_over_many_cells_each_get_their_nearest_point():
    """格子をまとめて比べる刻み（数百の格子）を越える数の格子に地点が散らばっても、どの地点も最寄りを得る。"""
    rng = np.random.default_rng(0)
    locations = [Point(float(lat), float(lon)) for lat, lon in zip(rng.uniform(30, 40, 1500), rng.uniform(130, 140, 1500), strict=True)]
    candidates = [Point(float(lat), float(lon)) for lat, lon in zip(rng.uniform(30, 40, 60), rng.uniform(130, 140, 60), strict=True)]

    indices = nearest(locations, candidates)

    for location, index in zip(locations, indices, strict=True):
        assert chosen_km(location, candidates, index) == pytest.approx(brute_force_nearest_km(location, candidates), abs=RESOLUTION_KM)


def test_no_locations_give_no_indices():
    indices = geo.nearest_point_indices(np.array([]), np.array([]), np.array([35.0]), np.array([139.0]))

    assert indices.shape == (0,)


def test_nearest_point_index_has_no_answer_without_points():
    assert geo.nearest_point_index(35.0, 139.0, np.array([]), np.array([])) is None


@pytest.mark.parametrize("candidates", [[Point(0.0, 1.0), Point(0.0, -1.0)], [Point(0.0, -1.0), Point(0.0, 1.0)]])
def test_nearest_point_index_takes_the_first_listed_of_equally_near_points(candidates):
    index = geo.nearest_point_index(
        0.0, 0.0, np.array([p.latitude for p in candidates]), np.array([p.longitude for p in candidates])
    )

    assert index == 0
