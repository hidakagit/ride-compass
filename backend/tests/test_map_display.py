"""`domain/map_display.py`——地図に出すものの束ね方（グループ・種別・情報源・レイヤー）の宣言。

入口は`map_layer_label`（レイヤーの名前）・説明の文を宣言から組む`ordered_ends_text`・`size_sentence`と、生成物として
画面へ配る宣言そのもの。宣言どうしは名前（`key`）で指し合い、型はその名前が実在することを保証しないので、指した先が
あることを確かめる。描く寸法の値そのものは見ない（宣言の書き写しになる）。レイヤーの説明は、ほかの宣言から差し込む
部分だけを見る。文を組む関数には架空の行を渡し、宣言を変えると文が追従することを見る。

ここで見ないもの:
- 気象の要素の宣言（チップ・名前付きソース・コマの規則）と予測が届く先の語 → `test_weather_elements.py`
- 一次属性の行の色と、値の無い道の線が地色から見えること → `test_display_palette.py`
- 一次属性の表示の行の宣言 → `test_material_catalog.py`
- 宣言を生成物へ書き出すこと → `scripts/export_openapi.py`の生成物のドリフト検査
- 説明の差し込み口を軸カタログの値で埋めること → frontend `mapLayers.test.ts`
"""

import pytest

from app.domain import map_display
from app.domain.landcover import LANDCOVER_CLASSES
from app.domain.map_display import MapLayerSpec, map_layer_label, ordered_ends_text, size_sentence
from app.domain.registry import DisplayAxisSpec, DisplayCategorySpec
from app.domain.weather_elements import WEATHER_ELEMENTS

ALL_SPECS = [spec for _, spec in map_display.MAP_LAYERS] + list(map_display.AXIS_LAYER_SPECS.values())
LAYERS = dict(map_display.MAP_LAYERS)


def text_of(layer_id: str, field: str) -> str:
    """説明の文のうち、差し込み口を除いた文。"""
    return "".join(part for part in getattr(LAYERS[layer_id], field) if isinstance(part, str))


def keys(declarations) -> list[str]:
    return [declaration.key for declaration in declarations]


def axis(*rows: tuple[str, int | None], palette=None) -> DisplayAxisSpec:
    """架空の行（名前・半径）を並べた見方。"""
    return DisplayAxisSpec(
        key="axis",
        property="prop",
        palette=palette,
        categories=tuple(
            DisplayCategorySpec(key=f"k{i}", label=label, values=(f"v{i}",), description="架空の行", radius_px=radius)
            for i, (label, radius) in enumerate(rows)
        ),
    )


@pytest.mark.parametrize(
    ("rows", "named"),
    [([("重い", 6), ("軽い", 3)], "重い"), ([("重い", 3), ("軽い", 6)], "軽い")],
    ids=["先頭が大きい", "半径を入れ替えた"],
)
def test_the_size_sentence_names_the_row_drawn_largest(rows, named):
    """半径の宣言を入れ替えて文が追従しないと、説明が小さく描く方を「大きく表示」と書く。"""
    assert size_sentence(axis(*rows)) == f"{named}は円を大きく表示します。"


@pytest.mark.parametrize("rows", [[("重い", 4), ("軽い", 4)], [("重い", 6), ("軽い", None)]], ids=["同じ半径", "半径の無い行"])
def test_the_size_sentence_is_refused_when_the_rows_are_not_told_apart_by_size(rows):
    """大きさで分けていない見方に「大きく表示」と書かない。"""
    with pytest.raises(ValueError, match="違う半径"):
        size_sentence(axis(*rows))


def test_the_ordered_colors_are_described_from_the_first_and_the_last_row():
    """行を足し替えても、説明は濃く塗る先頭の行と明るく塗る末尾の行を名指す。"""
    dark, light = map_display.ORDERED_END_COLOR_NAMES

    text = ordered_ends_text(axis(("先頭", None), ("中ほど", None), ("末尾", None), palette="ordered"))

    assert text == f"「先頭」ほど{dark}、「末尾」ほど{light}"


def test_the_ordered_colors_are_not_described_for_an_unordered_axis():
    with pytest.raises(ValueError, match="順序のある分類ではない"):
        ordered_ends_text(axis(("先頭", None), ("末尾", None), palette="nominal"))


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


@pytest.mark.parametrize("layer_id", ["stop_poi", "supply_poi"])
def test_point_layers_list_the_kinds_by_the_names_of_the_legend_rows(layer_id):
    """凡例と違う名前で種別を挙げると、説明に書いた種別を凡例で探せない。"""
    attribute = next(attr for attr in map_display.PRIMARY_ATTRIBUTES if attr.attr_id == layer_id)

    for category in attribute.display_axes[0].categories:
        assert category.label in text_of(layer_id, "description")


def test_landcover_text_names_the_classes_it_does_not_paint():
    """塗らない分類を書かないと、その分類の土地が地図で空白に見える理由が分からない。"""
    unpainted = [cls.label for cls in LANDCOVER_CLASSES if not cls.painted]
    assert unpainted

    for label in unpainted:
        assert label in text_of("landcover", "description")
        assert f"{label}は塗りません" in text_of("landcover", "panel_hint")


def test_disaster_text_names_every_element_of_the_disaster_chip():
    """要素を足しても説明に名前が出ないと、チップが何を出すのか読めない。"""
    elements = [element for element in WEATHER_ELEMENTS if element.group == "disaster"]
    assert elements

    for element in elements:
        assert element.label in text_of("disaster", "description")
        assert element.label in text_of("disaster", "panel_hint")


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
