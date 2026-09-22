"""`domain/wind_grid.py`——風・降水を描くための格子点を作る。

外部APIは叩かない純粋な座標生成だけ。値の取得は`test_weather_service.py`、
配信は`test_weather_route.py`が持つ。

**この層の要は「格子の絶対座標が閲覧位置に依存しないこと」**——依存すると、近い場所を
見ている別の利用者とキャッシュを共有できなくなる（鍵は丸めた緯度経度）。
"""

import pytest

from app.domain.route import Coordinates
from app.domain.wind_grid import (
    WIND_GRID_BBOX,
    WIND_GRID_DETAIL_ALLOWED_SPACINGS_DEG,
    WIND_GRID_DETAIL_MAX_POINTS,
    WIND_GRID_SPACING_DEG,
    generate_wind_grid_detail_points,
    generate_wind_grid_points,
    nearest_grid_point,
)

MIN_LON, MIN_LAT, MAX_LON, MAX_LAT = WIND_GRID_BBOX
SMALL_BBOX = (10.0, 20.0, 10.5, 20.5)  # (min_lon, min_lat, max_lon, max_lat)


class TestGenerateWindGridPoints:
    def test_the_points_start_at_the_south_west_corner(self):
        points = generate_wind_grid_points(SMALL_BBOX, spacing_deg=0.1)

        assert points[0] == Coordinates(latitude=20.0, longitude=10.0)

    def test_the_spacing_is_kept_along_both_axes(self):
        points = generate_wind_grid_points(SMALL_BBOX, spacing_deg=0.1)
        latitudes = sorted({p.latitude for p in points})
        longitudes = sorted({p.longitude for p in points})

        assert latitudes == [20.0, 20.1, 20.2, 20.3, 20.4, 20.5]
        assert longitudes == [10.0, 10.1, 10.2, 10.3, 10.4, 10.5]

    def test_the_coordinates_do_not_drift(self):
        """歩幅を足し込むと浮動小数の誤差が溜まり、遠い格子点ほど絶対座標がずれる。
        整数のステップ数から都度計算し、丸めた値が同じになるようにする。
        """
        points = generate_wind_grid_points((10.0, 20.0, 12.0, 22.0), spacing_deg=0.1)

        assert all(round(p.latitude, 4) == p.latitude for p in points)
        assert Coordinates(latitude=22.0, longitude=12.0) in points

    def test_every_point_is_inside_the_box(self):
        points = generate_wind_grid_points(SMALL_BBOX, spacing_deg=0.1)

        assert points
        for p in points:
            assert 20.0 <= p.latitude <= 20.5
            assert 10.0 <= p.longitude <= 10.5

    def test_a_coarser_spacing_gives_fewer_points(self):
        assert len(generate_wind_grid_points(SMALL_BBOX, 0.2)) < len(
            generate_wind_grid_points(SMALL_BBOX, 0.1)
        )

    def test_the_default_box_and_spacing_produce_a_usable_grid(self):
        points = generate_wind_grid_points()

        assert points
        assert all(MIN_LAT <= p.latitude <= MAX_LAT for p in points)
        assert all(MIN_LON <= p.longitude <= MAX_LON for p in points)


class TestNearestGridPoint:
    """任意の座標を、固定ラティス上の点へ丸める。"""

    def test_a_point_is_rounded_to_the_nearest_node(self):
        near_origin = Coordinates(latitude=MIN_LAT + 0.04, longitude=MIN_LON + 0.04)
        past_half = Coordinates(latitude=MIN_LAT + 0.06, longitude=MIN_LON + 0.06)

        assert nearest_grid_point(near_origin) == Coordinates(latitude=MIN_LAT, longitude=MIN_LON)
        assert nearest_grid_point(past_half) == Coordinates(
            latitude=round(MIN_LAT + WIND_GRID_SPACING_DEG, 4),
            longitude=round(MIN_LON + WIND_GRID_SPACING_DEG, 4),
        )

    def test_nearby_points_collapse_onto_the_same_node(self):
        """タイル中心のような任意座標をそのまま使うと、隣り合うタイルごとに別の鍵になり、
        派生値のキャッシュが共有されない。
        """
        a = nearest_grid_point(Coordinates(latitude=MIN_LAT + 0.01, longitude=MIN_LON + 0.01))
        b = nearest_grid_point(Coordinates(latitude=MIN_LAT + 0.02, longitude=MIN_LON + 0.02))

        assert a == b

    def test_the_node_is_one_of_the_generated_points(self):
        """丸め先が生成側のラティスと違うと、値を持たない座標を引きに行く。"""
        node = nearest_grid_point(Coordinates(latitude=MIN_LAT + 0.37, longitude=MIN_LON + 0.44))

        assert node in generate_wind_grid_points()

    def test_a_node_maps_to_itself(self):
        """丸めが恒等でないと、同じ点を2回引くだけで別の鍵になる。"""
        node = generate_wind_grid_points()[17]

        assert nearest_grid_point(node) == node

    def test_a_point_outside_the_box_is_clamped_first(self):
        """境界付近の取りこぼしを避ける安全側の処理。範囲外を例外にすると、離島や県境の
        すぐ外を見ただけで風が出なくなる。
        """
        far_south_west = nearest_grid_point(Coordinates(latitude=0.0, longitude=0.0))
        far_north_east = nearest_grid_point(Coordinates(latitude=80.0, longitude=179.0))

        assert far_south_west == Coordinates(latitude=MIN_LAT, longitude=MIN_LON)
        assert MIN_LAT <= far_north_east.latitude <= MAX_LAT
        assert MIN_LON <= far_north_east.longitude <= MAX_LON


class TestGenerateWindGridDetailPoints:
    """表示中の範囲だけを細かい間隔で敷く。"""

    def test_the_lattice_is_anchored_to_the_fixed_origin(self):
        """**問い合わせbboxの角を起点にしない。** 閲覧位置が少しずれるだけで格子点の絶対
        座標が全部ずれ、近い場所を見ている別の利用者とキャッシュを共有できなくなる。
        """
        shifted = (MIN_LON + 0.103, MIN_LAT + 0.103, MIN_LON + 0.2, MIN_LAT + 0.2)

        points = generate_wind_grid_detail_points(shifted, spacing_deg=0.02)

        assert points
        for p in points:
            steps_lat = (p.latitude - MIN_LAT) / 0.02
            steps_lon = (p.longitude - MIN_LON) / 0.02
            assert abs(steps_lat - round(steps_lat)) < 1e-6
            assert abs(steps_lon - round(steps_lon)) < 1e-6

    def test_two_overlapping_views_share_their_points(self):
        a = generate_wind_grid_detail_points((MIN_LON, MIN_LAT, MIN_LON + 0.1, MIN_LAT + 0.1), 0.02)
        b = generate_wind_grid_detail_points(
            (MIN_LON + 0.03, MIN_LAT + 0.03, MIN_LON + 0.13, MIN_LAT + 0.13), 0.02
        )

        assert set((p.latitude, p.longitude) for p in a) & set((p.latitude, p.longitude) for p in b)

    def test_a_narrow_view_s_points_are_a_subset_of_a_wider_one(self):
        """狭い表示範囲の結果が、それを包む広い範囲の結果へ同じ座標で含まれる。含まれない
        なら、格子が表示範囲の角を起点にしている。
        """
        narrow = generate_wind_grid_detail_points(
            (MIN_LON + 0.05, MIN_LAT + 0.05, MIN_LON + 0.09, MIN_LAT + 0.09), 0.02
        )
        wide = generate_wind_grid_detail_points(
            (MIN_LON, MIN_LAT, MIN_LON + 0.2, MIN_LAT + 0.2), 0.02
        )

        assert narrow
        assert {(p.latitude, p.longitude) for p in narrow} <= {(p.latitude, p.longitude) for p in wide}

    def test_a_view_outside_the_covered_area_gives_no_points(self):
        assert generate_wind_grid_detail_points((0.0, 0.0, 1.0, 1.0)) == []

    def test_a_degenerate_view_gives_no_points(self):
        assert generate_wind_grid_detail_points((MIN_LON, MIN_LAT, MIN_LON, MIN_LAT)) == []

    def test_a_view_reaching_past_the_edge_is_clipped(self):
        """覆っていない範囲の点を返すと、値の無い座標を取りに行く。"""
        points = generate_wind_grid_detail_points(
            (MIN_LON - 1.0, MIN_LAT - 1.0, MIN_LON + 0.1, MIN_LAT + 0.1), 0.02
        )

        assert points
        for p in points:
            assert MIN_LAT <= p.latitude <= MAX_LAT
            assert MIN_LON <= p.longitude <= MAX_LON

    def test_a_view_reaching_past_the_far_edge_is_clipped(self):
        points = generate_wind_grid_detail_points(
            (MAX_LON - 0.1, MAX_LAT - 0.1, MAX_LON + 1.0, MAX_LAT + 1.0), 0.02
        )

        assert points
        for p in points:
            assert p.latitude <= MAX_LAT
            assert p.longitude <= MAX_LON

    def test_a_finer_spacing_gives_more_points(self):
        box = (MIN_LON, MIN_LAT, MIN_LON + 0.1, MIN_LAT + 0.1)

        assert len(generate_wind_grid_detail_points(box, 0.01)) > len(
            generate_wind_grid_detail_points(box, 0.02)
        )

    def test_it_does_not_cap_the_number_of_points_itself(self):
        """上限は呼び出し元が見る。ここで黙って間引くと、画面の一部だけ風が出なくなる。"""
        wide = generate_wind_grid_detail_points(WIND_GRID_BBOX, 0.02)

        assert len(wide) > WIND_GRID_DETAIL_MAX_POINTS


@pytest.mark.parametrize("spacing", WIND_GRID_DETAIL_ALLOWED_SPACINGS_DEG)
def test_every_allowed_spacing_divides_the_coarse_spacing(spacing):
    """細かい段階が粗い格子の点を含んでいれば、ズームを切り替えても同じ座標が使い回せる。"""
    steps = WIND_GRID_SPACING_DEG / spacing

    assert abs(steps - round(steps)) < 1e-9
