"""`domain/wind_grid.py`——地図の風・降水の格子点をどこに敷くか。

入口は`generate_wind_grid_points`（対象範囲全体の粗い格子）・`generate_wind_grid_detail_points`
（問い合わせ範囲の詳細格子）・`count_wind_grid_detail_points`（点を作らずに数える）。

ここで見ないもの:
- 点数の上限・間隔の下限で断ること、格子点へ予報を補間すること → `test_weather_route.py`
- 道の風の格子（`domain/wind.py: WindLattice`） → `test_wind.py`
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.region import BoundingBox
from app.domain.wind_grid import (
    WIND_GRID_DETAIL_MIN_SPACING_DEG,
    count_wind_grid_detail_points,
    generate_wind_grid_detail_points,
    generate_wind_grid_points,
)

AREA = BoundingBox(min_latitude=34.8, min_longitude=138.9, max_latitude=36.6, max_longitude=140.9)

#: 画面が求めうる間隔（下限から粗い格子の間隔まで）。
SPACINGS = st.floats(WIND_GRID_DETAIL_MIN_SPACING_DEG, 0.1)


def _box(south, west, north, east) -> BoundingBox:
    return BoundingBox(min_latitude=south, min_longitude=west, max_latitude=north, max_longitude=east)


def _pairs(points) -> list[tuple[float, float]]:
    return [(p.latitude, p.longitude) for p in points]


@st.composite
def boxes(draw) -> BoundingBox:
    """対象範囲と重なりうる、表示中の範囲くらいの矩形。"""
    south = draw(st.floats(34.6, 36.6))
    west = draw(st.floats(138.7, 140.9))
    return _box(south, west, south + draw(st.floats(0.001, 0.08)), west + draw(st.floats(0.001, 0.08)))


def test_the_coarse_grid_covers_the_area_from_the_lines_counted_from_zero_degrees():
    """南西の点は対象範囲の角ではなく、0度から0.1度ずつ数えた線の上に乗る（範囲の手前の線から）。"""
    area = _box(35.05, 139.0, 35.25, 139.15)

    assert _pairs(generate_wind_grid_points(area)) == [
        (35.0, 139.0),
        (35.0, 139.1),
        (35.1, 139.0),
        (35.1, 139.1),
        (35.2, 139.0),
        (35.2, 139.1),
    ]


def test_coordinates_carry_no_floating_point_noise():
    """画面は前回の点を緯度経度の一致で見分ける。353 × 0.1 は 35.300000000000004 になる。"""
    points = generate_wind_grid_detail_points(AREA, _box(35.29, 139.29, 35.31, 139.31), 0.1)

    assert _pairs(points) == [(35.2, 139.2), (35.2, 139.3), (35.3, 139.2), (35.3, 139.3)]


@given(boxes(), st.floats(-0.05, 0.05), st.floats(-0.05, 0.05), SPACINGS)
def test_a_panned_view_returns_the_same_coordinates_where_it_overlaps(view_a, dy, dx, spacing):
    """パンで範囲がずれても、重なる所は同じ座標で返る（前回の点が今回の点とずれて二重に描かれない）。"""
    view_b = _box(
        view_a.min_latitude + dy, view_a.min_longitude + dx, view_a.max_latitude + dy, view_a.max_longitude + dx
    )
    points_b = set(_pairs(generate_wind_grid_detail_points(AREA, view_b, spacing)))
    margin = 1e-4  # 座標の小数4桁の丸めぶん
    inside_b = [
        (lat, lon)
        for lat, lon in _pairs(generate_wind_grid_detail_points(AREA, view_a, spacing))
        if max(view_b.min_latitude, AREA.min_latitude) + margin < lat < view_b.max_latitude - margin
        and max(view_b.min_longitude, AREA.min_longitude) + margin < lon < view_b.max_longitude - margin
    ]

    assert set(inside_b) <= points_b


@given(boxes(), SPACINGS)
def test_counting_agrees_with_the_points_made(view, spacing):
    """上限で断るかは点を作る前に数えて決める。数えた数と作る数が食い違うと、上限が効かない。"""
    assert count_wind_grid_detail_points(AREA, view, spacing) == len(
        generate_wind_grid_detail_points(AREA, view, spacing)
    )


@given(boxes(), SPACINGS)
def test_detail_points_stay_within_the_area_clipped_view(view, spacing):
    """問い合わせ範囲を対象範囲へクリップした所に、手前の線の点から敷く。"""
    south = max(view.min_latitude, AREA.min_latitude)
    west = max(view.min_longitude, AREA.min_longitude)
    north = min(view.max_latitude, AREA.max_latitude)
    east = min(view.max_longitude, AREA.max_longitude)

    for lat, lon in _pairs(generate_wind_grid_detail_points(AREA, view, spacing)):
        assert south - spacing - 1e-4 < lat <= north + 1e-4
        assert west - spacing - 1e-4 < lon <= east + 1e-4


@pytest.mark.parametrize(
    "view",
    [
        _box(30.0, 130.0, 31.0, 131.0),
        _box(35.0, 140.9, 35.5, 141.5),  # 対象範囲の東の辺に接するだけ
    ],
    ids=["離れている", "辺で接する"],
)
def test_a_view_outside_the_area_gets_no_points(view):
    assert count_wind_grid_detail_points(AREA, view, 0.02) == 0
    assert generate_wind_grid_detail_points(AREA, view, 0.02) == []
