import pytest

from app.domain.region import tile_bounds_lonlat


def test_tile_bounds_lonlat_covers_whole_world_at_zoom_0():
    bbox = tile_bounds_lonlat(0, 0, 0)

    assert bbox.min_longitude == pytest.approx(-180.0)
    assert bbox.max_longitude == pytest.approx(180.0)
    assert bbox.max_latitude == pytest.approx(85.0511, abs=1e-3)
    assert bbox.min_latitude == pytest.approx(-85.0511, abs=1e-3)


def test_tile_bounds_lonlat_contains_the_point_it_was_computed_for():
    # 王子駅付近を含むタイル（z14）。tile x/yはWeb Mercatorの標準式で算出したもの。
    bbox = tile_bounds_lonlat(14, 14551, 6447)

    assert bbox.min_latitude < 35.7597 < bbox.max_latitude
    assert bbox.min_longitude < 139.7387 < bbox.max_longitude


def test_tile_bounds_lonlat_adjacent_tiles_share_a_boundary():
    left = tile_bounds_lonlat(10, 100, 200)
    right = tile_bounds_lonlat(10, 101, 200)

    assert left.max_longitude == pytest.approx(right.min_longitude)
