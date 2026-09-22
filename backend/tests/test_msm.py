"""`domain/msm.py`——気象庁MSM格子の幾何と補間。

実データの同期・読み出しは`test_msm_freshness.py`・`infrastructure/msm_client.py`側が持つ。
ここは外部I/Oを持たない純関数だけ。
"""

import numpy as np
import pytest

from app.domain.msm import MsmGrid, interpolate_points, parse_bbox, wind_speed_and_direction

# 南30度・西120度から、0.5度刻みで5×5の格子。
GRID = MsmGrid(lat_min=30.0, lon_min=120.0, d_lat=0.5, d_lon=0.5, n_lat=5, n_lon=5)


class TestParseBbox:
    """配信元メタ情報のWKTから範囲を取り出す。"""

    def test_the_values_come_back_in_south_west_north_east_order(self):
        """**WKTのBBOXは南・西・北・東の順**。緯度経度の組で読むと南北と東西が入れ替わる。"""
        assert parse_bbox("BBOX[22.4,120.0,47.6,150.0]") == (22.4, 120.0, 47.6, 150.0)

    def test_spaces_around_the_values_are_allowed(self):
        assert parse_bbox("BBOX[ 22.4 , 120.0 , 47.6 , 150.0 ]") == (22.4, 120.0, 47.6, 150.0)

    def test_negative_values_are_read(self):
        assert parse_bbox("BBOX[-10.5,-20.25,10.5,20.25]") == (-10.5, -20.25, 10.5, 20.25)

    def test_the_surrounding_text_does_not_matter(self):
        assert parse_bbox('GEOGCRS["x",BBOX[1.0,2.0,3.0,4.0]]') == (1.0, 2.0, 3.0, 4.0)

    def test_a_wkt_without_a_bbox_is_rejected(self):
        """既定の範囲へ倒すと、別の格子のメタ情報で全地点が静かにずれる。"""
        with pytest.raises(ValueError):
            parse_bbox('GEOGCRS["x"]')


class TestGridFromBboxAndShape:
    """原点と間隔は、配信元のbboxと実データの形状から導く。書き写すと、配信元が格子を
    変えたときにここだけ古い値が残る。"""

    def test_the_origin_is_the_south_west_corner(self):
        grid = MsmGrid.from_bbox_and_shape((30.0, 120.0, 32.0, 124.0), n_lat=5, n_lon=5)

        assert (grid.lat_min, grid.lon_min) == (30.0, 120.0)

    def test_the_spacing_spans_the_range_between_the_end_points(self):
        """格子点は両端を含む。`n`で割ると間隔が1つぶん短くなり、東西南北の端が欠ける。"""
        grid = MsmGrid.from_bbox_and_shape((30.0, 120.0, 32.0, 124.0), n_lat=5, n_lon=5)

        assert grid.d_lat == 0.5
        assert grid.d_lon == 1.0

    def test_a_shape_too_small_to_have_a_spacing_is_rejected(self):
        with pytest.raises(ValueError):
            MsmGrid.from_bbox_and_shape((30.0, 120.0, 32.0, 124.0), n_lat=1, n_lon=5)
        with pytest.raises(ValueError):
            MsmGrid.from_bbox_and_shape((30.0, 120.0, 32.0, 124.0), n_lat=5, n_lon=1)


class TestContains:
    def test_a_point_inside_is_contained(self):
        assert GRID.contains(np.array([31.0]), np.array([121.0])) is True

    def test_the_far_corner_is_still_inside(self):
        """上端は`lat_min + d_lat*(n-1)`。ここを外すと、格子の端の地点だけ値を引けない。"""
        assert GRID.contains(np.array([32.0]), np.array([122.0])) is True

    def test_one_point_outside_makes_the_whole_set_outside(self):
        """1点でも外なら補間できない。部分的に返すと、どの地点が欠けたか呼び出し側が
        分からない。
        """
        assert GRID.contains(np.array([31.0, 99.0]), np.array([121.0, 121.0])) is False
        assert GRID.contains(np.array([31.0]), np.array([999.0])) is False


class TestSliceBounds:
    """補間に要る部分ブロックの範囲。"""

    def test_it_takes_one_extra_row_and_column_beyond_the_point(self):
        """双一次補間は右上側の格子点も参照する。ぴったり切ると端の地点で索引が外れる。"""
        i0, i1, j0, j1 = GRID.slice_bounds(np.array([30.2]), np.array([120.2]))

        assert (i0, i1) == (0, 2)
        assert (j0, j1) == (0, 2)

    def test_it_covers_every_point_in_the_set(self):
        i0, i1, j0, j1 = GRID.slice_bounds(np.array([30.2, 31.6]), np.array([120.2, 121.8]))

        assert i0 == 0 and i1 >= 4
        assert j0 == 0 and j1 >= 4

    def test_it_does_not_run_past_the_grid(self):
        """上端の地点でも、全体の形状を超える索引を返さない。"""
        i0, i1, j0, j1 = GRID.slice_bounds(np.array([32.0]), np.array([122.0]))

        assert i1 <= GRID.n_lat
        assert j1 <= GRID.n_lon

    def test_a_point_outside_the_grid_is_rejected(self):
        with pytest.raises(ValueError):
            GRID.slice_bounds(np.array([99.0]), np.array([121.0]))


class TestInterpolatePoints:
    """部分ブロックから地点ごとの時系列を双一次補間で取り出す。"""

    @staticmethod
    def _block() -> np.ndarray:
        """[緯度, 経度, 時刻]。時刻0は緯度の索引、時刻1は経度の索引をそのまま値にする。"""
        block = np.zeros((2, 2, 2))
        for i in range(2):
            for j in range(2):
                block[i, j, 0] = float(i)
                block[i, j, 1] = float(j)
        return block

    def test_a_point_on_a_grid_node_takes_that_node_s_value(self):
        result = interpolate_points(self._block(), GRID, 0, 0, np.array([30.0]), np.array([120.0]))

        assert result.tolist() == [[0.0, 0.0]]

    def test_a_point_halfway_averages_the_four_corners(self):
        result = interpolate_points(self._block(), GRID, 0, 0, np.array([30.25]), np.array([120.25]))

        assert result.tolist() == [[0.5, 0.5]]

    def test_the_weights_follow_each_axis_separately(self):
        """緯度と経度の重みを取り違えると、南北と東西が入れ替わった値になる。"""
        result = interpolate_points(self._block(), GRID, 0, 0, np.array([30.25]), np.array([120.0]))

        assert result.tolist() == [[0.5, 0.0]]

    def test_the_block_offset_is_taken_into_account(self):
        """ブロックは全体格子の途中から切り出される。原点からの索引で引くと範囲外になる。"""
        result = interpolate_points(self._block(), GRID, 2, 2, np.array([31.0]), np.array([121.0]))

        assert result.tolist() == [[0.0, 0.0]]

    def test_it_returns_one_series_per_point(self):
        result = interpolate_points(
            self._block(), GRID, 0, 0, np.array([30.0, 30.25]), np.array([120.0, 120.25])
        )

        assert result.shape == (2, 2)


class TestWindSpeedAndDirection:
    """東西・南北成分から風速と風向を出す。"""

    def test_the_speed_is_the_length_of_the_vector(self):
        speed, _ = wind_speed_and_direction(np.array([3.0]), np.array([4.0]))

        assert speed.tolist() == [5.0]

    def test_the_direction_is_where_the_wind_comes_from(self):
        """**吹いてくる方位**（北=0、東=90）。吹いていく方位で返すと、向かい風と追い風が
        入れ替わる。南向きの成分だけの風は「北から吹いてくる」。
        """
        _, from_north = wind_speed_and_direction(np.array([0.0]), np.array([-1.0]))
        _, from_south = wind_speed_and_direction(np.array([0.0]), np.array([1.0]))
        _, from_west = wind_speed_and_direction(np.array([1.0]), np.array([0.0]))
        _, from_east = wind_speed_and_direction(np.array([-1.0]), np.array([0.0]))

        assert from_north.tolist() == [0.0]
        assert from_east.tolist() == [90.0]
        assert from_south.tolist() == [180.0]
        assert from_west.tolist() == [270.0]

    def test_the_direction_stays_inside_one_turn(self):
        u = np.array([1.0, -1.0, 0.5, -0.5, 0.0])
        v = np.array([1.0, -1.0, -0.5, 0.5, -1.0])

        _, direction = wind_speed_and_direction(u, v)

        assert np.all((direction >= 0.0) & (direction < 360.0))

    def test_calm_air_has_zero_speed(self):
        speed, _ = wind_speed_and_direction(np.array([0.0]), np.array([0.0]))

        assert speed.tolist() == [0.0]

    def test_it_works_element_by_element(self):
        speed, direction = wind_speed_and_direction(np.array([0.0, 3.0]), np.array([-1.0, 4.0]))

        assert speed.shape == (2,)
        assert direction.shape == (2,)
