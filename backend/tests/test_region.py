import pytest

from app.domain.region import BoundingBox, tile_bounds_lonlat, tiles_covering_bbox


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


def test_tiles_covering_bbox_returns_single_tile_when_bbox_fits_inside_it():
    z, x, y = 12, 3637, 1612
    bbox = tile_bounds_lonlat(z, x, y)
    eps = 1e-6  # 境界ちょうどだと浮動小数点誤差で隣タイルへこぼれうるため少し内側にずらす
    inset = BoundingBox(
        min_latitude=bbox.min_latitude + eps,
        min_longitude=bbox.min_longitude + eps,
        max_latitude=bbox.max_latitude - eps,
        max_longitude=bbox.max_longitude - eps,
    )

    assert tiles_covering_bbox(inset, z) == [(x, y)]


def test_tiles_covering_bbox_returns_all_tiles_when_bbox_spans_multiple():
    z, x, y = 12, 3637, 1612
    tile_a = tile_bounds_lonlat(z, x, y)
    tile_d = tile_bounds_lonlat(z, x + 1, y + 1)
    # tile_aの中心からtile_dの中心まで広がるbboxは、(x,y),(x+1,y),(x,y+1),(x+1,y+1)の
    # 4タイルにまたがる。
    spanning = BoundingBox(
        min_latitude=tile_d.min_latitude + (tile_d.max_latitude - tile_d.min_latitude) / 2,
        min_longitude=tile_a.min_longitude + (tile_a.max_longitude - tile_a.min_longitude) / 2,
        max_latitude=tile_a.min_latitude + (tile_a.max_latitude - tile_a.min_latitude) / 2,
        max_longitude=tile_d.min_longitude + (tile_d.max_longitude - tile_d.min_longitude) / 2,
    )

    result = sorted(tiles_covering_bbox(spanning, z))
    expected = sorted([(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)])
    assert result == expected


def test_tiles_covering_bbox_clamps_to_valid_tile_range_at_world_edges():
    z = 3
    n = 2**z
    world_bbox = BoundingBox(min_latitude=-85.0, min_longitude=-180.0, max_latitude=85.0, max_longitude=180.0)

    tiles = tiles_covering_bbox(world_bbox, z)

    assert all(0 <= tx < n and 0 <= ty < n for tx, ty in tiles)


def test_tiles_covering_bbox_does_not_raise_for_out_of_range_latitude():
    # BoundingBoxはCoordinatesと異なり緯度の範囲を検証しないため、90度を超える不正な値が
    # 渡されても（本来あってはならないが）math domain error等でクラッシュしないことを確認する。
    z = 3
    n = 2**z
    out_of_range_bbox = BoundingBox(min_latitude=-95.0, min_longitude=-10.0, max_latitude=95.0, max_longitude=10.0)

    tiles = tiles_covering_bbox(out_of_range_bbox, z)

    assert all(0 <= tx < n and 0 <= ty < n for tx, ty in tiles)
