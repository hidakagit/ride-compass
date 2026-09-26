"""`domain/wind.py`——風を走行方向へ分解し、追加負荷の材料にする。

風の予報をどこから取るかは`test_weather_service.py`、way単位の配信は
`test_wind_way_service.py`が持つ。ここで見るのは向きと大きさの扱い。
"""

from datetime import datetime, timedelta

import numpy as np
import pytest

from app.domain.route import Coordinates
from app.domain.wind import (
    ROUTE_DETOUR_RATIO,
    WIND_DRAG_REFERENCE_SPEED_MS,
    WindForecastSeries,
    WindLattice,
    estimate_passage_hours,
    kmh_to_ms,
    wind_components,
    wind_drag_ratio,
    wind_drag_ratio_array,
)

# 走行方位は北。風向は「吹いてくる方向」なので、北からの風が向かい風。
NORTHBOUND = 0.0
CRUISE_MS = 20.0 / 3.6


def test_speed_is_converted_from_kilometres_per_hour():
    assert kmh_to_ms(36.0) == 10.0


class TestWindComponents:

    def test_a_headwind_is_positive_along_the_route(self):
        along, cross = wind_components(5.0, NORTHBOUND, NORTHBOUND)

        assert along == pytest.approx(5.0)
        assert cross == pytest.approx(0.0, abs=1e-9)

    def test_a_tailwind_is_negative_along_the_route(self):
        along, _ = wind_components(5.0, 180.0, NORTHBOUND)

        assert along == pytest.approx(-5.0)

    def test_a_pure_crosswind_has_no_component_along_the_route(self):
        along, cross = wind_components(5.0, 90.0, NORTHBOUND)

        assert along == pytest.approx(0.0, abs=1e-9)
        assert abs(cross) == pytest.approx(5.0)

    def test_it_works_element_by_element(self):
        along, _ = wind_components(np.array([5.0, 5.0]), np.array([0.0, 180.0]), np.array([0.0, 0.0]))

        assert along.tolist() == pytest.approx([5.0, -5.0])


class TestWindDragRatio:

    def test_a_headwind_costs_and_a_tailwind_pays_back(self):
        head = wind_drag_ratio(5.0, NORTHBOUND, NORTHBOUND, CRUISE_MS)
        tail = wind_drag_ratio(5.0, 180.0, NORTHBOUND, CRUISE_MS)

        assert head > 0
        assert tail < 0

    def test_a_tailwind_as_fast_as_the_rider_cancels_the_still_air_drag(self):
        """追い風が走行速度と同じなら相対風速は0。基準速度で走っているとき、値は
        ちょうど −1（無風時の抵抗1つぶんが消える）になる。
        """
        value = wind_drag_ratio(
            WIND_DRAG_REFERENCE_SPEED_MS, 180.0, NORTHBOUND, WIND_DRAG_REFERENCE_SPEED_MS
        )

        assert value == pytest.approx(-1.0)

    @pytest.mark.parametrize("wind_speed", [0.0, 2.0, 5.0, 12.0])
    @pytest.mark.parametrize("relative_angle", [0.0, 180.0])
    def test_without_a_crosswind_it_matches_the_one_dimensional_form(self, wind_speed, relative_angle):
        """ここがずれると、追い風と向かい風で別の尺度になる。"""
        along = CRUISE_MS + wind_speed * np.cos(np.radians(relative_angle))
        expected = (np.sign(along) * along * along - CRUISE_MS**2) / WIND_DRAG_REFERENCE_SPEED_MS**2

        assert wind_drag_ratio(wind_speed, relative_angle, NORTHBOUND, CRUISE_MS) == pytest.approx(expected)

    def test_a_pure_crosswind_costs_a_little(self):
        """0にすると、横風の区間が無風と同じに見える。"""
        cross = wind_drag_ratio(5.0, 90.0, NORTHBOUND, CRUISE_MS)
        head = wind_drag_ratio(5.0, NORTHBOUND, NORTHBOUND, CRUISE_MS)

        assert 0 < cross < head

    def test_a_tailwind_stronger_than_the_rider_stays_finite(self):
        """1次元の`sign(x)x²`で書くとこの境界で折れる。"""
        values = [wind_drag_ratio(w, 180.0, NORTHBOUND, CRUISE_MS) for w in (4.0, 5.0, 6.0, 10.0, 20.0)]

        assert all(np.isfinite(values))
        assert values == sorted(values, reverse=True)

    def test_a_faster_rider_feels_the_same_wind_more(self):
        slow = wind_drag_ratio(5.0, NORTHBOUND, NORTHBOUND, kmh_to_ms(15.0))
        fast = wind_drag_ratio(5.0, NORTHBOUND, NORTHBOUND, kmh_to_ms(30.0))

        assert fast > slow

    def test_a_rider_who_is_not_moving_is_rejected(self):
        """0で割る形になる。黙って0を返すと、停止状態の区間が無風として扱われる。"""
        with pytest.raises(ValueError):
            wind_drag_ratio_array(5.0, NORTHBOUND, NORTHBOUND, 0.0)

    def test_one_wind_spreads_over_many_bearings(self):
        """1地点の風を、区間ごとに違う走行方位へ当てる。形を揃えるために風を複製すると、
        区間数ぶんの配列を毎回作ることになる。
        """
        result = wind_drag_ratio_array(5.0, 0.0, np.array([0.0, 90.0, 180.0]), CRUISE_MS)

        assert result.shape == (3,)
        assert result[0] > result[1] > result[2]


class TestWindLattice:

    def test_it_covers_the_north_and_east_edges(self):
        """端の地点がどの格子点にも近くならないと、格子の外として端の点へ寄せられ、遠い点の風を引く。"""
        lattice = WindLattice.covering(35.0, 139.0, 35.12, 139.1, 0.05, 0.0625)

        latitudes, longitudes = lattice.coordinates()

        assert latitudes.max() >= 35.12 and longitudes.max() >= 139.1

    def test_each_place_takes_the_nearest_grid_point(self):
        lattice = WindLattice(south=35.0, west=139.0, lat_step=0.05, lon_step=0.0625, rows=3, cols=4)
        latitudes, longitudes = lattice.coordinates()

        points = lattice.points_of(latitudes + 0.01, longitudes - 0.02)

        assert points.tolist() == list(range(12))

    def test_places_outside_take_the_edge_point(self):
        lattice = WindLattice(south=35.0, west=139.0, lat_step=0.05, lon_step=0.0625, rows=3, cols=4)

        assert lattice.points_of(np.array([34.0, 36.0]), np.array([138.0, 140.0])).tolist() == [0, 11]


class TestWindForecastSeries:

    @staticmethod
    def _series(hours: int = 5) -> WindForecastSeries:
        start = datetime(2026, 6, 21, 9, 0)
        return WindForecastSeries(
            times=[start + timedelta(hours=h) for h in range(hours)],
            speed_ms=np.arange(float(hours)),
            direction_deg=np.zeros(hours),
        )

    def test_it_takes_the_nearest_hour(self):
        series = self._series()

        speed, _ = series.sample(series.times[0], np.array([0.4, 0.6, 2.0]))

        assert speed.tolist() == [0.0, 1.0, 2.0]

    def test_times_before_the_series_clamp_to_the_first_value(self):
        """欠損にすると、その区間だけ風を無視する。"""
        series = self._series()

        speed, _ = series.sample(series.times[0], np.array([-5.0]))

        assert speed.tolist() == [0.0]

    def test_times_after_the_series_clamp_to_the_last_value(self):
        series = self._series()

        speed, _ = series.sample(series.times[0], np.array([99.0]))

        assert speed.tolist() == [4.0]

    def test_a_later_start_shifts_the_lookup(self):
        series = self._series()

        speed, _ = series.sample(series.times[2], np.array([1.0]))

        assert speed.tolist() == [3.0]

    def test_a_lattice_series_takes_the_wind_of_each_grid_point(self):
        """格子点ごとの系列は、区間ごとに近い格子点の風を引く（1地点の系列では全区間が同じ風になる）。"""
        start = datetime(2026, 6, 21, 9, 0)
        lattice = WindLattice(south=35.0, west=139.0, lat_step=0.05, lon_step=0.0625, rows=1, cols=2)
        series = WindForecastSeries(
            times=[start, start + timedelta(hours=1)],
            speed_ms=np.array([[1.0, 2.0], [5.0, 6.0]]),
            direction_deg=np.zeros((2, 2)),
            lattice=lattice,
        )

        speed, _ = series.sample(start, np.array([0.0, 1.0, 1.0]), np.array([0, 0, 1]))

        assert speed.tolist() == [1.0, 2.0, 6.0]

    def test_a_lattice_series_needs_the_grid_points(self):
        start = datetime(2026, 6, 21, 9, 0)
        lattice = WindLattice(south=35.0, west=139.0, lat_step=0.05, lon_step=0.0625, rows=1, cols=2)
        series = WindForecastSeries(
            times=[start, start + timedelta(hours=1)],
            speed_ms=np.zeros((2, 2)), direction_deg=np.zeros((2, 2)), lattice=lattice,
        )

        with pytest.raises(ValueError):
            series.sample(start, np.array([0.0]))

    def test_a_series_too_short_to_have_a_step_is_rejected(self):
        with pytest.raises(ValueError):
            WindForecastSeries(
                times=[datetime(2026, 6, 21, 9, 0)],
                speed_ms=np.array([1.0]),
                direction_deg=np.array([0.0]),
            )

    def test_mismatched_lengths_are_rejected(self):
        """長さがずれると、引いた添字が別の時刻の値を指す。"""
        start = datetime(2026, 6, 21, 9, 0)
        with pytest.raises(ValueError):
            WindForecastSeries(
                times=[start, start + timedelta(hours=1)],
                speed_ms=np.array([1.0, 2.0, 3.0]),
                direction_deg=np.array([0.0, 0.0]),
            )

    def test_a_step_other_than_one_hour_is_rejected(self):
        """添字の計算が1時間刻みを前提にしている。3時間刻みを渡すと3倍先の風を引く。"""
        start = datetime(2026, 6, 21, 9, 0)
        with pytest.raises(ValueError):
            WindForecastSeries(
                times=[start, start + timedelta(hours=3)],
                speed_ms=np.array([1.0, 2.0]),
                direction_deg=np.array([0.0, 0.0]),
            )


class TestEstimatePassageHours:

    ANCHOR = Coordinates(latitude=35.0, longitude=139.0)

    def test_the_anchor_itself_is_reached_at_the_offset(self):
        hours = estimate_passage_hours(
            np.array([35.0]), np.array([139.0]), self.ANCHOR, offset_hours=2.0, direction=1, speed_kmh=20.0
        )

        assert hours.tolist() == pytest.approx([2.0])

    def test_an_outbound_leg_gets_later_with_distance(self):
        near = estimate_passage_hours(
            np.array([35.01]), np.array([139.0]), self.ANCHOR, offset_hours=0.0, direction=1, speed_kmh=20.0
        )
        far = estimate_passage_hours(
            np.array([35.1]), np.array([139.0]), self.ANCHOR, offset_hours=0.0, direction=1, speed_kmh=20.0
        )

        assert far[0] > near[0] > 0

    def test_an_inbound_leg_gets_earlier_with_distance(self):
        """遠い区間ほど先に通る。"""
        hours = estimate_passage_hours(
            np.array([35.1]), np.array([139.0]), self.ANCHOR, offset_hours=3.0, direction=-1, speed_kmh=20.0
        )

        assert hours[0] < 3.0

    def test_a_faster_rider_reaches_the_same_point_sooner(self):
        slow = estimate_passage_hours(
            np.array([35.1]), np.array([139.0]), self.ANCHOR, offset_hours=0.0, direction=1, speed_kmh=10.0
        )
        fast = estimate_passage_hours(
            np.array([35.1]), np.array([139.0]), self.ANCHOR, offset_hours=0.0, direction=1, speed_kmh=30.0
        )

        assert fast[0] < slow[0]

    def test_the_detour_ratio_stretches_the_estimate(self):
        """直線距離のままだと、道なりに走るぶんの時間を取りこぼす。"""
        straight = estimate_passage_hours(
            np.array([35.1]), np.array([139.0]), self.ANCHOR, 0.0, 1, 20.0, detour_ratio=1.0
        )
        detoured = estimate_passage_hours(
            np.array([35.1]), np.array([139.0]), self.ANCHOR, 0.0, 1, 20.0, detour_ratio=ROUTE_DETOUR_RATIO
        )

        assert detoured[0] == pytest.approx(straight[0] * ROUTE_DETOUR_RATIO)

    def test_a_rider_who_is_not_moving_is_rejected(self):
        with pytest.raises(ValueError):
            estimate_passage_hours(np.array([35.0]), np.array([139.0]), self.ANCHOR, 0.0, 1, 0.0)
