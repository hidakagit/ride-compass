"""一次属性の表示定義（`display_axes`）が、正準分類と食い違っていないこと。

**母集団は導出する**（設計原則 構造仕様12）——表示定義を持つ属性すべて、正準分類のタグ
すべてに対して回す。名指しした数件の検査は書かない。

この検査が守るのは「地図の色とルート評価の食い違い」である。表示の行が正準分類の一部を
取りこぼすと、その値の道は地図に出ないまま評価にだけ効く。逆に正準分類に無い値を行へ
書くと、その行は永久に空になる。どちらも例外にならず、画面を見ても気づけない。

後半は配る色の性質（地色から浮くこと・軸の中で見分けられること）を、色を持つ軸すべてに
対して測る。色は規則から作るので、規則の定数を動かしたときに落ちるのはここだけである。
"""

from typing import get_args

import pytest

from app.domain.display_palette import SEMANTIC_COLORS, resolved_display_axes
from app.domain.material_catalog import display_axis_missing_semantics
from app.domain.material_catalog import PRIMARY_ATTRIBUTES
from app.domain.traffic import STOP_POI_KINDS, SupplyPoiKind
from app.domain.road import BAD_OSM_SURFACE_TAGS, GOOD_OSM_SURFACE_TAGS

DISPLAYED = [attr for attr in PRIMARY_ATTRIBUTES if attr.display_axes]


def _linear(hex_color: str) -> tuple[float, float, float]:
    channels = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return r, g, b


def _contrast(a: str, b: str) -> float:
    """WCAG 2.xのコントラスト比。"""
    lum = sorted((0.2126 * r + 0.7152 * g + 0.0722 * b_ for r, g, b_ in (_linear(a), _linear(b))), reverse=True)
    return (lum[0] + 0.05) / (lum[1] + 0.05)


def _lab(hex_color: str) -> tuple[float, float, float]:
    r, g, b = _linear(hex_color)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    fx, fy, fz = (t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116 for t in (x, y, z))
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _delta_e76(a: str, b: str) -> float:
    return sum((p - q) ** 2 for p, q in zip(_lab(a), _lab(b), strict=True)) ** 0.5


def _attr(attr_id: str):
    return next(attr for attr in PRIMARY_ATTRIBUTES if attr.attr_id == attr_id)


def _values(attr_id: str) -> set[object]:
    return {value for axis in _attr(attr_id).display_axes for c in axis.categories for value in c.values}


@pytest.mark.parametrize("attr", DISPLAYED, ids=lambda a: a.attr_id)
def test_行の鍵は属性の中で重複しない(attr) -> None:
    for axis in attr.display_axes:
        keys = [c.key for c in axis.categories]
        assert len(keys) == len(set(keys)), f"{attr.attr_id}:{axis.key} の行の鍵が重複している"


@pytest.mark.parametrize("attr", DISPLAYED, ids=lambda a: a.attr_id)
def test_同じ値が2つの行に属さない(attr) -> None:
    for axis in attr.display_axes:
        values = [v for c in axis.categories for v in c.values]
        assert len(values) == len(set(values)), f"{attr.attr_id}:{axis.key} で同じ値が2行に属している"


@pytest.mark.parametrize("attr", DISPLAYED, ids=lambda a: a.attr_id)
def test_色を持つのは先頭の軸だけ(attr) -> None:
    """地図は先頭の軸で塗る。2本目以降が色を持つと、地図に無い色が凡例にだけ並ぶ。"""
    first, *rest = attr.display_axes
    assert first.palette is not None, f"{attr.attr_id} の先頭の軸にパレットが無い"
    for axis in rest:
        assert axis.palette is None, f"{attr.attr_id}:{axis.key} は先頭ではないのに色を持つ"


@pytest.mark.parametrize("attr", DISPLAYED, ids=lambda a: a.attr_id)
def test_列挙の軸だけが色相の起点を持つ(attr) -> None:
    for axis in attr.display_axes:
        if axis.palette == "nominal":
            assert axis.hue_slot is not None, f"{attr.attr_id}:{axis.key} に色相の起点が無い"
        else:
            assert axis.hue_slot is None, f"{attr.attr_id}:{axis.key} は列挙ではないので起点を持たない"


def test_色相の起点は軸をまたいで重複しない() -> None:
    """**軸をまたいで重複させない。** 同じ起点だと、1行しか持たない軸どうし
    （トンネルと一方通行）が必ず同じ色になり、別の意味が同じ色で地図に載る。"""
    used: dict[int, str] = {}
    assert DISPLAYED, "地図に出す一次属性が1つも無い"
    for attr in DISPLAYED:
        for axis in attr.display_axes:
            if axis.hue_slot is None:
                continue
            where = f"{attr.attr_id}:{axis.key}"
            assert axis.hue_slot not in used, f"起点{axis.hue_slot}が{used[axis.hue_slot]}と{where}で衝突"
            used[axis.hue_slot] = where


def _resolved_colors() -> list[tuple[str, str, list[str]]]:
    """(属性:軸, パレット, 行の色)。色を持つ軸すべて。"""
    out = []
    for attr in DISPLAYED:
        for spec, resolved in zip(attr.display_axes, resolved_display_axes(attr), strict=True):
            colors = [c["color"] for c in resolved["categories"] if "color" in c]
            if colors:
                out.append((f"{attr.attr_id}:{spec.key}", spec.palette, colors))
    return out


def test_色を持たない軸の行は色を配らない() -> None:
    assert DISPLAYED, "地図に出す一次属性が1つも無い"
    for attr in DISPLAYED:
        for spec, resolved in zip(attr.display_axes, resolved_display_axes(attr), strict=True):
            if spec.palette is None:
                assert all("color" not in c for c in resolved["categories"]), f"{attr.attr_id}:{spec.key}"


@pytest.mark.parametrize("where, palette, colors", _resolved_colors(), ids=lambda v: v if isinstance(v, str) else "")
def test_分類の色は地図の地色に対してコントラスト比3以上(where, palette, colors) -> None:
    """これより薄い分類色は「薄い＝対象外」と見分けられない。"""
    ground = SEMANTIC_COLORS["basemap_ground"]
    for color in colors:
        assert _contrast(color, ground) >= 3.0, f"{where} の {color} が地色 {ground} に沈む"


@pytest.mark.parametrize("where, palette, colors", _resolved_colors(), ids=lambda v: v if isinstance(v, str) else "")
def test_軸の中の色は互いに見分けられる(where, palette, colors) -> None:
    """列挙はどの2行も（CIE76で）20以上離す。順序は隣どうしを10以上離す——順序は明度で示すので、
    地色とのコントラストの制約の下で取れる明度の幅が狭い。"""
    if palette == "nominal":
        pairs = [(a, b) for i, a in enumerate(colors) for b in colors[i + 1 :]]
        threshold = 20.0
    else:
        pairs = list(zip(colors, colors[1:]))
        threshold = 10.0
    for a, b in pairs:
        assert _delta_e76(a, b) >= threshold, f"{where} の {a} と {b} が近い"


@pytest.mark.parametrize("attr", DISPLAYED, ids=lambda a: a.attr_id)
def test_面には表示定義を持たせない(attr) -> None:
    assert attr.geometry in ("line", "point"), f"{attr.attr_id} は面なのに行の定義を持っている"


def test_路面の行は正準分類を過不足なく覆う() -> None:
    canonical = GOOD_OSM_SURFACE_TAGS | BAD_OSM_SURFACE_TAGS
    displayed = _values("surface")
    assert displayed - canonical == set(), "正準分類に無い値が行にある（その行は永久に空になる）"
    assert canonical - displayed == set(), "正準分類のタグが行から漏れている（地図に出ないまま評価に効く）"


def test_停止要因の行は種別を過不足なく覆う() -> None:
    assert _values("stop_poi") == set(STOP_POI_KINDS)


def test_補給の行は種別を過不足なく覆う() -> None:
    assert _values("supply_poi") == set(get_args(SupplyPoiKind))


@pytest.mark.parametrize("attr", DISPLAYED, ids=lambda a: a.attr_id)
def test_地図へ出す属性はタイルの系統を持つ(attr) -> None:
    """持たないと、画面がどのソースから読むかを自分で決めることになる。"""
    assert attr.tile_kind is not None, f"{attr.attr_id} に tile_kind が無い"


def test_タイルに載せる線の軸は値が欠けたときの意味を持つ() -> None:
    """地図は、値の無い道が現れうる軸（`unknown`）にだけ「不明」の行と破線を出す。意味が引けない軸は凡例を組めない。"""
    lines = [attr for attr in DISPLAYED if attr.geometry == "line" and attr.tile_kind is not None]
    assert lines, "タイルに載せる線の一次属性が1つも無い"
    for attr in lines:
        for axis in attr.display_axes:
            assert display_axis_missing_semantics(attr, axis.property) is not None, f"{attr.attr_id}:{axis.key}"
