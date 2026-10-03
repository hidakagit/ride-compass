"""`domain/material_catalog.py`——材料の宣言と、宣言から導く一覧・判定。

入口は次のとおり。
- `MaterialSpec`: dtypeと噛み合わない宣言を断る・表示用の名前・欠損を配列でどう持つか
- カタログから導く一覧: `is_known_material`・`material_dtype`・`material_array_group`・`material_array_columns`・
  `material_value_sql`・`material_coverage_specs`・`material_coverage_exclusions`
- `display_axis_missing_semantics`: 地図の表示の軸の値が欠けたときの意味
- `tile_runtime_scales`: タイルの生値に掛ける、実行時に決まる係数

カタログの中身は架空の材料（`num_a` 等）へ差し替えて与える。後ろの2節だけは本番の宣言（材料のカタログと
一次属性の表示の行）そのものを読み、型でも導出でも保証されない不変条件を確かめる。

ここで見ないもの:
- 材料の値を求めるSQLが返す値 → `test_material_values.py`
- 欠損率をDBで数えること → `test_material_coverage.py`
- 一次属性の行に配る色 → `test_display_palette.py`
- 停止要因の点を地図でまとめるSQL（`stop_poi_map_group_sql`）→ タイルを焼くテスト（`test_road_graph_repository_contracts.py`）
- カタログを配るAPI → `test_material_catalog_routes.py`・`test_axis_catalog_routes.py`
"""

from typing import get_args

import pytest
from pydantic import ValidationError

from app.domain import material_catalog
from app.domain.material_catalog import (
    CoverageExcluded,
    EdgeMaterialCoverageSpec,
    MaterialReferencePoint,
    MaterialSpec,
    WayMaterialCoverageSpec,
)
from app.domain.registry import PrimaryAttributeSpec
from app.domain.traffic import STOP_POI_KINDS, SupplyPoiKind

ATTR_A = PrimaryAttributeSpec(attr_id="attr_a", label="属性A", geometry="line", tile_kind="road_surface")
ATTR_B = PrimaryAttributeSpec(attr_id="attr_b", label="属性B", geometry="line", tile_kind="road_surface")

WAY_UNKNOWN = WayMaterialCoverageSpec(missing_condition="w.x IS NULL", source="x", missing_semantics="unknown")
WAY_DEFINITE = WayMaterialCoverageSpec(missing_condition="w.y IS NULL", source="y", missing_semantics="definite")
EDGE_UNKNOWN = EdgeMaterialCoverageSpec(present_condition="em.z IS NOT NULL", source="z", missing_semantics="unknown")
EXCLUDED = CoverageExcluded(reason="都度引く", missing_semantics="unknown")


def spec(material_id: str, dtype="numeric", coverage=WAY_UNKNOWN, **fields) -> MaterialSpec:
    fields.setdefault("tile_property", None)
    fields.setdefault("value_sql", f"w.{material_id}")
    return MaterialSpec(
        material_id=material_id, label=f"名前{material_id}", description="説明", dtype=dtype, coverage=coverage, **fields
    )


@pytest.fixture
def catalog(monkeypatch):
    """数値・真偽（欠損が不明／確定）・分類の材料と、SQLで求められない材料・タイルに載る材料の組。"""
    specs = [
        spec("num_b", tile_property="num_b_tile", primary_attribute=ATTR_A),
        spec("num_a", coverage=EDGE_UNKNOWN),
        spec("bool_definite", "boolean", WAY_DEFINITE, tile_property="bool_tile", primary_attribute=ATTR_A),
        spec("bool_unknown", "boolean", WAY_UNKNOWN),
        spec("cat_a", "categorical", WAY_DEFINITE, tile_property="cat_tile", primary_attribute=ATTR_B),
        spec("dynamic_a", value_sql=None, coverage=EXCLUDED),
        spec(
            "per_year_a",
            tile_property="per_year_tile",
            tile_property_runtime_scale="per_accident_year",
            coverage=EXCLUDED,
        ),
    ]
    monkeypatch.setattr(material_catalog, "MATERIAL_CATALOG", {s.material_id: s for s in specs})


@pytest.mark.parametrize(
    "fields",
    [
        {"total_unit": "回"},  # 掛ける相手の単位が無い
        {"value_labels": {"a": "あ"}},  # 対訳は分類の値にだけ付く
        {"reference_points": [MaterialReferencePoint(label="目安", value=1.0)], "dtype": "boolean"},
    ],
)
def test_a_declaration_that_does_not_fit_its_dtype_is_refused(fields):
    fields.setdefault("dtype", "numeric")
    with pytest.raises(ValidationError):
        spec("x", **fields)


def test_declarations_that_fit_their_dtype_are_accepted():
    spec("count_a", unit="回/km", total_unit="回")
    spec("cat_a", "categorical", value_labels={"a": "あ"})
    spec("num_a", reference_points=[MaterialReferencePoint(label="目安", value=1.0)])


def test_a_value_is_shown_with_its_label_when_the_table_has_one():
    material = spec("cat_a", "categorical", value_labels={"paved": "舗装"})

    assert material.value_label("paved") == "舗装 - paved"
    assert material.value_label("new_value") == "new_value"
    assert material.full_label() == "名前cat_a - cat_a"


@pytest.mark.parametrize(
    ("dtype", "coverage", "expected"),
    [
        ("boolean", WAY_UNKNOWN, "nan"),  # 不明を非該当と混同しない
        ("boolean", WAY_DEFINITE, "false"),  # タグの不在は非該当
        ("boolean", EXCLUDED, "nan"),
        ("numeric", WAY_UNKNOWN, "false"),
    ],
)
def test_a_missing_boolean_is_nan_only_when_missing_means_unknown(dtype, coverage, expected):
    assert spec("x", dtype, coverage).bool_default == expected


def test_materials_are_known_by_their_id(catalog):
    assert material_catalog.is_known_material("cat_a")
    assert not material_catalog.is_known_material("nothing")
    assert material_catalog.material_dtype("cat_a") == "categorical"
    assert material_catalog.material_dtype("nothing") is None


def test_a_boolean_that_can_be_unknown_goes_to_the_numeric_matrix(catalog):
    groups = {
        material_id: material_catalog.material_array_group(material)
        for material_id, material in material_catalog.MATERIAL_CATALOG.items()
    }

    assert groups["num_a"] == "numeric"
    assert groups["bool_definite"] == "boolean"
    assert groups["bool_unknown"] == "numeric"
    assert groups["cat_a"] == "categorical"


def test_the_matrix_columns_are_the_materials_with_sql_sorted_by_id(catalog):
    numeric, boolean, categorical = material_catalog.material_array_columns()

    assert numeric == ("bool_unknown", "num_a", "num_b", "per_year_a")
    assert boolean == ("bool_definite",)
    assert categorical == ("cat_a",)


def test_the_value_sql_lists_only_materials_that_sql_can_compute(catalog):
    value_sql = material_catalog.material_value_sql()

    assert "dynamic_a" not in value_sql
    assert value_sql["num_a"] == "w.num_a"


def test_every_material_is_either_measured_for_coverage_or_excluded_with_a_reason(catalog):
    measured = material_catalog.material_coverage_specs()
    excluded = material_catalog.material_coverage_exclusions()

    assert measured["num_a"] == EDGE_UNKNOWN
    assert measured["bool_definite"] == WAY_DEFINITE
    assert excluded == {"dynamic_a": "都度引く", "per_year_a": "都度引く"}
    assert set(measured) | set(excluded) == set(material_catalog.MATERIAL_CATALOG)


def test_a_display_axis_takes_the_missing_semantics_of_the_material_on_its_tile_property(catalog):
    assert material_catalog.display_axis_missing_semantics(ATTR_A, "num_b_tile") == "unknown"
    assert material_catalog.display_axis_missing_semantics(ATTR_A, "bool_tile") == "definite"
    assert material_catalog.display_axis_missing_semantics(ATTR_B, "cat_tile") == "definite"


def test_a_display_axis_without_its_material_has_no_missing_semantics(catalog):
    assert material_catalog.display_axis_missing_semantics(ATTR_B, "num_b_tile") is None  # 別の属性の材料
    assert material_catalog.display_axis_missing_semantics(ATTR_A, "nothing") is None


@pytest.mark.parametrize(("years", "expected"), [([2021, 2022, 2023, 2024], 0.25), ([2024], 1.0)])
def test_accident_counts_are_scaled_by_the_number_of_years(catalog, years, expected):
    assert material_catalog.tile_runtime_scales(years) == {"per_year_tile": expected}


def test_without_any_accident_year_there_is_no_scale(catalog):
    assert material_catalog.tile_runtime_scales([]) == {}


# --- 本番のカタログ -------------------------------------------------------------


def test_every_material_is_registered_under_its_own_id():
    """読む側は鍵で引き、引いた材料の`material_id`を書き出す。食い違うと別の名前で配られる。"""
    assert all(key == material.material_id for key, material in material_catalog.MATERIAL_CATALOG.items())


def test_no_two_materials_share_a_tile_property():
    """同じ列に2つの材料が焼かれると、地図はどちらか一方の値で塗る。"""
    properties = [m.tile_property for m in material_catalog.MATERIAL_CATALOG.values() if m.tile_property]
    assert len(properties) == len(set(properties))


def test_a_material_whose_value_depends_on_the_direction_is_not_baked_into_tiles():
    """タイルの線は向きを持たないので、往復で値の違う材料を1つの列に焼くと片方の向きの値が消える。"""
    directed = [m for m in material_catalog.MATERIAL_CATALOG.values() if m.tile_property_direction_dependent]

    assert directed
    assert all(material.tile_property is None for material in directed)


def test_every_population_and_missing_semantics_has_a_heading():
    """管理画面の欠損率は母集団と欠損の扱いで束ねて見出しを付ける。見出しの無い値の材料は表から落ちる。"""
    assert set(material_catalog.POPULATION_LABELS) == set(get_args(material_catalog.Population))
    assert set(material_catalog.MISSING_SEMANTICS_DISPLAY) == set(get_args(material_catalog.MissingSemantics))


# --- 本番の一次属性の表示の宣言 -----------------------------------------------------

DISPLAYED = [attr for attr in material_catalog.PRIMARY_ATTRIBUTES if attr.display_axes]


def row_values(attr_id: str) -> set:
    attribute = next(attr for attr in material_catalog.PRIMARY_ATTRIBUTES if attr.attr_id == attr_id)
    return {value for category in attribute.display_axes[0].categories for value in category.values}


@pytest.mark.parametrize("attr", DISPLAYED, ids=lambda attr: attr.attr_id)
def test_only_the_first_axis_declares_a_palette(attr):
    """地図は先頭の軸で塗る。2本目以降の軸（大きさで示す重大度等）は色を持たない。"""
    first, *rest = attr.display_axes

    assert first.palette is not None
    assert all(spec.palette is None and spec.hue_slot is None and spec.tone is None for spec in rest)


@pytest.mark.parametrize("attr", DISPLAYED, ids=lambda attr: attr.attr_id)
def test_a_value_belongs_to_one_row_only(attr):
    """2つの行に属する値は、地図ではどちらか一方の色でしか塗られない。"""
    for spec in attr.display_axes:
        values = [value for category in spec.categories for value in category.values]
        assert len(values) == len(set(values)), spec.key


@pytest.mark.parametrize("attr", DISPLAYED, ids=lambda attr: attr.attr_id)
def test_a_row_key_is_not_repeated_in_an_axis(attr):
    """凡例の絞り込みは行を鍵で持ち、停止要因の点は行の鍵でまとめる。重なると2つの行が1つとして振る舞う。"""
    for spec in attr.display_axes:
        row_keys = [category.key for category in spec.categories]
        assert len(row_keys) == len(set(row_keys)), spec.key


def test_a_line_has_exactly_one_axis():
    """道の線は1本の軸の行で塗る（線のプロパティが属性そのもの）。2本目の軸は地図のどこにも出ない。"""
    lines = [attr for attr in DISPLAYED if attr.geometry == "line"]

    assert lines
    assert all(len(attr.display_axes) == 1 for attr in lines)


def test_an_area_has_no_rows():
    """面は配信元の画像の色で塗り、行で塗り分けない。行を持たせると、地図に無い色が凡例にだけ並ぶ。"""
    assert not [attr.attr_id for attr in DISPLAYED if attr.geometry == "area"]


@pytest.mark.parametrize("attr", DISPLAYED, ids=lambda attr: attr.attr_id)
def test_an_attribute_on_the_map_reads_a_tile(attr):
    assert attr.tile_kind is not None


def test_no_two_nominal_axes_start_from_the_same_hue():
    """同じ起点だと、1行しか持たない軸どうし（トンネルと一方通行）が必ず同じ色になる。"""
    slots = [attr.display_axes[0].hue_slot for attr in DISPLAYED if attr.display_axes[0].palette == "nominal"]

    assert None not in slots
    assert len(slots) == len(set(slots))


@pytest.mark.parametrize(
    "attr",
    [attr for attr in DISPLAYED if attr.geometry == "line"],
    ids=lambda attr: attr.attr_id,
)
def test_a_line_axis_knows_what_a_missing_value_means(attr):
    """道の線の行は、値が欠けた道を「不明」として出すか、タグの不在として出すかを、載せる材料の宣言から引く。"""
    assert material_catalog.display_axis_missing_semantics(attr, attr.display_axes[0].property) is not None


@pytest.mark.parametrize(
    ("attr_id", "kinds"),
    [("stop_poi", STOP_POI_KINDS), ("supply_poi", set(get_args(SupplyPoiKind)))],
)
def test_the_rows_of_a_point_layer_cover_every_kind_it_draws(attr_id, kinds):
    """行に無い種別の点は地図から消え、凡例にも出ない。種別に無い行は何も塗らない。種別の分類は取込が持ち、
    行の束ね方（利用者から見て同じものを1行にする）は表示が持つので、片方からもう片方を導けない。"""
    assert row_values(attr_id) == set(kinds)
