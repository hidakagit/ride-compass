"""`infrastructure/jma_tile_interpolation.py`（配信元が持たないズームの補間）のテスト。"""

import io

import pytest
from PIL import Image

from app.infrastructure.jma_tile_interpolation import (
    crop_and_upscale,
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
