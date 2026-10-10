"""`domain/attributes.py`——区間の材料と標高属性を運ぶ型。

入口は次のとおり。
- `CategoricalColumn`: 分類の材料1列を語彙への番号で持ち、値・数・一致を区間ごとに引く
- `EdgeMaterialArrays`: dtypeごとの行列を、材料id・0次フィルタ名から列で引く
- `ElevationAttribute.reversed_as`: 同じ地形を逆方向に走った区間の標高属性

ここで見ないもの:
- 標高と勾配を出すSQL（`elevation_values_sql`）と、その逆順が`reversed_as`に一致すること → `test_elevation_values.py`
- 道路網の配列から材料と標高属性を組み立てること → `test_road_network.py`
"""

import math

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from app.domain.attributes import CategoricalColumn, EdgeMaterialArrays, ElevationAttribute


def test_values_are_numbered_in_the_order_they_appear_and_none_is_zero():
    column = CategoricalColumn.encode(["b", None, "a", "b"])

    assert column.codes.tolist() == [1, 0, 2, 1]
    assert column.vocab == (None, "b", "a")


@given(st.lists(st.one_of(st.none(), st.sampled_from(["a", "b", "c", "d"]))))
def test_each_row_reads_back_the_value_it_was_encoded_from(values):
    column = CategoricalColumn.encode(values)

    assert [column.value_at(row) for row in range(len(values))] == values


def test_taking_rows_keeps_the_vocabulary():
    column = CategoricalColumn.encode(["a", "b", None])

    taken = column.take(np.array([2, 0]))

    assert [taken.value_at(row) for row in range(len(taken))] == [None, "a"]
    assert taken.vocab == column.vocab


def test_a_lookup_gives_nan_for_no_value_and_for_values_missing_from_the_table():
    column = CategoricalColumn.encode(["a", None, "b"])

    looked_up = column.lookup({"a": 1.5})

    assert looked_up[0] == 1.5
    assert math.isnan(looked_up[1])
    assert math.isnan(looked_up[2])


def test_no_value_matches_nothing():
    column = CategoricalColumn.encode(["a", None, "b"])

    assert column.equals("a").tolist() == [True, False, False]
    assert column.equals(None).tolist() == [False, False, False]


def arrays() -> EdgeMaterialArrays:
    n = 2
    nan = np.full(n, np.nan)
    return EdgeMaterialArrays(
        numeric_ids=("num_a", "num_b"),
        numeric_values=np.array([[1.0, 2.0], [3.0, np.nan]]),
        categorical_ids=("cat_a",),
        categorical_columns=(CategoricalColumn.encode(["x", None]),),
        hard_filter_ids=("filter_a", "filter_b"),
        hard_filter_flags=np.array([[True, False], [False, True]]),
        distance_m=np.array([100.0, 200.0]),
        bearing_deg=nan,
        mid_lat=nan,
        mid_lon=nan,
        elevation_present=np.zeros(n, dtype=bool),
        elevation_gain_m=nan,
        elevation_loss_m=nan,
    )


def test_every_material_is_found_by_its_id_whatever_its_dtype():
    columns = arrays().columns()

    assert set(columns) == {"num_a", "num_b", "cat_a"}
    assert columns["num_a"].tolist() == [1.0, 3.0]
    assert columns["num_b"][0] == 2.0
    assert columns["cat_a"].value_at(0) == "x"


def test_each_hard_filter_is_found_by_its_name():
    flags = arrays().hard_filter_columns()

    assert flags["filter_a"].tolist() == [True, False]
    assert flags["filter_b"].tolist() == [False, True]


def climb() -> ElevationAttribute:
    return ElevationAttribute(
        edge_id="1:0:f",
        elevation_gain_m=25.0,
        elevation_loss_m=5.0,
        average_grade=4.0,
    )


def test_the_reverse_turns_climbs_into_descents():
    reverse = climb().reversed_as("1:0:r")

    assert reverse.model_dump() == {
        "edge_id": "1:0:r",
        "elevation_gain_m": 5.0,
        "elevation_loss_m": 25.0,
        "average_grade": -4.0,
    }


def test_missing_grades_stay_missing_in_the_reverse():
    missing = climb().model_copy(update={"average_grade": None})

    assert missing.reversed_as("1:0:r").average_grade is None

