"""`domain/region.py`——緯度経度の矩形と、XYZタイル（Web Mercator）との行き来。

入口は`BoundingBox`・`bbox_covering_points`・`parse_bbox`・`tile_bounds_lonlat`・`tile_bounds_3857`・
`tiles_covering_bbox`。期待値はWeb Mercatorの公開の定義（WGS84の長半径6378137m・緯度の限界±85.0511度）と、
地球を半径6371kmの球とみなした距離から書き、実装の定数を掛け戻さない。

ここで見ないもの:
- `tile_position_sql`の式が地点を正しいタイルの位置へ写すこと → SQLを実行する標高の派生
  （`test_derive_elevation.py`）。ここでは式の文字列しか手に入らない
- 矩形の緯度経度の範囲（±90・±180）は`Field`の宣言が持つ
"""

import math
from typing import NamedTuple

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from app.domain.region import (
    BoundingBox,
    bbox_covering_points,
    parse_bbox,
    tile_bounds_3857,
    tile_bounds_lonlat,
    tiles_covering_bbox,
)

WGS84_SEMI_MAJOR_AXIS_M = 6378137.0
MERCATOR_LATITUDE_LIMIT = 85.0511287798
KM_PER_DEGREE_ON_A_6371KM_SPHERE = 2 * math.pi * 6371.0 / 360


class Point(NamedTuple):
    latitude: float
    longitude: float


def box(min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> BoundingBox:
    return BoundingBox(min_latitude=min_lat, min_longitude=min_lon, max_latitude=max_lat, max_longitude=max_lon)


# --- BoundingBox ---


@pytest.mark.parametrize(
    ("corners", "message"),
    [
        ((35.0, 139.0, 35.0, 139.1), "緯度はmin < maxが必要です"),
        ((35.0, 139.0, 35.1, 139.0), "経度はmin < maxが必要です"),
    ],
)
def test_a_box_with_empty_sides_is_rejected(corners, message):
    with pytest.raises(ValidationError, match=message):
        box(*corners)


# --- bbox_covering_points ---


def test_the_margin_extends_every_side_by_about_that_many_kilometers_converting_longitude_at_the_mean_latitude():
    covering = bbox_covering_points([Point(30.0, 139.0), Point(40.0, 140.0)], margin_km=10.0)

    km_per_degree_longitude = KM_PER_DEGREE_ON_A_6371KM_SPHERE * math.cos(math.radians(35.0))
    assert (30.0 - covering.min_latitude) * KM_PER_DEGREE_ON_A_6371KM_SPHERE == pytest.approx(10.0, rel=0.01)
    assert (covering.max_latitude - 40.0) * KM_PER_DEGREE_ON_A_6371KM_SPHERE == pytest.approx(10.0, rel=0.01)
    assert (139.0 - covering.min_longitude) * km_per_degree_longitude == pytest.approx(10.0, rel=0.01)
    assert (covering.max_longitude - 140.0) * km_per_degree_longitude == pytest.approx(10.0, rel=0.01)


# 日本の取込範囲を含む広さ。極・日付変更線をまたぐ矩形は`BoundingBox`が表せない。
japan_points = st.builds(
    Point,
    latitude=st.floats(min_value=20.0, max_value=46.0),
    longitude=st.floats(min_value=122.0, max_value=154.0),
)


@given(points=st.lists(japan_points, min_size=1, max_size=20), margin_km=st.floats(min_value=0.1, max_value=200.0))
def test_every_point_lies_inside_the_covering_box_with_the_margin_to_spare(points, margin_km):
    covering = bbox_covering_points(points, margin_km)

    margin_deg = margin_km / KM_PER_DEGREE_ON_A_6371KM_SPHERE / 1.01
    for point in points:
        assert covering.min_latitude + margin_deg < point.latitude < covering.max_latitude - margin_deg
        assert covering.min_longitude + margin_deg < point.longitude < covering.max_longitude - margin_deg


# --- parse_bbox ---


def test_parse_bbox_reads_min_lat_min_lon_max_lat_max_lon_in_that_order():
    assert parse_bbox("35.0, 139.0,35.5,139.5") == box(35.0, 139.0, 35.5, 139.5)


def test_parse_bbox_needs_exactly_four_values():
    with pytest.raises(ValueError, match="4値が必要です"):
        parse_bbox("35.0,139.0,35.5")


# --- tile_bounds_lonlat・tile_bounds_3857 ---


def _approx_box(actual: BoundingBox, expected: BoundingBox) -> bool:
    return actual.model_dump() == pytest.approx(expected.model_dump(), abs=1e-9)


def test_the_single_tile_at_zoom_0_covers_the_whole_mercator_world():
    world = box(-MERCATOR_LATITUDE_LIMIT, -180.0, MERCATOR_LATITUDE_LIMIT, 180.0)

    assert _approx_box(tile_bounds_lonlat(0, 0, 0), world)


def test_y_grows_southward_and_x_grows_eastward():
    """z1のx=1, y=0は北東の4分の1。"""
    assert _approx_box(tile_bounds_lonlat(1, 1, 0), box(0.0, 0.0, MERCATOR_LATITUDE_LIMIT, 180.0))


def mercator_m(longitude: float, latitude: float) -> tuple[float, float]:
    """EPSG:3857の順変換（球面メルカトル）。"""
    return (
        WGS84_SEMI_MAJOR_AXIS_M * math.radians(longitude),
        WGS84_SEMI_MAJOR_AXIS_M * math.log(math.tan(math.pi / 4 + math.radians(latitude) / 2)),
    )


tiles = st.integers(min_value=0, max_value=18).flatmap(
    lambda z: st.tuples(st.just(z), st.integers(0, 2**z - 1), st.integers(0, 2**z - 1))
)


@given(tile=tiles)
def test_the_lonlat_and_meter_bounds_of_a_tile_are_the_same_area(tile):
    lonlat = tile_bounds_lonlat(*tile)
    west, south, east, north = tile_bounds_3857(*tile)

    assert mercator_m(lonlat.min_longitude, lonlat.min_latitude) == pytest.approx((west, south), abs=1e-3)
    assert mercator_m(lonlat.max_longitude, lonlat.max_latitude) == pytest.approx((east, north), abs=1e-3)


@given(tile=tiles)
def test_neighboring_tiles_share_their_edges(tile):
    z, x, y = tile
    here = tile_bounds_lonlat(z, x, y)
    if x + 1 < 2**z:
        assert tile_bounds_lonlat(z, x + 1, y).min_longitude == here.max_longitude
    if y + 1 < 2**z:
        assert tile_bounds_lonlat(z, x, y + 1).max_latitude == here.min_latitude


# --- tiles_covering_bbox ---


def test_an_east_or_south_side_lying_on_a_tile_edge_also_takes_the_tile_beyond_it():
    """境目の上の点は東・南のタイルに属するとみなす（覆い漏れの無い側へ倒れる）。"""
    covering = tiles_covering_bbox(box(0.0, -10.0, 10.0, 0.0), 1)

    assert sorted(covering) == [(0, 0), (0, 1), (1, 0), (1, 1)]


def test_a_box_reaching_beyond_the_mercator_limits_stops_at_the_edge_of_the_world():
    assert sorted(tiles_covering_bbox(box(-90.0, -180.0, 90.0, 180.0), 1)) == [(0, 0), (0, 1), (1, 0), (1, 1)]


boxes_in_japan = st.tuples(
    st.floats(min_value=20.0, max_value=46.0),
    st.floats(min_value=0.001, max_value=1.0),
    st.floats(min_value=122.0, max_value=154.0),
    st.floats(min_value=0.001, max_value=1.0),
).map(lambda t: box(t[0], t[2], t[0] + t[1], t[2] + t[3]))


@given(bbox=boxes_in_japan, z=st.integers(min_value=8, max_value=15))
def test_the_tiles_are_exactly_the_block_of_tiles_the_box_touches(bbox, z):
    covering = tiles_covering_bbox(bbox, z)

    xs = sorted({x for x, _ in covering})
    ys = sorted({y for _, y in covering})
    assert len(covering) == len(xs) * len(ys)
    assert xs == list(range(xs[0], xs[-1] + 1)) and ys == list(range(ys[0], ys[-1] + 1))
    # 四隅はどれも、覆うタイルのどれかの中（境目を含む）にある。
    for latitude in (bbox.min_latitude, bbox.max_latitude):
        for longitude in (bbox.min_longitude, bbox.max_longitude):
            assert any(_contains(tile_bounds_lonlat(z, x, y), latitude, longitude) for x, y in covering)
    # 四方の端の列・行は、どれも矩形に触れている（余分な列・行が無い）。境目の上の点は東・南のタイルに入る。
    north_west, south_east = tile_bounds_lonlat(z, xs[0], ys[0]), tile_bounds_lonlat(z, xs[-1], ys[-1])
    assert north_west.max_longitude > bbox.min_longitude and south_east.min_longitude <= bbox.max_longitude
    assert north_west.min_latitude < bbox.max_latitude and south_east.max_latitude >= bbox.min_latitude


def _contains(bounds: BoundingBox, latitude: float, longitude: float) -> bool:
    return (
        bounds.min_latitude <= latitude <= bounds.max_latitude
        and bounds.min_longitude <= longitude <= bounds.max_longitude
    )
