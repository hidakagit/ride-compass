"""`domain/map_display.py`——地図に出すものの束ね方（グループ・種別・情報源・レイヤー）の宣言。

入口は`map_layer_label`（レイヤーの名前）と、生成物として画面へ配る宣言そのもの。宣言どうしは名前（`key`）で
指し合い、型はその名前が実在することを保証しないので、指した先があることを確かめる。描く寸法の値そのものは見ない
（宣言の書き写しになる）。

ここで見ないもの:
- 気象の要素の宣言（チップ・名前付きソース・コマの規則）→ `test_weather_elements.py`
- 一次属性の行の色と、値の無い道の線が地色から見えること → `test_display_palette.py`
- 一次属性の表示の行の宣言 → `test_material_catalog.py`
- 宣言を生成物へ書き出すこと → `scripts/export_openapi.py`の生成物のドリフト検査
"""

import pytest

from app.domain import map_display
from app.domain.map_display import MapLayerSpec, map_layer_label

ALL_SPECS = [spec for _, spec in map_display.MAP_LAYERS] + list(map_display.AXIS_LAYER_SPECS.values())


def keys(declarations) -> list[str]:
    return [declaration.key for declaration in declarations]


def test_a_layer_with_its_own_label_is_called_by_it():
    assert map_layer_label("anything", MapLayerSpec("ownFetch", None, label="名前")) == "名前"


def test_a_layer_drawing_a_primary_attribute_takes_the_name_of_the_attribute():
    attribute = next(attr for attr in map_display.PRIMARY_ATTRIBUTES if attr.display_axes)

    assert map_layer_label(attribute.attr_id, MapLayerSpec("road_surface", None)) == attribute.label


def test_a_layer_without_any_name_is_refused():
    with pytest.raises(ValueError, match="名前が無い"):
        map_layer_label("not_an_attribute", MapLayerSpec("ownFetch", None))


def test_every_layer_on_the_map_has_a_name():
    """名前の無いレイヤーはチップに何も書けない。"""
    assert all(map_layer_label(layer_id, spec) for layer_id, spec in map_display.MAP_LAYERS)


def test_every_layer_reads_a_declared_data_source():
    """情報源が宣言に無いと、取得状態（読み込み中・空・失敗）を判定できない。"""
    sources = set(keys(map_display.MAP_LAYER_DATA_SOURCES))

    assert {spec.data_source for spec in ALL_SPECS} <= sources


def test_every_layer_belongs_to_a_declared_category_and_every_category_to_a_declared_group():
    categories = set(keys(map_display.MAP_LAYER_CATEGORIES))
    groups = set(keys(map_display.MAP_OVERLAY_GROUPS))

    assert {spec.category for spec in ALL_SPECS if spec.category is not None} <= categories
    assert {category.group for category in map_display.MAP_LAYER_CATEGORIES} <= groups


def test_no_chip_is_empty():
    """グループには種別が、種別にはレイヤーがある。空のチップは押しても何も出ない。"""
    used_categories = {spec.category for _, spec in map_display.MAP_LAYERS}

    assert set(keys(map_display.MAP_LAYER_CATEGORIES)) <= used_categories
    assert set(keys(map_display.MAP_OVERLAY_GROUPS)) <= {c.group for c in map_display.MAP_LAYER_CATEGORIES}


def test_every_layer_has_a_declared_kind_and_nature():
    assert {spec.kind for spec in ALL_SPECS} <= set(map_display.MAP_LAYER_KINDS)
    assert {spec.data_nature for spec in ALL_SPECS} <= set(map_display.MAP_LAYER_DATA_NATURES)


@pytest.mark.parametrize(
    "declarations",
    [map_display.MAP_OVERLAY_GROUPS, map_display.MAP_LAYER_CATEGORIES, map_display.MAP_LAYER_DATA_SOURCES],
    ids=["グループ", "種別", "情報源"],
)
def test_names_that_are_pointed_at_are_not_repeated(declarations):
    """同じ名前が2つあると、指した側はどちらか一方だけを読む。"""
    assert len(set(keys(declarations))) == len(declarations)


def test_no_layer_appears_twice():
    """一次属性・気象のグループ・ルートの名前が重なると、同じ名前のレイヤーが2つ並ぶ。"""
    assert len(set(map_display.MAP_LAYER_IDS)) == len(map_display.MAP_LAYER_IDS)


#: ズームから値への曲線（数の組の並び）。名前で拾わず、形で拾う。
CURVES = {
    name: value
    for name, value in vars(map_display).items()
    if isinstance(value, tuple)
    and value
    and all(
        type(stop) is tuple and len(stop) == 2 and all(isinstance(x, (int, float)) for x in stop) for stop in value
    )
}


def test_there_are_curves_to_check():
    assert CURVES


@pytest.mark.parametrize("name", sorted(CURVES))
def test_a_curve_over_the_zoom_has_strictly_ascending_stops(name):
    """地図の式（MapLibreの`interpolate`・`step`）は入力の段が厳密に昇順でないと式ごと失敗し、レイヤーが黙って消える。"""
    zooms = [zoom for zoom, _ in CURVES[name]]

    assert zooms == sorted(set(zooms))


def test_the_difficulty_boundaries_are_strictly_ascending():
    boundaries = list(map_display.DEFAULT_DIFFICULTY_BOUNDARIES)

    assert boundaries == sorted(set(boundaries))
