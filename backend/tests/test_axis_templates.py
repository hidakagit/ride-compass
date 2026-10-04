"""`domain/axis_templates.py`——軸の得点を求める2つの演算（区分線形・値ごとの対応表）。

入口は`evaluate_breakpoint_linear`と`evaluate_categorical`。どちらも配列で受け、欠損と引けない値はNaNで返す。
`evaluate_categorical`は材料の列が本番で届く形（分類の材料の`domain/attributes.py: CategoricalColumn`、真偽の材料の真偽の配列と
1.0/0.0/NaNの数値の配列、Pythonの値から作ったobjectの配列）ごとに確かめる——同じ値には形によらず同じ得点になる。

ここで見ないもの:
- 材料の線形結合・前処理・得点の丸め・0次条件 → `test_axis_definitions.py`
"""

import bisect
import math

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.attributes import CategoricalColumn
from app.domain.axis_templates import evaluate_breakpoint_linear, evaluate_categorical


def _object_column(values):
    column = np.empty(len(values), dtype=object)
    column[:] = values
    return column


def _straight_line(x: float, breakpoints: list[tuple[float, float]]) -> float:
    """折れ線を1点ずつ素直に引く（両端は端の値で止める）。"""
    if math.isnan(x):
        return math.nan
    xs = [p[0] for p in breakpoints]
    if x <= xs[0]:
        return breakpoints[0][1]
    if x >= xs[-1]:
        return breakpoints[-1][1]
    right = bisect.bisect_right(xs, x)
    (x0, y0), (x1, y1) = breakpoints[right - 1], breakpoints[right]
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


@st.composite
def _breakpoints(draw):
    xs = sorted(draw(st.sets(st.integers(min_value=-1000, max_value=1000), min_size=1, max_size=6)))
    ys = draw(st.lists(st.floats(min_value=0.0, max_value=100.0), min_size=len(xs), max_size=len(xs)))
    return [(float(x), y) for x, y in zip(xs, ys)]


_material_values = st.one_of(st.floats(min_value=-2000.0, max_value=2000.0), st.just(math.nan))


@given(breakpoints=_breakpoints(), values=st.lists(_material_values, min_size=1, max_size=20))
def test_the_score_follows_the_line_between_the_breakpoints_and_stops_at_its_ends(breakpoints, values):
    """欠損（NaN）は得点を持たない。端より外は端の得点で止まる。"""
    scores = evaluate_breakpoint_linear(np.array(values), breakpoints)

    expected = [_straight_line(x, breakpoints) for x in values]
    assert scores.tolist() == pytest.approx(expected, rel=1e-9, abs=1e-9, nan_ok=True)


ROAD_TYPES = {"primary": 80.0, "residential": 30.0, "track": 50.0}
# 対応表のどのキーより小さい・大きい値、間に挟まる値、欠損。
ROAD_VALUES = ["residential", "aaa", "zzz", "secondary", None, "track", "primary"]
ROAD_SCORES = [30.0, math.nan, math.nan, math.nan, math.nan, 50.0, 80.0]


@pytest.mark.parametrize(
    "column",
    [CategoricalColumn.encode(ROAD_VALUES), _object_column(ROAD_VALUES)],
    ids=["CategoricalColumn", "object"],
)
def test_a_value_the_table_does_not_hold_and_a_missing_value_have_no_score(column):
    assert evaluate_categorical(column, ROAD_TYPES).tolist() == pytest.approx(ROAD_SCORES, nan_ok=True)


FLAG = {True: 10.0, False: 90.0}


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        (np.array([True, False, True]), [10.0, 90.0, 10.0]),
        (np.array([1.0, 0.0, math.nan]), [10.0, 90.0, math.nan]),
        (_object_column([True, False, None]), [10.0, 90.0, math.nan]),
    ],
    ids=["bool", "float", "object"],
)
def test_a_flag_is_scored_the_same_whichever_array_carries_it(column, expected):
    """欠損を持たない真偽の材料は真偽の配列で、「不明」を持つものは数値の配列で届く。"""
    assert evaluate_categorical(column, FLAG).tolist() == pytest.approx(expected, nan_ok=True)
