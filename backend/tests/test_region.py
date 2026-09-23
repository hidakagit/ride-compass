"""`domain/region.py`——矩形とXYZタイルの相互変換。

タイルの配信そのもの（ズーム範囲の拒否・中身の組み立て）は`test_region_routes.py`が持つ。
"""

import math

import pytest
from pydantic import ValidationError

from app.domain.region import (
    ROAD_GRAPH_TILE_ZOOM,
    BoundingBox,
    parse_bbox,
    tile_bounds_lonlat,
    tiles_covering_bbox,
)

# 東京付近のz12タイル。
TOKYO_TILE = (12, 3637, 1612)


class TestParseBbox:

    def test_it_reads_four_values_in_latitude_first_order(self):
        bbox = parse_bbox("35.0,139.0,36.0,140.0")

        assert bbox == BoundingBox(
            min_latitude=35.0, min_longitude=139.0, max_latitude=36.0, max_longitude=140.0
        )

    def test_a_wrong_number_of_values_is_rejected(self):
        with pytest.raises(ValueError):
            parse_bbox("35.0,139.0,36.0")
        with pytest.raises(ValueError):
            parse_bbox("35.0,139.0,36.0,140.0,1.0")

    def test_a_non_numeric_value_is_rejected(self):
        with pytest.raises(ValueError):
            parse_bbox("35.0,139.0,north,140.0")


class TestBoundingBox:

    def test_a_range_that_is_not_increasing_is_rejected(self):
        """4値を並べて渡す形のため、minとmaxの入れ替わりは数としては通る。矩形として
        成立しないことをここで落とさないと、`tiles_covering_bbox`が昇順へ並べ直すぶんだけ
        「それらしいタイル一覧」になって、黙って別の場所を処理する。
        """
        with pytest.raises(ValidationError):
            BoundingBox(
                min_latitude=36.0, min_longitude=139.0, max_latitude=35.0, max_longitude=140.0
            )
        with pytest.raises(ValidationError):
            BoundingBox(
                min_latitude=35.0, min_longitude=140.0, max_latitude=36.0, max_longitude=139.0
            )
        with pytest.raises(ValidationError):
            BoundingBox(
                min_latitude=35.0, min_longitude=139.0, max_latitude=35.0, max_longitude=140.0
            )


class TestTileBoundsLonlat:

    def test_the_world_tile_covers_the_whole_mercator_extent(self):
        bounds = tile_bounds_lonlat(0, 0, 0)

        assert bounds.min_longitude == -180.0
        assert bounds.max_longitude == 180.0
        assert math.isclose(bounds.max_latitude, 85.0511, abs_tol=0.001)
        assert math.isclose(bounds.min_latitude, -85.0511, abs_tol=0.001)

    def test_y_increases_southwards(self):
        """取り違えると、南北が反転した範囲を取りに行く。"""
        upper = tile_bounds_lonlat(4, 7, 5)
        lower = tile_bounds_lonlat(4, 7, 6)

        assert upper.min_latitude > lower.max_latitude - 1e-9

    def test_x_increases_eastwards(self):
        west = tile_bounds_lonlat(4, 7, 5)
        east = tile_bounds_lonlat(4, 8, 5)

        assert east.min_longitude >= west.max_longitude - 1e-9

    def test_neighbouring_tiles_share_their_edge(self):
        """隙間が空くと、境界上の道路がどのタイルにも入らない。"""
        left = tile_bounds_lonlat(*TOKYO_TILE)
        right = tile_bounds_lonlat(TOKYO_TILE[0], TOKYO_TILE[1] + 1, TOKYO_TILE[2])

        assert left.max_longitude == right.min_longitude

    def test_the_tile_found_for_a_point_contains_that_point(self):
        """実在の地点（王子駅付近）で、点→タイル→範囲の往復が噛み合うことを見る。
        南北の向きを取り違えると、ここで点が範囲の外へ出る。
        """
        latitude, longitude = 35.7527, 139.7380
        spot = BoundingBox(
            min_latitude=latitude, min_longitude=longitude,
            max_latitude=latitude + 1e-9, max_longitude=longitude + 1e-9,
        )
        (x, y) = tiles_covering_bbox(spot, 14)[0]

        bounds = tile_bounds_lonlat(14, x, y)

        assert bounds.min_latitude <= latitude <= bounds.max_latitude
        assert bounds.min_longitude <= longitude <= bounds.max_longitude

    def test_the_bounds_are_increasing(self):
        bounds = tile_bounds_lonlat(*TOKYO_TILE)

        assert bounds.min_latitude < bounds.max_latitude
        assert bounds.min_longitude < bounds.max_longitude


class TestTilesCoveringBbox:

    def test_a_tile_s_own_bounds_always_include_that_tile(self):
        """変換と逆変換が噛み合っていることを往復で見る。**ちょうど1枚にはならない**——
        タイルの範囲は隣と辺を共有するため、端の座標は隣のタイルにも属する。
        """
        z, x, y = TOKYO_TILE

        assert (x, y) in tiles_covering_bbox(tile_bounds_lonlat(z, x, y), z)

    def test_a_box_strictly_inside_one_tile_returns_just_that_tile(self):
        z, x, y = TOKYO_TILE
        bounds = tile_bounds_lonlat(z, x, y)
        margin_lat = (bounds.max_latitude - bounds.min_latitude) / 4
        margin_lon = (bounds.max_longitude - bounds.min_longitude) / 4
        inside = BoundingBox(
            min_latitude=bounds.min_latitude + margin_lat,
            min_longitude=bounds.min_longitude + margin_lon,
            max_latitude=bounds.max_latitude - margin_lat,
            max_longitude=bounds.max_longitude - margin_lon,
        )

        assert tiles_covering_bbox(inside, z) == [(x, y)]

    def test_a_box_spanning_a_two_by_two_block_returns_all_four(self):
        """縦横どちらにもまたがる場合。片方の軸だけで範囲を出すと2枚しか返らない。"""
        z, x, y = TOKYO_TILE
        top_left = tile_bounds_lonlat(z, x, y)
        bottom_right = tile_bounds_lonlat(z, x + 1, y + 1)
        block = BoundingBox(
            min_latitude=(bottom_right.min_latitude + bottom_right.max_latitude) / 2,
            min_longitude=(top_left.min_longitude + top_left.max_longitude) / 2,
            max_latitude=(top_left.min_latitude + top_left.max_latitude) / 2,
            max_longitude=(bottom_right.min_longitude + bottom_right.max_longitude) / 2,
        )

        assert sorted(tiles_covering_bbox(block, z)) == [
            (x, y), (x, y + 1), (x + 1, y), (x + 1, y + 1)
        ]

    def test_the_whole_world_is_covered_at_a_coarse_zoom(self):
        world = BoundingBox(
            min_latitude=-85.0, min_longitude=-180.0, max_latitude=85.0, max_longitude=179.999
        )

        assert len(tiles_covering_bbox(world, 2)) == 16

    def test_latitudes_beyond_mercator_do_not_blow_up(self):
        beyond = BoundingBox(
            min_latitude=-90.0, min_longitude=-180.0, max_latitude=90.0, max_longitude=180.0
        )

        tiles = tiles_covering_bbox(beyond, 2)

        assert tiles
        assert all(0 <= x < 4 and 0 <= y < 4 for x, y in tiles)

    def test_every_returned_tile_is_inside_the_grid(self):
        tiles = tiles_covering_bbox(
            BoundingBox(min_latitude=35.0, min_longitude=139.0, max_latitude=36.0, max_longitude=140.0),
            ROAD_GRAPH_TILE_ZOOM,
        )
        n = 2**ROAD_GRAPH_TILE_ZOOM

        assert tiles
        assert all(0 <= x < n and 0 <= y < n for x, y in tiles)
