"""`domain/geo.py`——球面の距離・方位・方位の呼び名と、多数の地点それぞれの最寄りの点。

入口は`km_per_degree_longitude`・`compass_label`・`bearing_between`（と配列版）・`haversine_distance_km`（と配列版）・
`nearest_point_indices`・`nearest_point_index`。距離の性質（同じ点で0・三角不等式）と最寄りが本当に最も近いことは
hypothesisで任意の地点について確かめ、絶対値は公開の事実（子午線の4分の1はおよそ1万km）と突き合わせる。

ここで見ないもの:
- 方位の呼び名と距離を画面の計算と揃えること → 生成物`geo-expectations.json`を通す画面のテスト
- 最寄りの点を雨・アメダス・暑さ指数の値へ使うこと → それぞれのサービスのテスト
"""

from typing import NamedTuple

import numpy as np
import pytest
from hypothesis import given
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


def test_a_degree_of_longitude_at_the_pole_is_still_positive():
    """この値で割る側（矩形の余白・索引のセル幅）が極でゼロ除算にならない。"""
    assert geo.km_per_degree_longitude(90.0) > 0
    assert geo.km_per_degree_longitude(-90.0) > 0


# --- compass_label ---


@pytest.mark.parametrize(
    ("bearing", "label"),
    [
        (0.0, "北"),
        (90.0, "東"),
        (180.0, "南"),
        (270.0, "西"),
        (22.4, "北"),
        (22.5, "北東"),  # 区分の境界ちょうどは上の区分へ倒す
        (67.5, "東"),
        (337.4, "北西"),
        (337.5, "北"),
        (360.0, "北"),
        (405.0, "北東"),
        (-45.0, "北西"),
    ],
)
def test_compass_label_names_the_eight_point_sector(bearing, label):
    assert geo.compass_label(bearing) == label


def test_every_sixteen_point_name_is_different():
    """同じ呼び名が2つあると、違う向きが画面で同じ名前になる（8方位の呼び名はこの1つおき）。"""
    assert len(set(geo.SIXTEEN_POINT_LABELS)) == len(geo.SIXTEEN_POINT_LABELS)


# --- bearing_between ---


@pytest.mark.parametrize(
    ("destination", "bearing"),
    [
        (Point(1.0, 0.0), 0.0),
        (Point(0.0, 1.0), 90.0),
        (Point(-1.0, 0.0), 180.0),
        (Point(0.0, -1.0), 270.0),
    ],
)
def test_bearing_between_measures_clockwise_from_north(destination, bearing):
    assert geo.bearing_between(Point(0.0, 0.0), destination) == pytest.approx(bearing)


def test_bearing_between_the_same_point_is_north():
    assert geo.bearing_between(Point(35.0, 139.0), Point(35.0, 139.0)) == 0.0


def test_the_initial_bearing_along_a_great_circle_leans_toward_the_pole():
    """同じ緯度の真東の地点へ向かう大円は、北半球では真東より北へ傾いて出る（平面の方位とは違う）。"""
    assert geo.bearing_between(Point(35.0, 139.0), Point(35.0, 149.0)) < 90.0


def test_bearing_between_array_answers_each_point_in_the_shape_given():
    bearings = geo.bearing_between_array(Point(0.0, 0.0), np.array([1.0, 0.0, -1.0, 0.0]), np.array([0.0, 1.0, 0.0, -1.0]))

    np.testing.assert_allclose(bearings, [0.0, 90.0, 180.0, 270.0], atol=1e-9)



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


def test_the_nearest_point_across_the_date_line_is_found():
    candidates = [Point(0.0, -179.99), Point(0.0, 179.0)]

    assert list(nearest([Point(0.0, 179.99)], candidates)) == [0]


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


@given(location=points, candidates=st.lists(points, min_size=1, max_size=20))
def test_nearest_point_index_answers_the_nearest_point(location, candidates):
    index = geo.nearest_point_index(
        location.latitude,
        location.longitude,
        np.array([p.latitude for p in candidates]),
        np.array([p.longitude for p in candidates]),
    )

    assert index is not None
    assert chosen_km(location, candidates, index) == pytest.approx(brute_force_nearest_km(location, candidates), abs=RESOLUTION_KM)
