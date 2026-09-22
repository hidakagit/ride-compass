"""`infrastructure/jma_tile_interpolation.py`——1段上のタイルから欠けたズームを作る。

ここで見ないもの:
- どの要素のどのズームに実データがあるか（配信元の仕様） → `test_jma_tile_specs.py`
- 補間を呼ぶ・結果をキャッシュへ書き戻す導線 → `test_jma_tile_routes.py`

ベクタの座標はMVTのタイル内座標（extent基準の整数、y軸は上向き）で書く。
"""

import io

import mapbox_vector_tile
import pytest
from PIL import Image
from shapely.geometry import LineString, MultiLineString, Point, Polygon

from app.infrastructure.jma_tile_interpolation import (
    crop_and_upscale,
    crop_and_upscale_mvt,
    parse_tile_path,
)

TILE_PATH = "bosai/jmatile/data/nowc/20260101000000/none/20260101000500/surf/hrpns/10/909/403.png"

_QUADRANT_COLORS = {
    (0, 0): (220, 20, 20, 255),
    (1, 0): (20, 220, 20, 255),
    (0, 1): (20, 20, 220, 255),
    (1, 1): (220, 220, 20, 255),
}
_SIZE = 64
_EXTENT = 4096
_LAYER = "flood"
#: 象限の中心にあたるタイル内座標（左上・右上・左下・右下の順にタイルXYの象限と対応）。
_QUADRANT_POINTS = {
    (0, 0): Point(1024, 3072),
    (1, 0): Point(3072, 3072),
    (0, 1): Point(1024, 1024),
    (1, 1): Point(3072, 1024),
}


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _quadrant_painted(mode: str = "RGBA") -> bytes:
    image = Image.new("RGBA", (_SIZE, _SIZE))
    half = _SIZE // 2
    for (quadrant_x, quadrant_y), color in _QUADRANT_COLORS.items():
        left, top = quadrant_x * half, quadrant_y * half
        image.paste(color, (left, top, left + half, top + half))
    return _png(image.convert(mode))


def _colors(png: bytes) -> set[tuple[int, int, int, int]]:
    with Image.open(io.BytesIO(png)) as image:
        rgba = image.convert("RGBA")
        return {color for _, color in rgba.getcolors(rgba.width * rgba.height)}


def _encode(features: list[dict], extent: int = _EXTENT, name: str = _LAYER) -> bytes:
    return mapbox_vector_tile.encode(
        [{"name": name, "features": features}], per_layer_options={name: {"extents": extent}}
    )


def _features(pbf: bytes, name: str = _LAYER) -> list[dict]:
    return mapbox_vector_tile.decode(pbf)[name]["features"]


def test_tile_path_yields_the_element_and_coordinates():
    coords = parse_tile_path(TILE_PATH)
    assert (coords.element, coords.z, coords.x, coords.y, coords.ext) == ("hrpns", 10, 909, 403, "png")


@pytest.mark.parametrize(
    "path",
    [
        "bosai/jmatile/data/nowc/targetTimes_N1.json",
        f"{TILE_PATH}?t=20260101000000",
        TILE_PATH.replace(".png", ".jpg"),
        TILE_PATH.replace("/surf/hrpns/", "/surf/HRPNS/"),
    ],
)
def test_paths_that_are_not_tiles_are_not_parsed(path):
    assert parse_tile_path(path) is None


@pytest.mark.parametrize(
    ("x", "y", "quadrant"),
    [(908, 402, (0, 0)), (909, 402, (1, 0)), (908, 403, (0, 1)), (909, 403, (1, 1))],
)
def test_parent_tile_halves_the_coordinates_and_keeps_the_quadrant(x, y, quadrant):
    coords = parse_tile_path(f"head/surf/hrpns/10/{x}/{y}.png")
    assert coords.parent_path() == "head/surf/hrpns/9/454/201.png"
    assert coords.quadrant == quadrant


@pytest.mark.parametrize("quadrant", list(_QUADRANT_COLORS))
def test_raster_quadrant_fills_the_whole_tile(quadrant):
    result = crop_and_upscale(_quadrant_painted(), quadrant)
    with Image.open(io.BytesIO(result)) as image:
        assert image.size == (_SIZE, _SIZE)
    assert _colors(result) == {_QUADRANT_COLORS[quadrant]}


def test_upscaling_carries_pixel_values_through_unchanged():
    """拡大で中間色が生まれず、透明の領域も透明のまま残ることを一度に見る。"""
    image = Image.new("RGBA", (_SIZE, _SIZE), (0, 0, 0, 0))
    image.paste((220, 20, 20, 255), (0, 0, _SIZE // 4, _SIZE // 4))
    image.paste((20, 220, 20, 128), (_SIZE // 4, 0, _SIZE // 2, _SIZE // 4))
    assert _colors(crop_and_upscale(_png(image), (0, 0))) == {
        (220, 20, 20, 255),
        (20, 220, 20, 128),
        (0, 0, 0, 0),
    }


def test_palette_encoded_parent_is_handled():
    assert _colors(crop_and_upscale(_quadrant_painted(mode="P"), (1, 1))) == {_QUADRANT_COLORS[(1, 1)]}


@pytest.mark.parametrize("quadrant", list(_QUADRANT_POINTS))
def test_vector_quadrant_is_cut_out_and_rescaled(quadrant):
    parent = _encode(
        [{"geometry": point, "properties": {"level": index}} for index, point in enumerate(_QUADRANT_POINTS.values())]
    )
    features = _features(crop_and_upscale_mvt(parent, quadrant))
    assert len(features) == 1
    assert features[0]["geometry"]["coordinates"] == [_EXTENT // 2, _EXTENT // 2]
    assert features[0]["properties"] == {"level": list(_QUADRANT_POINTS).index(quadrant)}


def test_vector_features_keep_their_identity():
    parent = _encode([{"geometry": _QUADRANT_POINTS[(0, 0)], "properties": {"level": 3}, "id": 7}])
    assert _features(crop_and_upscale_mvt(parent, (0, 0)))[0]["id"] == 7


def test_vector_tile_with_nothing_in_the_quadrant_is_zero_bytes():
    parent = _encode([{"geometry": _QUADRANT_POINTS[(1, 1)], "properties": {}}])
    assert crop_and_upscale_mvt(parent, (0, 0)) == b""


def test_features_just_outside_the_quadrant_are_kept_as_a_margin():
    """タイルの継ぎ目で線が途切れて見えないよう、境界の外側も少し残す。"""
    parent = _encode([{"geometry": Point(_EXTENT // 2 + 12, 3072), "properties": {}}])
    assert _features(crop_and_upscale_mvt(parent, (0, 0)))[0]["geometry"]["coordinates"] == [_EXTENT + 24, 2048]


def test_each_layer_keeps_its_own_extent():
    parent = mapbox_vector_tile.encode(
        [
            {"name": "coarse", "features": [{"geometry": Point(1024, 3072), "properties": {}}]},
            {"name": "fine", "features": [{"geometry": Point(256, 768), "properties": {}}]},
        ],
        per_layer_options={"coarse": {"extents": 4096}, "fine": {"extents": 1024}},
    )
    decoded = mapbox_vector_tile.decode(crop_and_upscale_mvt(parent, (0, 0)))
    assert {name: layer["extent"] for name, layer in decoded.items()} == {"coarse": 4096, "fine": 1024}
    assert decoded["fine"]["features"][0]["geometry"]["coordinates"] == [512, 512]


def test_parts_of_another_kind_are_dropped_from_the_cut():
    """線を矩形で切ると接点が点として混ざる。点はMVTの同じレイヤーへ混ぜられない。"""
    inside = [(100, 3000), (500, 3000)]
    touching = [(_EXTENT // 2 + 32, 2500), (3000, 2500)]
    parent = _encode([{"geometry": MultiLineString([inside, touching]), "properties": {}}])
    geometry = _features(crop_and_upscale_mvt(parent, (0, 0)))[0]["geometry"]
    assert geometry["type"] == "LineString"
    assert geometry["coordinates"] == [[200, 1904], [1000, 1904]]


def test_feature_left_with_no_part_of_its_own_kind_is_dropped():
    edge = _EXTENT // 2 + 32
    parent = _encode(
        [
            {
                "geometry": Polygon(
                    [(edge, 2500), (edge, 2600), (2200, 2620), (edge, 2700), (2200, 2750), (3000, 2750), (3000, 2500)]
                ),
                "properties": {},
            }
        ]
    )
    assert crop_and_upscale_mvt(parent, (0, 0)) == b""


def test_line_touching_the_quadrant_at_a_single_point_is_dropped():
    parent = _encode([{"geometry": LineString([(_EXTENT // 2 + 32, 3072), (3000, 3072)]), "properties": {}}])
    assert crop_and_upscale_mvt(parent, (0, 0)) == b""
