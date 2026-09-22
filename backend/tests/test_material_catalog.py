"""`domain/material_catalog.py`——材料の宣言から、下流が要るものを導く。

カタログの中身（どの材料が実在し、どのSQLで求まるか）は`test_material_values.py`、
欠損率の測り方は`test_material_coverage.py`、公開APIの形は
`test_material_catalog_routes.py`、地図表示の導出は`test_axis_display.py`が持つ。

**カタログは丸ごと差し替える。** 性質だけを表す架空の材料で見る——実在の材料に由来する
事実を持ち込むと、材料が1つ増えただけでここが落ちる。
"""

import pytest

from app.domain import material_catalog
from app.domain.material_catalog import (
    CoverageExcluded,
    EdgeMaterialCoverageSpec,
    MaterialSpec,
    WayMaterialCoverageSpec,
    material_array_columns,
    material_array_group,
    material_coverage_exclusions,
    material_coverage_specs,
    material_dtype,
    material_value_sql,
)

WAY_UNKNOWN = WayMaterialCoverageSpec(
    missing_condition="TRUE", source="架空", missing_semantics="unknown"
)
WAY_DEFINITE = WayMaterialCoverageSpec(
    missing_condition="TRUE", source="架空", missing_semantics="definite"
)
EDGE_UNKNOWN = EdgeMaterialCoverageSpec(
    present_count_sql="SELECT 0", source="架空", missing_semantics="unknown"
)
NOT_MEASURED = CoverageExcluded(reason="架空", missing_semantics="definite")


def _spec(material_id: str, dtype: str = "numeric", *, coverage=WAY_DEFINITE, **overrides):
    return MaterialSpec(
        material_id=material_id,
        label=overrides.pop("label", f"材料[{material_id}]"),
        description="架空の材料",
        dtype=dtype,
        coverage=coverage,
        **overrides,
    )


@pytest.fixture
def catalog(monkeypatch):
    """カタログを差し替える。返る辞書へ入れた材料だけが見える。"""
    fake: dict[str, MaterialSpec] = {}
    monkeypatch.setattr(material_catalog, "MATERIAL_CATALOG", fake)
    return fake


class TestLabels:
    def test_a_known_value_gets_its_japanese_name_beside_the_tag(self):
        spec = _spec("cat_a", "categorical", value_labels={"v": "論理名"})

        assert spec.value_label("v") == "論理名 - v"

    def test_a_value_nobody_translated_is_shown_as_it_is(self):
        """新しいOSMタグ値がDBへ現れても軸スタジオの値候補が落ちない。区切りの" - "も
        付けない——論理名の無い値が「 - v」として並ぶ。
        """
        spec = _spec("cat_a", "categorical", value_labels={"v": "論理名"})

        assert spec.value_label("other") == "other"

    def test_the_material_itself_is_labelled_the_same_way(self):
        assert _spec("num_a", label="数値").full_label() == "数値 - num_a"


class TestBoolDefault:
    def test_a_boolean_whose_missing_means_unknown_keeps_nan(self):
        """「不明」を「非該当」へ畳むと、タグの無い道が確定的に偽として評価される。"""
        assert _spec("bool_a", "boolean", coverage=WAY_UNKNOWN).bool_default == "nan"

    def test_a_boolean_whose_missing_is_a_definite_value_folds_to_false(self):
        assert _spec("bool_a", "boolean", coverage=WAY_DEFINITE).bool_default == "false"

    @pytest.mark.parametrize("dtype", ["numeric", "categorical"])
    def test_a_material_that_is_not_boolean_answers_without_looking(self, dtype):
        assert _spec("a", dtype, coverage=WAY_UNKNOWN).bool_default == "false"


class TestWhichMatrixAMaterialLandsOn:
    def test_a_categorical_material_goes_to_the_object_matrix(self):
        assert material_array_group(_spec("cat_a", "categorical")) == "categorical"

    def test_a_numeric_material_goes_to_the_float_matrix(self):
        assert material_array_group(_spec("num_a")) == "numeric"

    def test_a_boolean_material_goes_to_the_bool_matrix(self):
        assert material_array_group(_spec("bool_a", "boolean", coverage=WAY_DEFINITE)) == "boolean"

    def test_a_boolean_that_can_be_unknown_goes_to_the_float_matrix(self):
        """bool配列はNaNを持てない。真偽の側へ載せると「不明」が偽へ落ちる。"""
        spec = _spec("bool_a", "boolean", coverage=WAY_UNKNOWN)

        assert material_array_group(spec) == "numeric"


class TestTheColumnOrder:
    def test_the_three_groups_split_the_materials_that_have_a_value(self, catalog):
        catalog.update(
            {
                "num_a": _spec("num_a", value_sql="1"),
                "bool_a": _spec("bool_a", "boolean", coverage=WAY_DEFINITE, value_sql="TRUE"),
                "cat_a": _spec("cat_a", "categorical", value_sql="'x'"),
            }
        )

        numeric, boolean, categorical = material_array_columns()

        assert (numeric, boolean, categorical) == (("num_a",), ("bool_a",), ("cat_a",))

    def test_a_material_without_a_value_is_in_no_group(self, catalog):
        """値を求められない材料（リクエスト時に決まる風等）の列を空けておくと、
        行列の幅と材料の数が食い違う。
        """
        catalog.update({"num_a": _spec("num_a", value_sql="1"), "num_b": _spec("num_b")})

        assert material_array_columns() == (("num_a",), (), ())

    def test_the_order_inside_a_group_does_not_depend_on_the_declaration_order(self, catalog):
        """宣言の順で並べると、カタログの行を入れ替えただけで焼き込み済みの列がずれる。"""
        catalog.update(
            {
                "num_c": _spec("num_c", value_sql="1"),
                "num_a": _spec("num_a", value_sql="1"),
                "num_b": _spec("num_b", value_sql="1"),
            }
        )

        assert material_array_columns()[0] == ("num_a", "num_b", "num_c")

    def test_a_boolean_that_can_be_unknown_is_listed_with_the_numbers(self, catalog):
        catalog.update(
            {"bool_a": _spec("bool_a", "boolean", coverage=WAY_UNKNOWN, value_sql="TRUE")}
        )

        assert material_array_columns() == (("bool_a",), (), ())


class TestValueSql:
    def test_only_the_materials_that_can_be_asked_of_the_db_are_listed(self, catalog):
        catalog.update({"num_a": _spec("num_a", value_sql="1 + 1"), "num_b": _spec("num_b")})

        assert material_value_sql() == {"num_a": "1 + 1"}


class TestCoverage:
    def test_the_measured_and_the_excluded_split_every_material(self, catalog):
        """片方の一覧だけを見ると、測り方を書き忘れた材料が「測ったが0%」として
        画面に出る。
        """
        catalog.update(
            {
                "num_a": _spec("num_a", coverage=WAY_DEFINITE),
                "num_b": _spec("num_b", coverage=EDGE_UNKNOWN),
                "num_c": _spec("num_c", coverage=NOT_MEASURED),
            }
        )

        measured = set(material_coverage_specs())
        excluded = set(material_coverage_exclusions())

        assert measured == {"num_a", "num_b"}
        assert excluded == {"num_c"}
        assert measured | excluded == set(catalog)

    def test_the_exclusion_carries_its_reason(self, catalog):
        """理由の無い除外は、次に見た人が測るべきか判断できない。"""
        catalog.update(
            {
                "num_a": _spec(
                    "num_a",
                    coverage=CoverageExcluded(reason="実測できない", missing_semantics="unknown"),
                )
            }
        )

        assert material_coverage_exclusions() == {"num_a": "実測できない"}


class TestLookingUpAnUnknownMaterial:
    def test_an_unknown_id_has_no_dtype_instead_of_raising(self, catalog):
        """綴り違いで軸カタログの配信ごと落とさない。"""
        catalog.update({"num_a": _spec("num_a")})

        assert material_dtype("num_a") == "numeric"
        assert material_dtype("no_such_material") is None
