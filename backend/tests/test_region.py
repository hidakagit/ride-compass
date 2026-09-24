"""`domain/region.py`——緯度経度の矩形（`BoundingBox`）と、XYZタイル（Web Mercator）との行き来。

ここで見ないもの:
- タイルのズーム範囲を使う配信の口 → `test_region_routes.py`
- 道路グラフのタイル単位の取得 → `test_road_graph_repository_contracts.py`等

タイルの期待値はWeb Mercatorの事実（z0の1枚が全世界・z1で4分割・yは北から南へ増える・緯度の上限約85.05度）から作る。
"""

import pytest
from pydantic import ValidationError

from app.domain import region

Box = region.BoundingBox


def _box(min_lat=35.0, min_lon=139.0, max_lat=36.0, max_lon=140.0) -> region.BoundingBox:
    return Box(min_latitude=min_lat, min_longitude=min_lon, max_latitude=max_lat, max_longitude=max_lon)


# ---- 矩形 ----


@pytest.mark.parametrize(
    "corners",
    [
        (-90.0, -180.0, 90.0, 180.0),  # 緯度・経度とも範囲の端ちょうど
        (35.0, 139.0, 35.000001, 139.000001),
    ],
)
def test_a_box_within_the_globe_with_increasing_edges_is_accepted(corners):
    _box(*corners)


@pytest.mark.parametrize(
    "corners",
    [
        (-90.1, 139.0, 36.0, 140.0),
        (35.0, 139.0, 90.1, 140.0),
        (35.0, -180.1, 36.0, 140.0),
        (35.0, 139.0, 36.0, 180.1),
    ],
)
def test_a_box_outside_the_globe_is_rejected(corners):
    with pytest.raises(ValidationError):
        _box(*corners)


@pytest.mark.parametrize(
    ("corners", "axis"),
    [
        ((36.0, 139.0, 35.0, 140.0), "緯度"),  # 南北の入れ替わり
        ((35.0, 139.0, 35.0, 140.0), "緯度"),  # 幅0
        ((35.0, 140.0, 36.0, 139.0), "経度"),  # 東西の入れ替わり
        ((35.0, 139.0, 36.0, 139.0), "経度"),
    ],
)
def test_a_box_whose_edges_do_not_increase_is_rejected_naming_the_axis(corners, axis):
    with pytest.raises(ValidationError, match=axis):
        _box(*corners)


# ---- CLIの--bbox ----


def test_the_cli_bbox_is_read_as_latitude_longitude_latitude_longitude():
    assert region.parse_bbox("35.1,139.2,35.3,139.4") == _box(35.1, 139.2, 35.3, 139.4)


@pytest.mark.parametrize("text", ["35.1,139.2,35.3", "35.1,139.2,35.3,139.4,1", "a,139.2,35.3,139.4"])
def test_a_cli_bbox_that_is_not_four_numbers_is_an_error(text):
    with pytest.raises(ValueError):
        region.parse_bbox(text)


def test_a_cli_bbox_with_swapped_values_is_rejected_by_the_box():
    with pytest.raises(ValidationError):
        region.parse_bbox("139.2,35.1,139.4,35.3")


# ---- タイル1枚の範囲 ----


def test_the_single_tile_at_zoom_zero_covers_the_whole_mercator_world():
    bounds = region.tile_bounds_lonlat(0, 0, 0)

    assert (bounds.min_longitude, bounds.max_longitude) == (-180.0, 180.0)
    assert bounds.max_latitude == pytest.approx(85.0511, abs=1e-4)
    assert bounds.min_latitude == pytest.approx(-85.0511, abs=1e-4)


@pytest.mark.parametrize(
    ("x", "y", "west", "east", "north_hemisphere"),
    [(0, 0, -180.0, 0.0, True), (1, 0, 0.0, 180.0, True), (0, 1, -180.0, 0.0, False), (1, 1, 0.0, 180.0, False)],
)
def test_zoom_one_splits_the_world_into_quadrants_with_y_growing_southwards(x, y, west, east, north_hemisphere):
    bounds = region.tile_bounds_lonlat(1, x, y)

    assert (bounds.min_longitude, bounds.max_longitude) == (west, east)
    assert (bounds.min_latitude >= 0.0) is north_hemisphere
    assert (bounds.max_latitude <= 0.0) is not north_hemisphere


def test_neighbouring_tiles_share_their_edges():
    tile = region.tile_bounds_lonlat(12, 3637, 1612)
    east = region.tile_bounds_lonlat(12, 3638, 1612)
    south = region.tile_bounds_lonlat(12, 3637, 1613)

    assert east.min_longitude == tile.max_longitude
    assert south.max_latitude == pytest.approx(tile.min_latitude)


# ---- 矩形を覆うタイル ----


def _shrunk(bounds: region.BoundingBox, margin: float = 1e-6) -> region.BoundingBox:
    return _box(
        bounds.min_latitude + margin,
        bounds.min_longitude + margin,
        bounds.max_latitude - margin,
        bounds.max_longitude - margin,
    )


@pytest.mark.parametrize(("z", "x", "y"), [(0, 0, 0), (12, 3637, 1612), (15, 29100, 12900)])
def test_a_box_inside_one_tile_is_covered_by_that_tile_alone(z, x, y):
    assert region.tiles_covering_bbox(_shrunk(region.tile_bounds_lonlat(z, x, y)), z) == [(x, y)]


@pytest.mark.parametrize(("z", "x", "y"), [(1, 0, 0), (12, 3637, 1612), (15, 29100, 12900)])
def test_a_box_whose_east_and_south_edges_lie_on_tile_edges_also_takes_the_neighbours_there(z, x, y):
    assert region.tiles_covering_bbox(region.tile_bounds_lonlat(z, x, y), z) == [
        (x, y),
        (x, y + 1),
        (x + 1, y),
        (x + 1, y + 1),
    ]


def test_a_box_across_a_tile_corner_is_covered_by_the_four_tiles_around_it():
    tile = region.tile_bounds_lonlat(12, 3637, 1612)
    corner_lat, corner_lon = tile.min_latitude, tile.max_longitude  # 南東の角
    box = _box(corner_lat - 0.001, corner_lon - 0.001, corner_lat + 0.001, corner_lon + 0.001)

    assert region.tiles_covering_bbox(box, 12) == [(3637, 1612), (3637, 1613), (3638, 1612), (3638, 1613)]


def test_the_whole_globe_is_covered_by_every_tile_of_the_zoom_without_error():
    # 極（±90度）はWeb Mercatorで表せないので、表せる緯度の限界へ寄せてから求める
    tiles = region.tiles_covering_bbox(_box(-90.0, -180.0, 90.0, 180.0), 2)

    assert sorted(tiles) == [(x, y) for x in range(4) for y in range(4)]
