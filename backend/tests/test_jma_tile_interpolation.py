"""`infrastructure/jma_tile_interpolation.py`（配信元が持たないズームの補間）のテスト。"""

import io

import pytest
from PIL import Image

import mapbox_vector_tile
from shapely.geometry import LineString

from app.infrastructure.jma_tile_interpolation import (
    crop_and_upscale,
    crop_and_upscale_mvt,
    parse_tile_path,
)

_RISK_PREFIX = "bosai/jmatile/data/risk/20260906191000/immed0/20260906191000/surf"


def test_parse_tile_path_extracts_element_and_coords():
    coords = parse_tile_path(f"{_RISK_PREFIX}/rain_mesh/9/454/201.png")

    assert coords is not None
    assert (coords.element, coords.z, coords.x, coords.y, coords.ext) == ("rain_mesh", 9, 454, 201, "png")


def test_parse_tile_path_builds_parent_path_and_quadrant():
    coords = parse_tile_path(f"{_RISK_PREFIX}/rain_mesh/9/455/201.png")

    # 親は1段上のズームで、タイル座標は切り捨て（455//2=227、201//2=100）。
    assert coords.parent_path() == f"{_RISK_PREFIX}/rain_mesh/8/227/100.png"
    # 455は奇数=右側、201は奇数=下側。
    assert coords.quadrant == (1, 1)


@pytest.mark.parametrize(
    ("x", "y", "expected"),
    [(454, 200, (0, 0)), (455, 200, (1, 0)), (454, 201, (0, 1)), (455, 201, (1, 1))],
)
def test_quadrant_covers_all_four_positions(x, y, expected):
    assert parse_tile_path(f"{_RISK_PREFIX}/land/9/{x}/{y}.png").quadrant == expected


@pytest.mark.parametrize(
    "path",
    [
        # 時刻一覧はタイルではない。
        "bosai/jmatile/data/risk/targetTimes.json",
        # 雷放電位置データはGeoJSON（クエリ文字列付き）。
        "bosai/jmatile/data/nowc/20260906/none/20260906/surf/liden/data.geojson?id=liden",
        # 拡張子が想定外。
        f"{_RISK_PREFIX}/rain_mesh/9/454/201.webp",
    ],
)
def test_parse_tile_path_rejects_non_tile_paths(path):
    assert parse_tile_path(path) is None


def _solid_quadrants_png(size: int = 256) -> bytes:
    """4象限を別々の色で塗ったPNG（切り出し位置の検証用）。"""
    image = Image.new("RGBA", (size, size))
    half = size // 2
    colors = {
        (0, 0): (255, 0, 0, 255),
        (1, 0): (0, 255, 0, 255),
        (0, 1): (0, 0, 255, 255),
        (1, 1): (255, 255, 0, 255),
    }
    for (qx, qy), color in colors.items():
        for x in range(qx * half, qx * half + half):
            for y in range(qy * half, qy * half + half):
                image.putpixel((x, y), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("quadrant", "expected_color"),
    [
        ((0, 0), (255, 0, 0, 255)),
        ((1, 0), (0, 255, 0, 255)),
        ((0, 1), (0, 0, 255, 255)),
        ((1, 1), (255, 255, 0, 255)),
    ],
)
def test_crop_and_upscale_picks_the_requested_quadrant(quadrant, expected_color):
    result = crop_and_upscale(_solid_quadrants_png(), quadrant)

    with Image.open(io.BytesIO(result)) as image:
        assert image.size == (256, 256)
        # 拡大後は全面がその象限の色で埋まる。
        assert image.convert("RGBA").getpixel((10, 10)) == expected_color
        assert image.convert("RGBA").getpixel((245, 245)) == expected_color


def test_crop_and_upscale_does_not_blend_colors():
    """最近傍で拡大する（凡例に無い中間色を作らない）。

    キキクル・ナウキャストは危険度を離散的な色で塗り分けており、滑らかに拡大すると
    境界に凡例のどの段階でもない色が生まれる。
    """
    result = crop_and_upscale(_solid_quadrants_png(), (0, 0))

    with Image.open(io.BytesIO(result)) as image:
        colors = {image.convert("RGBA").getpixel((x, y)) for x in range(0, 256, 8) for y in range(0, 256, 8)}

    assert colors == {(255, 0, 0, 255)}


def test_crop_and_upscale_preserves_transparency():
    """危険度ゼロの領域（透明）が不透明にならない——平常時の地図の見た目を変えない。"""
    transparent = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    buffer = io.BytesIO()
    transparent.save(buffer, format="PNG")

    result = crop_and_upscale(buffer.getvalue(), (1, 0))

    with Image.open(io.BytesIO(result)) as image:
        assert image.convert("RGBA").getpixel((128, 128))[3] == 0


_EXTENT = 4096


def _mvt(*lines: list[tuple[int, int]]) -> bytes:
    """タイル内座標で線を持つMVT。座標系はデコード結果と同じy軸上向き。"""
    return mapbox_vector_tile.encode(
        [
            {
                "name": "flood",
                "features": [
                    {"geometry": LineString(coords), "properties": {"level": index + 1}}
                    for index, coords in enumerate(lines)
                ],
            }
        ],
        default_options={"extents": _EXTENT},
    )


def _levels(tile: bytes) -> list[int]:
    if not tile:
        return []
    decoded = mapbox_vector_tile.decode(tile)
    return sorted(f["properties"]["level"] for f in decoded["flood"]["features"])


@pytest.mark.parametrize(
    ("quadrant", "expected_levels"),
    [
        # 親の左下（南西）に短い線1（level=1）、右上（北東）に短い線2（level=2）を置く。
        # quadrantはタイルXY（y=0が北）のため、南西は(0,1)・北東は(1,0)。
        ((0, 1), [1]),
        ((1, 0), [2]),
        ((0, 0), []),
        ((1, 1), []),
    ],
)
def test_crop_and_upscale_mvt_picks_the_requested_quadrant(quadrant, expected_levels):
    """タイルXYのyは南向き、MVTのデコード座標は北向き。上下の取り違えを固定する。"""
    parent = _mvt(
        [(100, 100), (500, 500)],
        [(_EXTENT - 500, _EXTENT - 500), (_EXTENT - 100, _EXTENT - 100)],
    )

    assert _levels(crop_and_upscale_mvt(parent, quadrant)) == expected_levels


def test_crop_and_upscale_mvt_doubles_coordinates_within_the_quadrant():
    # 南西象限いっぱいに対角線を引くと、切り出し後は子タイルいっぱいの対角線になる。
    parent = _mvt([(0, 0), (_EXTENT // 2, _EXTENT // 2)])

    decoded = mapbox_vector_tile.decode(crop_and_upscale_mvt(parent, (0, 1)))
    coordinates = decoded["flood"]["features"][0]["geometry"]["coordinates"]

    assert coordinates[0] == [0, 0]
    # 境界に接する線はクリップの余白ぶんだけはみ出す（タイルの継ぎ目で途切れないため）。
    assert coordinates[-1][0] >= _EXTENT
    assert coordinates[-1][1] >= _EXTENT


def test_crop_and_upscale_mvt_returns_empty_tile_when_nothing_intersects():
    # 親に地物があっても象限に掛からなければ0バイト（＝地物なし）。
    parent = _mvt([(0, 0), (100, 100)])

    assert crop_and_upscale_mvt(parent, (1, 0)) == b""


def test_crop_and_upscale_mvt_keeps_properties():
    parent = _mvt([(0, 0), (_EXTENT, _EXTENT)])

    decoded = mapbox_vector_tile.decode(crop_and_upscale_mvt(parent, (0, 1)))

    assert decoded["flood"]["features"][0]["properties"] == {"level": 1}
