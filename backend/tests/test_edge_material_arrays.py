"""`domain/attributes.py: EdgeMaterialArrays`——探索範囲の区間の材料を持つ器。

標高と勾配を出すSQLは`test_elevation_values.py`、経路の区間の標高属性の組み立ては
`test_road_network.py`が持つ。

材料は**性質だけを表す架空のid**で与える（実在の材料に由来する事実は持ち込まない）。
"""

import numpy as np

from app.domain.attributes import EdgeMaterialArrays
from app.domain.material_catalog import GRADIENT_PERCENT

NUM_A = "num_a"
BOOL_A = "bool_a"
CAT_A = "cat_a"
FILTER_A = "filter_a"


def _arrays(n: int) -> EdgeMaterialArrays:
    gradients = [1.0] * n
    return EdgeMaterialArrays(
        numeric_ids=(GRADIENT_PERCENT, NUM_A),
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
        elevation_present=np.full(n, True),
        elevation_start_m=np.full(n, 0.0),
        elevation_end_m=np.full(n, 5.0),
        elevation_gain_m=np.full(n, 5.0),
        elevation_loss_m=np.full(n, 0.0),
        elevation_max_grade=np.full(n, 7.0),
        elevation_min_grade=np.full(n, -1.0),
    )


class TestTheColumns:
    def test_the_hard_filter_flags_are_keyed_by_filter_name(self):
        arrays = _arrays(2)

        assert arrays.hard_filter_columns()[FILTER_A].tolist() == [True, False]
