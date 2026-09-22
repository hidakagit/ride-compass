"""`domain/msm.py`——気象庁MSM格子の幾何と補間。

実データの同期・読み出しは`test_msm_freshness.py`が持つ。
"""

import numpy as np
import pytest

from app.domain.msm import MsmGrid, parse_bbox, wind_speed_and_direction

# 南30度・西120度から、0.5度刻みで5×5の格子。
GRID = MsmGrid(lat_min=30.0, lon_min=120.0, d_lat=0.5, d_lon=0.5, n_lat=5, n_lon=5)


class TestParseBbox:
    def test_the_values_come_back_in_south_west_north_east_order(self):
        """緯度経度の組で読むと、南北と東西が入れ替わる。"""
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


class TestWindow:
    def test_it_takes_one_extra_row_and_column_beyond_the_point(self):
        """ぴったり切ると、端の地点で索引が外れる。"""
        window = GRID.window(np.array([30.2]), np.array([120.2]))

        assert (window.i0, window.i1) == (0, 2)
        assert (window.j0, window.j1) == (0, 2)

    def test_it_covers_every_point_in_the_set(self):
        window = GRID.window(np.array([30.2, 31.6]), np.array([120.2, 121.8]))

        assert window.i0 == 0 and window.i1 >= 4
        assert window.j0 == 0 and window.j1 >= 4

    def test_the_far_corner_does_not_run_past_the_grid(self):
        """端の地点も引けなければならない。余分の1つを無条件に足すと格子をはみ出す。"""
        window = GRID.window(np.array([32.0]), np.array([122.0]))

        assert window.i1 <= GRID.n_lat
        assert window.j1 <= GRID.n_lon

    def test_the_slices_cut_exactly_the_window(self):
        window = GRID.window(np.array([30.2]), np.array([120.2]))

        assert (window.lat_slice, window.lon_slice) == (slice(0, 2), slice(0, 2))

    @pytest.mark.parametrize(
        ("latitudes", "longitudes"),
        [
            (np.array([31.0, 99.0]), np.array([121.0, 121.0])),
            (np.array([31.0]), np.array([999.0])),
        ],
    )
    def test_a_point_outside_the_grid_is_rejected(self, latitudes, longitudes):
        """1点でも外なら補間できない。部分的に返すと、どの地点が欠けたか呼び出し側が
        分からない。
        """
        with pytest.raises(ValueError):
            GRID.window(latitudes, longitudes)


class TestInterpolatePoints:
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
        result = GRID.window(np.array([30.0]), np.array([120.0])).interpolate(self._block())

        assert result.tolist() == [[0.0, 0.0]]

    def test_a_point_halfway_averages_the_four_corners(self):
        result = GRID.window(np.array([30.25]), np.array([120.25])).interpolate(self._block())

        assert result.tolist() == [[0.5, 0.5]]

    def test_the_weights_follow_each_axis_separately(self):
        """緯度と経度の重みを取り違えると、南北と東西が入れ替わった値になる。"""
        result = GRID.window(np.array([30.25]), np.array([120.0])).interpolate(self._block())

        assert result.tolist() == [[0.5, 0.0]]

    def test_the_block_offset_is_taken_into_account(self):
        """全体格子の原点からの索引で引くと、切り出したブロックの範囲外になる。"""
        window = GRID.window(np.array([31.0]), np.array([121.0]))

        assert (window.i0, window.j0) == (2, 2)
        assert window.interpolate(self._block()).tolist() == [[0.0, 0.0]]

    def test_it_returns_one_series_per_point(self):
        window = GRID.window(np.array([30.0, 30.25]), np.array([120.0, 120.25]))

        assert window.interpolate(self._block()).shape == (2, 2)


class TestWindSpeedAndDirection:
    def test_the_speed_is_the_length_of_the_vector(self):
        speed, _ = wind_speed_and_direction(np.array([3.0]), np.array([4.0]))

        assert speed.tolist() == [5.0]

    def test_the_direction_is_where_the_wind_comes_from(self):
        """吹いていく方位で返すと、向かい風と追い風が入れ替わる。南向きの成分だけの風は
        「北から吹いてくる」。
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
