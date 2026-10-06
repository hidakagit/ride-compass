"""`domain/evaluation.py`——静的スコア行列を組む間の軸定義の読み方。"""

from collections.abc import Iterator, Mapping

import numpy as np

from app.domain.attributes import EdgeMaterialArrays
from app.domain.axis_definitions import AxisDefinition, BreakpointLinearShape, MaterialTerm, replace_axis_definitions
from app.domain.evaluation import build_static_edge_score_matrix
from tests.axis_system_fixture import replaced_axis_definitions


def published_axis(axis_id: str, *materials: str) -> AxisDefinition:
    """材料を2つ以上読む公開軸（内訳の材料が行列の列に載る）。"""
    return AxisDefinition(
        axis_id=axis_id,
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material=material) for material in materials], breakpoints=[(0.0, 0.0), (1.0, 100.0)]
        ),
        default_weight=1.0,
        label="軸",
        is_published=True,
    )


def no_materials(n: int) -> EdgeMaterialArrays:
    nan = np.full(n, np.nan)
    return EdgeMaterialArrays(
        numeric_ids=(), numeric_values=np.empty((n, 0)),
        boolean_ids=(), boolean_values=np.empty((n, 0), dtype=bool),
        categorical_ids=(), categorical_columns=(),
        hard_filter_ids=(), hard_filter_flags=np.empty((n, 0), dtype=bool),
        distance_m=np.full(n, 100.0), bearing_deg=nan, mid_lat=nan, mid_lon=nan,
        elevation_present=np.zeros(n, dtype=bool), elevation_start_m=nan, elevation_end_m=nan,
        elevation_gain_m=nan, elevation_loss_m=nan, elevation_max_grade=nan, elevation_min_grade=nan,
    )


class ReplacingWhenRead(Mapping[str, np.ndarray]):
    """読まれた時点で軸定義を差し替える観測の材料（空）。組む途中に軸の保存が重なった場面を作る。"""

    def __init__(self, replacement: Mapping[str, AxisDefinition]):
        self._replacement = replacement

    def __iter__(self) -> Iterator[str]:
        replace_axis_definitions(self._replacement)
        return iter(())

    def __getitem__(self, key: str) -> np.ndarray:
        raise KeyError(key)

    def __len__(self) -> int:
        return 0


def test_axes_saved_while_building_do_not_mix_into_the_matrix():
    """組む途中で軸が差し替わっても、列は組み始めの軸の集合だけから組む。

    途中で`AXIS_DEFINITIONS`を読み直すと、別スレッドで組む生成が保存の途中の辞書を読み、
    鍵が欠けて落ちる・軸の集合が食い違った行列になる。
    """
    before = published_axis("before", "rain_1h_mm", "rain_3h_mm")
    after = published_axis("after", "rain_6h_mm", "rain_12h_mm")

    with replaced_axis_definitions({"before": before}):
        matrix = build_static_edge_score_matrix(no_materials(2), ReplacingWhenRead({"after": after}))

    assert matrix.axis_ids == ["before"]
    assert {"rain_1h_mm", "rain_3h_mm"} <= set(matrix.material_ids)
    assert not {"rain_6h_mm", "rain_12h_mm"} & set(matrix.material_ids)
