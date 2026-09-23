"""`domain/material_catalog.py`——材料の宣言の型と、カタログから導く一覧（値の式・行列の列・欠損率の測り方）。

ここで見ないもの:
- 値の式（SQL）が実際に値を返すか → `test_material_values.py`（DBへ流す）
- 一次属性の表示定義と正準分類の突き合わせ → `test_primary_attribute_display.py`
- 欠損率の集計 → `test_material_coverage.py`
- カタログを配るAPI → `test_material_catalog_routes.py`

**導く関数はカタログを差し替えて見る。** どの材料が実在するかではなく、「値の式を持つ真偽の材料」の
ように性質だけを持つ架空の材料を与える。差し替えないのは末尾の`TestTheDeclaredCatalog`だけで、
型でも導出でも保証されていない本物の宣言の性質を、全材料に対して見る。
"""

from typing import get_args

import pytest
from pydantic import ValidationError

from app.domain import material_catalog

MaterialSpec = material_catalog.MaterialSpec


def spec(material_id, dtype="numeric", value_sql=None, coverage=None, **fields):
    return MaterialSpec(
        material_id=material_id,
        label=f"{material_id}の名前",
        description="説明",
        dtype=dtype,
        value_sql=value_sql,
        coverage=coverage
        or material_catalog.CoverageExcluded(reason=f"{material_id}は測らない", missing_semantics="unknown"),
        **fields,
    )


def way(missing_semantics):
    return material_catalog.WayMaterialCoverageSpec(
        missing_condition="x IS NULL", source="元", missing_semantics=missing_semantics
    )


def edge(missing_semantics):
    return material_catalog.EdgeMaterialCoverageSpec(
        present_condition="x IS NOT NULL", source="元", missing_semantics=missing_semantics
    )


@pytest.fixture
def catalog(monkeypatch):
    specs = {
        "num": spec("num", value_sql="n", coverage=way("unknown")),
        "flag_definite": spec("flag_definite", "boolean", value_sql="f", coverage=way("definite")),
        "flag_unknown": spec("flag_unknown", "boolean", value_sql="u", coverage=edge("unknown")),
        "cat": spec("cat", "categorical", value_sql="c"),
        "no_sql": spec("no_sql"),
    }
    monkeypatch.setattr(material_catalog, "MATERIAL_CATALOG", specs)
    return specs


class TestMaterialSpec:
    @pytest.mark.parametrize(
        ("fields", "reason"),
        [
            ({"dtype": "numeric", "total_unit": "回"}, "total_unit"),
            ({"dtype": "boolean", "value_labels": {"a": "エー"}}, "value_labels"),
            (
                {
                    "dtype": "categorical",
                    "reference_points": [material_catalog.MaterialReferencePoint(label="目安", value=1.0)],
                },
                "reference_points",
            ),
        ],
        ids=["単位の無い総量", "分類でない材料の値の対訳", "数値でない材料の目安"],
    )
    def test_declarations_that_do_not_fit_the_dtype_are_refused(self, fields, reason):
        with pytest.raises(ValidationError, match=reason):
            spec("m", **fields)

    def test_declarations_that_fit_the_dtype_are_accepted(self):
        spec(
            "counted",
            unit="回/km",
            total_unit="回",
            reference_points=[material_catalog.MaterialReferencePoint(label="目安", value=1.0)],
        )
        spec("named", "categorical", value_labels={"a": "エー"})

    @pytest.mark.parametrize(("value", "expected"), [("a", "エー - a"), ("b", "b")])
    def test_a_value_is_labelled_by_its_translation_when_there_is_one(self, value, expected):
        assert spec("m", "categorical", value_labels={"a": "エー"}).value_label(value) == expected

    def test_the_full_label_pairs_the_name_with_the_id(self):
        assert spec("m").full_label() == "mの名前 - m"

    @pytest.mark.parametrize(
        ("dtype", "missing_semantics", "expected"),
        [("boolean", "unknown", "nan"), ("boolean", "definite", "false"), ("numeric", "unknown", "false")],
    )
    def test_how_a_missing_flag_is_held_follows_what_missing_means(self, dtype, missing_semantics, expected):
        coverage = material_catalog.CoverageExcluded(reason="測らない", missing_semantics=missing_semantics)

        assert spec("m", dtype, coverage=coverage).bool_default == expected


class TestLookup:
    @pytest.mark.parametrize(("material_id", "known", "dtype"), [("cat", True, "categorical"), ("ghost", False, None)])
    def test_a_material_is_known_only_if_the_catalog_has_it(self, catalog, material_id, known, dtype):
        assert material_catalog.is_known_material(material_id) is known
        assert material_catalog.material_dtype(material_id) == dtype


class TestDerivedFromTheCatalog:
    @pytest.mark.parametrize(
        ("material_id", "group"),
        [("num", "numeric"), ("flag_definite", "boolean"), ("flag_unknown", "numeric"), ("cat", "categorical")],
    )
    def test_the_matrix_a_material_goes_to_follows_its_dtype_and_what_missing_means(self, catalog, material_id, group):
        """欠損を「不明」とする真偽の材料は、「非該当」と混同しないよう欠損を持てる数値の行列へ載せる。"""
        assert material_catalog.material_array_group(catalog[material_id]) == group

    def test_array_columns_are_the_materials_with_a_value_grouped_and_sorted(self, catalog):
        assert material_catalog.material_array_columns() == (("flag_unknown", "num"), ("flag_definite",), ("cat",))

    def test_value_sql_covers_only_materials_that_have_one(self, catalog):
        assert material_catalog.material_value_sql() == {
            "num": "n",
            "flag_definite": "f",
            "flag_unknown": "u",
            "cat": "c",
        }

    def test_every_material_is_either_measured_for_coverage_or_excluded_with_a_reason(self, catalog):
        assert material_catalog.material_coverage_specs() == {
            "num": catalog["num"].coverage,
            "flag_definite": catalog["flag_definite"].coverage,
            "flag_unknown": catalog["flag_unknown"].coverage,
        }
        assert material_catalog.material_coverage_exclusions() == {"cat": "catは測らない", "no_sql": "no_sqlは測らない"}


class TestTheDeclaredCatalog:
    """本物の宣言に対する性質。型でも導出でも保証されていないものだけを置く。"""

    def test_every_material_is_filed_under_its_own_id(self):
        """キーとidが食い違うと、材料が在るかの判定と画面に出るidが別の材料を指す。"""
        mismatched = {
            key: s.material_id for key, s in material_catalog.MATERIAL_CATALOG.items() if key != s.material_id
        }

        assert material_catalog.MATERIAL_CATALOG
        assert mismatched == {}

    @pytest.mark.parametrize(
        ("labels", "literal"),
        [
            (material_catalog.POPULATION_LABELS, material_catalog.Population),
            (material_catalog.MISSING_SEMANTICS_DISPLAY, material_catalog.MissingSemantics),
        ],
        ids=["母集団の表示名", "欠損の扱いの見出し"],
    )
    def test_every_value_the_admin_screen_groups_by_has_a_heading(self, labels, literal):
        assert set(labels) == set(get_args(literal))
