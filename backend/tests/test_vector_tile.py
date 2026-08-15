import mapbox_vector_tile

from app.infrastructure.vector_tile import ROAD_SURFACE_LAYER_NAME, encode_empty_road_surface_tile


def _decode(tile_bytes: bytes) -> dict:
    return mapbox_vector_tile.decode(tile_bytes, default_options={"y_coord_down": True})


def test_encode_empty_road_surface_tile_produces_a_decodable_layer_with_no_features():
    tile_bytes = encode_empty_road_surface_tile()

    decoded = _decode(tile_bytes)

    assert decoded[ROAD_SURFACE_LAYER_NAME]["features"] == []
