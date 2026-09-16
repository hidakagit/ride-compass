"""軸スタジオの分布プレビュー（`services/axis_preview_service.py`）の純ロジック。

分位・階級化・生値の算出はいずれも純関数で、`POST /api/admin/axis-definitions/
preview-distribution`と`GET /api/admin/material-catalog/{id}/distribution`の計算本体。
"""

import pytest

from app.domain.axis_definitions import BreakpointLinearShape, CategoricalShape, MaterialTerm
from app.domain.attributes import WIRED_LANDCOVER_KEYS
from app.infrastructure.road_graph_repository import WayMaterialSampleRow
from app.services.axis_preview_service import (
    HISTOGRAM_BINS,
    _distribution,
    _raw_value,
    load_way_sample,
)


def _bins_cover(bins, value: float) -> bool:
    """`value`がいずれかの階級の範囲に入るか（最上位階級は上限を含む）。"""
    for i, (low, high, _) in enumerate(bins):
        last = i == len(bins) - 1
        if low <= value < high or (last and value <= high):
            return True
    return False


class TestDistribution:
    def test_empty_pairs_return_zeroed_distribution(self):
        result = _distribution([])
        assert result.sample_ways == 0
        assert result.bins == []

    def test_positive_values_start_at_zero(self):
        # 正の値だけの分布は従来どおり0起点（0は常に範囲へ含める）。
        pairs = [(100.0, v) for v in (1.0, 2.0, 3.0, 4.0)]
        result = _distribution(pairs)
        assert result.bins[0][0] == 0.0
        assert len(result.bins) == HISTOGRAM_BINS
        assert result.bins[-1][1] > 0

    def test_negative_values_are_not_collapsed_into_the_first_bin(self):
        # 統合レビュー第6回の指摘I-6: 下限を0に固定していたため、生値が負の軸
        # （openness等）は全サンプルが階級0へ潰れ「1本だけの棒」になっていた。
        pairs = [(100.0, v) for v in (-160.0, -120.0, -80.0, -40.0, -5.0)]
        result = _distribution(pairs)

        assert result.bins[0][0] <= -160.0, "下限がデータ下端を覆っていない"
        assert result.bins[-1][1] >= 0.0, "0が範囲に含まれていない"
        occupied = [b for b in result.bins if b[2] > 0]
        assert len(occupied) > 1, "全サンプルが1つの階級へ潰れている"
        assert sum(b[2] for b in result.bins) == pytest.approx(1.0, abs=1e-4)

    def test_every_sample_falls_inside_some_bin(self):
        for values in ([-160.0, -80.0, -5.0], [0.0, 1.0, 2.0], [-3.0, 0.0, 7.0]):
            result = _distribution([(10.0, v) for v in values])
            for v in values:
                assert _bins_cover(result.bins, v), f"{v}がどの階級にも入らない（{values}）"

    def test_quantiles_and_bins_agree_on_sign(self):
        # 分位が負を返しているのにヒストグラムが正の範囲しか持たない、という
        # 画面上で矛盾する2つの数字が出ないこと。
        pairs = [(100.0, v) for v in (-144.0, -99.0, -79.0, -12.0, -2.0)]
        result = _distribution(pairs)
        assert result.quantiles["p50"] < 0
        assert result.bins[0][0] <= result.quantiles["p10"]

    def test_zero_share_counts_only_exact_zero(self):
        # 「ゼロ」は値がちょうど0のこと。負の値を混ぜても割合は変わらない。
        pairs = [(100.0, 0.0), (100.0, -5.0), (100.0, 3.0), (100.0, 0.0)]
        result = _distribution(pairs)
        assert result.zero_share == pytest.approx(0.5)

    def test_all_samples_at_zero_do_not_divide_by_zero(self):
        result = _distribution([(100.0, 0.0), (100.0, 0.0)])
        assert result.zero_share == pytest.approx(1.0)
        assert len(result.bins) == HISTOGRAM_BINS
        assert result.total_km == pytest.approx(0.2)


class TestRawValue:
    def _shape(self, terms):
        return BreakpointLinearShape(terms=terms, preprocess="identity", breakpoints=[[0.0, 0.0], [1.0, 100.0]])

    def test_weighted_sum_of_terms(self):
        shape = self._shape([
            MaterialTerm(material="a", weight=1.0, required=True),
            MaterialTerm(material="b", weight=1.5, required=True),
        ])
        assert _raw_value(shape, {"a": 2.0, "b": 4.0}) == pytest.approx(8.0)

    def test_missing_required_material_returns_none(self):
        shape = self._shape([MaterialTerm(material="a", weight=1.0, required=True)])
        assert _raw_value(shape, {"a": None}) is None

    def test_missing_optional_material_is_skipped(self):
        shape = self._shape([
            MaterialTerm(material="a", weight=1.0, required=False),
            MaterialTerm(material="b", weight=1.0, required=True),
        ])
        assert _raw_value(shape, {"a": None, "b": 3.0}) == pytest.approx(3.0)

    def test_all_materials_missing_returns_none(self):
        # 「1件も観測されていない」と「観測した結果が0だった」を区別する。
        shape = self._shape([MaterialTerm(material="a", weight=1.0, required=False)])
        assert _raw_value(shape, {"a": None}) is None

    def test_preprocess_abs_is_applied(self):
        shape = BreakpointLinearShape(
            terms=[MaterialTerm(material="a", weight=1.0, required=True)],
            preprocess="abs",
            breakpoints=[[0.0, 0.0], [1.0, 100.0]],
        )
        assert _raw_value(shape, {"a": -7.0}) == pytest.approx(7.0)

    def test_categorical_shape_has_no_raw_value(self):
        shape = CategoricalShape(material="highway", mapping={"primary": 50.0})
        assert _raw_value(shape, {"highway": "primary"}) is None


class TestLoadWaySample:
    """標本行から材料辞書を組み立てる経路（`load_way_sample`）。

    ルーターのテストは分布関数ごとmonkeypatchし、上のテストは純関数だけを見るため、
    両者の境目にあるこの組み立てだけがどのテストからも実行されていなかった。
    """

    @staticmethod
    def _row(**overrides):
        fields = dict(
            length_m=120.0,
            highway="residential",
            tags={"lit": "yes"},
            surface="asphalt",
            counts_length_m=120.0,
            accident_count=1.0,
            intersection_count=2,
            poi_counts={"drink": 1},
            landcover_percents={key: 12.5 for key in WIRED_LANDCOVER_KEYS},
            is_designated=False,
        )
        fields.update(overrides)
        return WayMaterialSampleRow(**fields)

    class _Repository:
        def __init__(self, rows):
            self._rows = rows

        async def sample_way_rows(self, sample_percent, limit, bbox):
            return self._rows

        async def get_accident_years_covered(self):
            return 3

    async def test_sample_rows_are_assembled_into_material_dicts(self):
        sample = await load_way_sample(self._Repository([self._row()]), 2.0, 10, None)
        assert len(sample) == 1
        length_m, materials = sample[0]
        assert length_m == 120.0
        # 土地被覆は配線済みクラスぶんが材料として解決される（クラスを1つ増やしても
        # ここは並びから導かれるため追従が要らない）。
        for key in WIRED_LANDCOVER_KEYS:
            assert materials[key] == pytest.approx(12.5)
        # 舗装は専用列（tags jsonbには入らない）から解決される。
        assert materials["surface"] == "asphalt"
        assert materials["surface_good"] == 1.0

    async def test_rows_without_landcover_resolve_to_missing_materials(self):
        sample = await load_way_sample(
            self._Repository([self._row(landcover_percents=None)]), 2.0, 10, None
        )
        _, materials = sample[0]
        assert all(materials[key] is None for key in WIRED_LANDCOVER_KEYS)

    async def test_zero_length_rows_are_dropped(self):
        sample = await load_way_sample(self._Repository([self._row(length_m=0.0)]), 2.0, 10, None)
        assert sample == []
