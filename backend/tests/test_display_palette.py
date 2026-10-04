"""`domain/display_palette.py`——一次属性の行に塗る色と、役割ごとの色。

入口は`resolved_display_axes`（行の色を解決した表示定義。画面へ配る形）と、その色を作る`ordered_colors`・
`nominal_colors`、役割ごとの色`SEMANTIC_COLORS`。前半は架空の属性で色の配り方を、後半は本番の一次属性の宣言
（`domain/material_catalog.py: PRIMARY_ATTRIBUTES`）に配った色が地図の上で読めること
（`docs/modules/frontend/static-map-layers.md`の配色の読み方）を確かめる。

コントラスト比はWCAG 2.xの相対輝度の比、色の離れ具合はCIE76のΔE（CIELab・D65）。どちらも公開の定義から
このファイルで計算し、実装の換算式を使わない。

ここで見ないもの:
- 一次属性の表示の宣言そのものの不変条件（行の重なり・色相の起点・欠損の意味・種別の網羅）→ `test_material_catalog.py`
- 地図のレイヤー・グループ・情報源の宣言 → `test_map_display.py`
- 行の値が画面の塗り分けの式になること → 画面側のテスト
"""

import itertools
import math

import pytest

from app.domain import display_palette
from app.domain.display_palette import SEMANTIC_COLORS, nominal_colors, ordered_colors, resolved_display_axes
from app.domain.map_display import ROAD_UNKNOWN_OPACITY
from app.domain.material_catalog import PRIMARY_ATTRIBUTES
from app.domain.registry import DisplayAxisSpec, DisplayCategorySpec, PrimaryAttributeSpec

GROUND = SEMANTIC_COLORS["basemap_ground"]
#: 分類色が地色から浮くコントラスト比（これを割ると「薄い＝対象外」と見分けられない）。
CLASS_COLOR_CONTRAST = 3.0
#: 値が無い道の線が、地色に対して見えるコントラスト比。
NO_DATA_LINE_CONTRAST = 1.5
#: 軸の中の色の離れ具合。列挙はどの2行も、順序は隣どうし。
NOMINAL_DELTA_E = 20.0
ORDERED_DELTA_E = 10.0
#: 同時に出る点のレイヤーどうしのどの2色の離れ具合。
POINT_LAYERS_DELTA_E = 10.0


def rgb(color: str) -> tuple[float, float, float]:
    value = color.lstrip("#")
    return tuple(int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))


def linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def contrast(a: str, b: str) -> float:
    def luminance(color):
        r, g, b_ = (linear(c) for c in rgb(color))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b_

    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def delta_e(a: str, b: str) -> float:
    def lab(color):
        r, g, b_ = (linear(c) for c in rgb(color))
        x = (0.4124 * r + 0.3576 * g + 0.1805 * b_) / 0.95047
        y = 0.2126 * r + 0.7152 * g + 0.0722 * b_
        z = (0.0193 * r + 0.1192 * g + 0.9505 * b_) / 1.08883

        def f(t):
            return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116

        return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))

    return math.dist(lab(a), lab(b))


def over_ground(color: str, opacity: float) -> str:
    return "#" + "".join(
        f"{round((opacity * c + (1 - opacity) * g) * 255):02x}" for c, g in zip(rgb(color), rgb(GROUND), strict=True)
    )


def axis(key: str, count: int, **fields) -> DisplayAxisSpec:
    return DisplayAxisSpec(
        key=key,
        property=key,
        categories=tuple(DisplayCategorySpec(key=f"{key}{i}", label=f"行{i}", values=(f"v{i}",), description=f"行{i}の道") for i in range(count)),
        **fields,
    )


# --- 色の配り方 -------------------------------------------------------------------


def test_only_the_first_axis_with_a_palette_gets_colors():
    """2本目の軸（大きさで示す重大度等）に色を配ると、地図のどこにも塗られない色が凡例にだけ並ぶ。"""
    attribute = PrimaryAttributeSpec(
        attr_id="attr_a",
        label="属性A",
        geometry="point",
        display_axes=(axis("main", 3, palette="nominal", hue_slot=4), axis("size", 2)),
    )

    main, size = resolved_display_axes(attribute)

    assert [c["color"] for c in main["categories"]] == nominal_colors(4, 3)
    assert all("color" not in c for c in size["categories"])
    assert [c["key"] for c in size["categories"]] == ["size0", "size1"]
    assert main["key"] == "main"
    assert "palette" not in main and "hue_slot" not in main


def test_a_glyph_reaches_the_screen_only_on_rows_that_declare_one():
    """画面は行が`glyph`の鍵を持つかで絵記号の点か丸い点かを分ける。持たない行に空の値を配ると、丸い点の行まで絵記号になる。"""
    with_glyphs = DisplayAxisSpec(
        key="main",
        property="main",
        palette="nominal",
        hue_slot=4,
        categories=(
            DisplayCategorySpec(key="a", label="行a", values=("a",), description="行aの点", glyph="bag"),
            DisplayCategorySpec(key="b", label="行b", values=("b",), description="行bの点", glyph="drop"),
        ),
    )
    attribute = PrimaryAttributeSpec(
        attr_id="attr_a", label="属性A", geometry="point", display_axes=(with_glyphs, axis("size", 2))
    )

    main, size = resolved_display_axes(attribute)

    assert [c["glyph"] for c in main["categories"]] == ["bag", "drop"]
    assert all("glyph" not in c for c in size["categories"])


def test_an_ordered_axis_is_colored_by_position():
    attribute = PrimaryAttributeSpec(
        attr_id="attr_a", label="属性A", geometry="line", display_axes=(axis("main", 4, palette="ordered"),)
    )

    [main] = resolved_display_axes(attribute)

    assert [c["color"] for c in main["categories"]] == ordered_colors(4)


def test_an_ordered_palette_goes_from_dark_to_light():
    colors = ordered_colors(5)

    lightness = [contrast(color, "#000000") for color in colors]
    assert lightness == sorted(lightness)


def test_an_ordered_axis_of_one_row_still_has_a_color():
    assert len(ordered_colors(1)) == 1


def test_the_same_slot_count_and_tone_always_give_the_same_colors():
    assert nominal_colors(3, 5, "dark") == nominal_colors(3, 5, "dark")
    assert nominal_colors(3, 5, "dark") != nominal_colors(3, 5, "light")
    assert nominal_colors(3, 5) != nominal_colors(4, 5)


@pytest.mark.parametrize("slot", [-1, display_palette.NOMINAL_HUE_SLOTS])
def test_a_hue_slot_outside_the_wheel_is_refused(slot):
    with pytest.raises(ValueError):
        nominal_colors(slot, 3)


@pytest.mark.parametrize("tone", [None, "dark", "light"])
def test_every_nominal_color_stands_out_from_the_ground(tone):
    """どの起点・行数・段でも、配る色は地色に対してコントラスト比3を割らない（明度の上限で守る）。"""
    colors = [
        color
        for slot in range(display_palette.NOMINAL_HUE_SLOTS)
        for count in range(1, 13)
        for color in nominal_colors(slot, count, tone)
    ]

    assert min(contrast(color, GROUND) for color in colors) >= CLASS_COLOR_CONTRAST


def test_every_ordered_color_stands_out_from_the_ground():
    colors = [color for count in range(1, 13) for color in ordered_colors(count)]

    assert min(contrast(color, GROUND) for color in colors) >= CLASS_COLOR_CONTRAST


# --- 本番の宣言 -------------------------------------------------------------------

DISPLAYED = [attr for attr in PRIMARY_ATTRIBUTES if attr.display_axes]
COLORED = [
    (attr, spec, [c["color"] for c in resolved["categories"]])
    for attr in DISPLAYED
    for spec, resolved in zip(attr.display_axes, resolved_display_axes(attr), strict=True)
    if spec.palette is not None
]


@pytest.mark.parametrize(("attr", "spec", "colors"), COLORED, ids=[f"{a.attr_id}:{s.key}" for a, s, _ in COLORED])
def test_colors_in_an_axis_stand_out_from_the_ground_and_from_each_other(attr, spec, colors):
    assert min(contrast(color, GROUND) for color in colors) >= CLASS_COLOR_CONTRAST
    if spec.palette == "nominal":
        pairs, threshold = itertools.combinations(colors, 2), NOMINAL_DELTA_E
    else:
        pairs, threshold = zip(colors, colors[1:]), ORDERED_DELTA_E
    for a, b in pairs:
        assert delta_e(a, b) >= threshold, (attr.attr_id, a, b)


def test_colors_of_point_layers_shown_together_are_not_too_close():
    """点のレイヤーはどれも同時にONにでき、同じ画面に並ぶ。"""
    points = [(attr.attr_id, colors) for attr, _, colors in COLORED if attr.geometry == "point"]

    assert len(points) >= 2
    for (id_a, colors_a), (id_b, colors_b) in itertools.combinations(points, 2):
        for a, b in itertools.product(colors_a, colors_b):
            assert delta_e(a, b) >= POINT_LAYERS_DELTA_E, (id_a, a, id_b, b)


def test_a_glyph_stands_out_from_the_color_of_its_row():
    """絵記号は行の色の角丸四角に載る。下地に溶けると、形で分けるはずの点が同じ四角に見える。"""
    rows = [
        (attr.attr_id, category["color"])
        for attr in DISPLAYED
        for category in resolved_display_axes(attr)[0]["categories"]
        if "glyph" in category
    ]

    assert rows
    for attr_id, color in rows:
        assert contrast(SEMANTIC_COLORS["mark_glyph"], color) >= CLASS_COLOR_CONTRAST, (attr_id, color)


def test_a_road_without_a_value_is_still_visible_on_the_ground():
    """値が無い道は`no_data`の灰を`ROAD_UNKNOWN_OPACITY`の濃さで描く。割ると、道があるのに線が無いように見える。"""
    line = over_ground(SEMANTIC_COLORS["no_data"], ROAD_UNKNOWN_OPACITY)

    assert contrast(line, GROUND) >= NO_DATA_LINE_CONTRAST


