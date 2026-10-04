"""`infrastructure/jma_tile_interpolation.py`——配信元が持たないズームのタイルを、1段上のタイルから切り出す。

入口は`parse_tile_path`（子のタイルの座標と、親のパス・象限）と、`crop_and_upscale`（ラスタ）・
`crop_and_upscale_mvt`（ベクタ）。親のタイルは画像・ベクタタイルをテストの中で作る。

ここで見ないもの:
- どのズームを補間するか（`domain/jma_tile_specs.py: source_zoom_for_interpolation`）・パスの形の読み書き
  （要素・座標・拡張子、タイルでないパスと宣言の無い要素がNoneになること） → `test_jma_tile_specs.py`。
  `parse_tile_path`はその読み取りを座標へ移すだけなので、ここでは親と象限の関係だけを宣言にあるラスタ（降水ナウキャスト）のパスで見る
- 親を取りに行く・取れないときに上流へ回す段取り・ベクタのパスをベクタとして切り出すこと → `test_jma_tile_routes.py`
"""

import io

import mapbox_vector_tile
import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from PIL import Image
from shapely.geometry import LineString, Point, Polygon, shape

from app.infrastructure.jma_tile_interpolation import crop_and_upscale, crop_and_upscale_mvt, parse_tile_path

FRAME = "bosai/jmatile/data/nowc/20260101000000/none/20260101000500/surf"
EXTENT = 4096
HALF = EXTENT // 2
SIZE = 256


def raster(z: int, x: int, y: int) -> str:
    return f"{FRAME}/hrpns/{z}/{x}/{y}.png"


@given(z=st.integers(5, 12), data=st.data())
def test_the_parent_is_the_tile_one_zoom_up_whose_quadrant_covers_the_child(z, data):
    """親のタイルを象限で4つに割ると、そのうち1つがちょうど子のタイルに当たる。"""
    x = data.draw(st.integers(0, 2**z - 1))
    y = data.draw(st.integers(0, 2**z - 1))
    coords = parse_tile_path(raster(z, x, y))

    parent = parse_tile_path(coords.parent_path())
    quadrant_x, quadrant_y = coords.quadrant

    assert parent.z == z - 1
    assert (2 * parent.x + quadrant_x, 2 * parent.y + quadrant_y) == (x, y)
    assert coords.parent_path().startswith(f"{FRAME}/hrpns/")


def png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def pixels(content: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(content)) as image:
        return np.asarray(image.convert("RGBA"))


@pytest.mark.parametrize("quadrant", [(1, 0), (0, 1)])
def test_a_raster_quadrant_is_doubled_pixel_for_pixel(quadrant):
    """凡例の色と1対1で読む画像なので、拡大で中間の色を作らない（1画素を2×2へ写すだけ）。
    象限は東西・南北それぞれの両側を通し、東西と南北を取り違えると落ちる組み合わせにする。"""
    rng = np.random.default_rng(0)
    parent = rng.integers(0, 256, size=(SIZE, SIZE, 4), dtype=np.uint8)
    left, top = quadrant[0] * SIZE // 2, quadrant[1] * SIZE // 2

    child = pixels(crop_and_upscale(png_bytes(Image.fromarray(parent, "RGBA")), quadrant))

    part = parent[top : top + SIZE // 2, left : left + SIZE // 2]
    assert np.array_equal(child, part.repeat(2, axis=0).repeat(2, axis=1))


def test_a_palette_raster_keeps_its_transparent_entry_transparent():
    """配信元の実データのタイルはパレット形式で、0番が透明。透明を不透明の黒に変えると地図が塗りつぶされる。"""
    parent = Image.new("P", (SIZE, SIZE), 0)
    parent.putpalette([0, 0, 0, 255, 40, 0] + [0, 0, 0] * 254)
    parent.info["transparency"] = 0
    parent.putpixel((0, 0), 1)

    child = pixels(crop_and_upscale(png_bytes(parent), (0, 0)))

    assert child[0:2, 0:2].tolist() == [[[255, 40, 0, 255]] * 2] * 2
    assert child[2:, 2:, 3].max() == 0


def mvt(*features, layer="flood", extent=EXTENT) -> bytes:
    """座標はy軸が上向き（MVTを解いた形と同じ）。"""
    return mapbox_vector_tile.encode(
        [{"name": layer, "features": list(features)}], per_layer_options={layer: {"extents": extent}}
    )


def feature(geometry, **properties):
    return {"geometry": geometry, "properties": properties}


def decoded(content: bytes) -> dict:
    return mapbox_vector_tile.decode(content)


@given(
    x=st.integers(40, HALF - 40) | st.integers(HALF + 40, EXTENT - 40),
    y=st.integers(40, HALF - 40) | st.integers(HALF + 40, EXTENT - 40),
)
def test_a_point_lands_only_in_the_quadrant_it_lies_in_at_twice_its_offset(x, y):
    """象限はタイルの行と同じく北が0。解いた座標はy軸が上向きなので、北の象限はyの大きい側にある。"""
    parent = mvt(feature(Point(x, y), level=3))
    lies_in = (int(x >= HALF), int(y < HALF))

    for quadrant in [(0, 0), (1, 0), (0, 1), (1, 1)]:
        child = crop_and_upscale_mvt(parent, quadrant)
        if quadrant != lies_in:
            assert child == b""
            continue
        left, bottom = quadrant[0] * HALF, (1 - quadrant[1]) * HALF
        [only] = decoded(child)["flood"]["features"]
        assert only["geometry"]["coordinates"] == [2 * (x - left), 2 * (y - bottom)]


def test_attributes_and_ids_are_carried_over():
    """危険度は地物の属性で塗るので、切り出しで落とすと色が消える。"""
    parent = mapbox_vector_tile.encode(
        [{"name": "flood", "features": [{"geometry": Point(100, 3000), "properties": {"level": 4}, "id": 7}]}]
    )

    [only] = decoded(crop_and_upscale_mvt(parent, (0, 0)))["flood"]["features"]

    assert (only["properties"], only["id"]) == ({"level": 4}, 7)


def test_a_line_crossing_into_the_next_quadrant_is_kept_a_little_past_the_edge():
    """線をちょうど縁で切ると、隣のタイルとの継ぎ目で途切れて見える。余白は縁の外へ短く残すだけにする。"""
    parent = mvt(feature(LineString([(1000, 3000), (4000, 3000)])))

    [line] = decoded(crop_and_upscale_mvt(parent, (0, 0)))["flood"]["features"]

    xs = [point[0] for point in line["geometry"]["coordinates"]]
    assert min(xs) == 2000
    assert EXTENT < max(xs) <= EXTENT * 1.05


def test_a_polygon_is_clipped_to_the_quadrant_as_a_polygon():
    parent = mvt(feature(Polygon([(1000, 1000), (3000, 1000), (3000, 3000), (1000, 3000)])))

    [area] = decoded(crop_and_upscale_mvt(parent, (1, 1)))["flood"]["features"]

    clipped = shape(area["geometry"])
    assert clipped.geom_type == "Polygon"
    west, south, east, north = clipped.bounds
    assert west < 0 and east == 2 * (3000 - HALF)
    assert south == 2 * 1000 and north > EXTENT


def test_a_line_keeps_only_its_line_parts_when_it_also_touches_the_edge_at_a_point():
    """縁に1点だけ触れる線は、切り出すと線と点が混ざる。点は線の層で描けないので落とす。"""
    margin = EXTENT // 128
    touch = (HALF + margin, 3000)
    line = LineString([(100, 3000), (100, 1000), (3000, 1000), touch, (3000, 3500)])
    only_touching = LineString([(3000, 1000), touch, (3000, 3500)])
    parent = mvt(feature(line, name="crossing"), feature(only_touching, name="touching"))

    features = decoded(crop_and_upscale_mvt(parent, (0, 0)))["flood"]["features"]

    assert [(f["properties"]["name"], f["geometry"]["type"]) for f in features] == [("crossing", "LineString")]


def test_a_line_split_into_several_pieces_keeps_every_piece():
    line = LineString([(100, 3000), (100, 1000), (1500, 1000), (1500, 3000)])
    parent = mvt(feature(line))

    [piece] = decoded(crop_and_upscale_mvt(parent, (0, 0)))["flood"]["features"]

    assert piece["geometry"]["type"] == "MultiLineString"
    assert len(piece["geometry"]["coordinates"]) == 2


def test_a_layer_with_its_own_extent_is_split_at_its_own_middle():
    parent = mvt(feature(Point(100, 400)), layer="small", extent=512)

    child = decoded(crop_and_upscale_mvt(parent, (0, 0)))["small"]

    assert child["extent"] == 512
    assert child["features"][0]["geometry"]["coordinates"] == [200, 288]


def test_only_layers_with_something_in_the_quadrant_are_kept():
    parent = mapbox_vector_tile.encode(
        [
            {"name": "north", "features": [feature(Point(100, 3000))]},
            {"name": "south", "features": [feature(Point(100, 1000))]},
        ]
    )

    assert list(decoded(crop_and_upscale_mvt(parent, (0, 0)))) == ["north"]
