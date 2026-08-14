import mapbox_vector_tile

from app.infrastructure.vector_tile import ROAD_SURFACE_LAYER_NAME, TILE_EXTENT, encode_road_surface_tile

Z, X, Y = 14, 14551, 6447  # 王子駅付近を含むタイル


def _decode(tile_bytes: bytes) -> dict:
    return mapbox_vector_tile.decode(tile_bytes, default_options={"y_coord_down": True})


def test_encode_road_surface_tile_produces_a_decodable_layer_with_expected_properties():
    ways = [
        {"coordinates": [[35.7550, 139.7350], [35.7560, 139.7360]], "surface_good": True},
        {"coordinates": [[35.7570, 139.7370], [35.7580, 139.7380]], "surface_good": False},
        {"coordinates": [[35.7590, 139.7390], [35.7600, 139.7400]], "surface_good": None},
    ]

    tile_bytes = encode_road_surface_tile(Z, X, Y, ways)
    decoded = _decode(tile_bytes)

    features = decoded[ROAD_SURFACE_LAYER_NAME]["features"]
    assert len(features) == 3
    surface_values = {f["properties"].get("surface_good") for f in features}
    assert surface_values == {True, False, None}


def test_encode_road_surface_tile_places_points_within_tile_extent_for_a_point_inside_the_tile():
    # タイルの中心に近い点は、タイルローカル座標でも概ね中央（0-4096の範囲内）に来るはず
    ways = [{"coordinates": [[35.7555, 139.7355], [35.7556, 139.7356]], "surface_good": True}]

    tile_bytes = encode_road_surface_tile(Z, X, Y, ways)
    decoded = _decode(tile_bytes)

    feature = decoded[ROAD_SURFACE_LAYER_NAME]["features"][0]
    for px, py in feature["geometry"]["coordinates"]:
        assert 0 <= px <= TILE_EXTENT
        assert 0 <= py <= TILE_EXTENT


def test_encode_road_surface_tile_skips_ways_with_fewer_than_two_points():
    ways = [{"coordinates": [[35.7555, 139.7355]], "surface_good": True}]

    tile_bytes = encode_road_surface_tile(Z, X, Y, ways)
    decoded = _decode(tile_bytes)

    assert decoded[ROAD_SURFACE_LAYER_NAME]["features"] == []


def test_encode_road_surface_tile_handles_empty_ways():
    tile_bytes = encode_road_surface_tile(Z, X, Y, [])

    decoded = _decode(tile_bytes)

    assert decoded[ROAD_SURFACE_LAYER_NAME]["features"] == []
