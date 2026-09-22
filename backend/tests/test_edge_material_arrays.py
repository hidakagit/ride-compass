"""`domain/attributes.py: EdgeMaterialArrays`——タイル1枚ぶんの材料を持つ器。

標高と勾配を出すSQLは`test_elevation_values.py`、ディスクから復元するときの突き合わせは
`test_graph_material_cache.py`・`test_cache_identity.py`が持つ。

材料は**性質だけを表す架空のid**で与える（実在の材料に由来する事実は持ち込まない）。
唯一の例外が勾配で、`elevation_attribute`が材料の列から平均勾配を引くため実idが要る。
"""

import numpy as np
import pytest

from app.domain.attributes import EdgeMaterialArrays
from app.domain.material_sql import MATERIAL_ID_GRADIENT_PERCENT

NUM_A = "num_a"
BOOL_A = "bool_a"
CAT_A = "cat_a"
FILTER_A = "filter_a"


def _arrays(
    edge_ids: list[str],
    *,
    gradients: list[float] | None = None,
    elevation_present: list[bool] | None = None,
    starts: list[float] | None = None,
) -> EdgeMaterialArrays:
    n = len(edge_ids)
    gradients = gradients if gradients is not None else [1.0] * n
    return EdgeMaterialArrays(
        edge_ids=edge_ids,
        numeric_ids=(MATERIAL_ID_GRADIENT_PERCENT, NUM_A),
        numeric_values=np.array([[g, 10.0 * (i + 1)] for i, g in enumerate(gradients)]),
        boolean_ids=(BOOL_A,),
        boolean_values=np.array([[i % 2 == 0] for i in range(n)]),
        categorical_ids=(CAT_A,),
        categorical_values=np.array([[f"v{i}"] for i in range(n)], dtype=object),
        hard_filter_ids=(FILTER_A,),
        hard_filter_flags=np.array([[i == 0] for i in range(n)]),
        distance_m=np.full(n, 100.0),
        bearing_deg=np.full(n, 90.0),
        mid_lat=np.full(n, 35.0),
        mid_lon=np.full(n, 139.0),
        elevation_present=np.array(
            elevation_present if elevation_present is not None else [True] * n
        ),
        elevation_start_m=np.array(starts if starts is not None else [0.0] * n),
        elevation_end_m=np.full(n, 5.0),
        elevation_gain_m=np.full(n, 5.0),
        elevation_loss_m=np.full(n, 0.0),
        elevation_max_grade=np.full(n, 7.0),
        elevation_min_grade=np.full(n, -1.0),
    )


class TestTheColumns:
    def test_the_id_list_spans_every_dtype(self):
        """真偽・分類を落とすと、それらの材料を持つ表が「別物」と判定されて毎回
        作り直される。
        """
        arrays = _arrays(["a", "b"])

        assert set(arrays.material_ids) == {MATERIAL_ID_GRADIENT_PERCENT, NUM_A, BOOL_A, CAT_A}

    def test_a_column_is_found_whatever_its_dtype(self):
        """数値だけを探すと、真偽・分類の材料が無いものとして扱われる。"""
        arrays = _arrays(["a", "b"])

        assert arrays.column(NUM_A).tolist() == [10.0, 20.0]
        assert arrays.column(BOOL_A).tolist() == [True, False]
        assert arrays.column(CAT_A).tolist() == ["v0", "v1"]

    def test_an_unknown_material_is_an_error_rather_than_an_empty_column(self):
        """空を返すと、綴り違いの材料が「全区間で欠損」として静かに評価から抜ける。"""
        with pytest.raises(KeyError, match="no_such_material"):
            _arrays(["a"]).column("no_such_material")

    def test_the_hard_filter_flags_are_keyed_by_filter_name(self):
        arrays = _arrays(["a", "b"])

        assert arrays.hard_filter_columns()[FILTER_A].tolist() == [True, False]


class TestElevationAttribute:
    def test_a_row_that_is_not_there_has_no_attribute(self):
        """別のタイルのEdgeを引くと行が無い。例外にすると、タイル境界の区間で落ちる。"""
        assert _arrays(["a"]).elevation_attribute("b") is None

    def test_a_row_without_computed_elevation_has_no_attribute(self):
        """0で埋めて返すと、標高が未計算の区間が「平坦」として表示される。"""
        arrays = _arrays(["a", "b"], elevation_present=[True, False])

        assert arrays.elevation_attribute("a") is not None
        assert arrays.elevation_attribute("b") is None

    def test_the_average_grade_comes_from_the_gradient_material(self):
        """標高の列とは別に、勾配は材料として持っている。ここで別の列を引くと、区間
        インスペクタの平均勾配だけが常に空になる。
        """
        arrays = _arrays(["a", "b"], gradients=[3.5, -2.0])

        assert arrays.elevation_attribute("a").average_grade == 3.5
        assert arrays.elevation_attribute("b").average_grade == -2.0

    def test_the_row_is_read_at_its_own_index(self):
        arrays = _arrays(["a", "b", "c"], starts=[1.0, 2.0, 3.0])

        assert arrays.elevation_attribute("c").start_elevation_m == 3.0

    def test_a_missing_number_becomes_none_instead_of_nan(self):
        """NaNをそのまま応答へ載せるとJSONにできない。**フィールドごとに独立して**
        欠損しうる（勾配だけ無い区間がある）。
        """
        arrays = _arrays(["a"], gradients=[np.nan], starts=[np.nan])
        attribute = arrays.elevation_attribute("a")

        assert attribute.average_grade is None
        assert attribute.start_elevation_m is None
        assert attribute.end_elevation_m == 5.0
