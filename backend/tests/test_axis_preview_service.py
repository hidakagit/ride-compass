"""`services/axis_preview_service.py`——延長で重み付けた分布（`weighted_distribution`）と分位点（`weighted_quantiles`）、
軸の下書きの形で道の標本から求める生値の分布（`raw_value_distribution`）。

ここで見ないもの:
- 軸の生値（重み付き和・欠損・前処理・対応表の軸に生値が無いこと） → `test_axis_definitions.py`
- 標本をDBから引いて持っておくこと（`load_way_sample`・期限付きの置き場） → 読むだけの結線
- 分布を管理APIの応答へ出すこと → `test_axis_admin_routes.py`（軸の下書き）・`test_material_catalog_routes.py`（材料）
"""

import pytest

from app.domain.axis_definitions import BreakpointLinearShape, MaterialTerm
from app.services.axis_preview_service import raw_value_distribution, weighted_distribution, weighted_quantiles


def test_quantiles_weight_by_length_not_by_way_count():
    """短い道が何本あっても、長い道1本の値が中央値を決める。

    本数で数えると「細い路地が大多数だから軸は効いている」と読み違える——実際に走る
    距離のほとんどが1本の幹線なら、その値がルート選択を支配する。
    """
    pairs = [(10.0, 0.0), (10.0, 0.0), (10.0, 0.0), (10_000.0, 100.0)]

    assert weighted_quantiles(pairs, [("p50", 0.5)], digits=1) == {"p50": 100.0}


class TestDistribution:
    def test_empty_pairs_return_zeroed_distribution(self):
        result = weighted_distribution([])
        assert result.sample_ways == 0
        assert result.bins == []

    @pytest.mark.parametrize("values", [[1.0, 2.0, 3.0, 4.0], [-160.0, -120.0, -80.0, -40.0, -5.0]])
    def test_range_covers_every_sample_and_zero_without_collapsing(self, values):
        # 下限を0に固定すると、生値が負になる軸で全サンプルが範囲の外（階級0）へ潰れる。
        # 分位は標本の値なので、範囲が標本を覆えば分位と階級の符号も揃う。
        result = weighted_distribution([(100.0, v) for v in values])

        assert result.bins[0][0] <= min(*values, 0.0)
        assert result.bins[-1][1] >= max(*values, 0.0)
        assert len([b for b in result.bins if b[2] > 0]) == len(values)

    def test_outliers_above_the_drawn_range_land_in_the_last_bin(self):
        # 描画範囲はp99の少し上まで。その外の延長も割合から落とさない。
        pairs = [(100.0, 1.0)] * 99 + [(50.0, 1000.0)]
        result = weighted_distribution(pairs)
        assert result.bins[-1][1] < 1000.0
        assert result.bins[-1][2] == pytest.approx(50.0 / 9950.0, abs=1e-5)
        assert sum(b[2] for b in result.bins) == pytest.approx(1.0, abs=1e-4)

    def test_zero_share_counts_only_exact_zero(self):
        # 「ゼロ」は値がちょうど0のこと。負の値を混ぜても割合は変わらない。
        pairs = [(100.0, 0.0), (100.0, -5.0), (100.0, 3.0), (100.0, 0.0)]
        result = weighted_distribution(pairs)
        assert result.zero_share == pytest.approx(0.5)

    def test_all_samples_at_zero_do_not_divide_by_zero(self):
        result = weighted_distribution([(100.0, 0.0), (100.0, 0.0)])
        assert result.zero_share == pytest.approx(1.0)
        assert result.total_km == pytest.approx(0.2)


def test_the_draft_shape_gives_raw_values_before_its_breakpoints_and_skips_ways_without_them():
    """軸スタジオは、下書きの形の生値（折れ点を通す前）の分布を見て折れ点を置く。材料の無い道は数えない。"""
    shape = BreakpointLinearShape(terms=[MaterialTerm(material="num_a", weight=2.0)], breakpoints=[(0.0, 0.0), (10.0, 100.0)])
    sample = [(1000.0, {"num_a": 3.0, "num_b": 9.0}), (500.0, {"num_a": None, "num_b": 1.0}), (500.0, {"num_b": 1.0})]

    result = raw_value_distribution(shape, sample)

    assert (result.sample_ways, result.total_km, result.quantiles["p50"]) == (1, 1.0, 6.0)
