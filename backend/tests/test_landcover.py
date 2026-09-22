"""`domain/landcover.py`——土地被覆の画素ヒストグラムを、クラス別の割合へ直す。

どの画素を数えるかは`derive_raster_materials`の仕事で、ここが負うのは「数えた結果をどう
割合にするか」だけ。**その判定はDB側で行うため、DBへ通して確かめる。**
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.landcover import (
    LANDCOVER_CLASSES,
    LULC_INVALID_VALUES,
    MIN_VALID_PIXELS,
    PERCENT_CLASSES,
    LULC_BUILT,
    LULC_CLOUDS,
    LULC_TREES,
    LULC_WATER,
    LandcoverPercentages,
    class_percentages_sql,
    raster_set_fingerprint,
)


class TestClassRegistry:
    """クラスの宣言そのものは書き写さない。全件に対して成り立つことだけを見る。"""

    def test_every_class_has_a_column_to_write_its_share_into(self):
        """綴りが違っても集計は例外にならず、その列だけが常に0になる。"""
        fields = set(LandcoverPercentages.model_fields)

        assert LANDCOVER_CLASSES
        for cls in LANDCOVER_CLASSES:
            assert cls.percent_field in fields, cls.percent_field

    def test_no_class_is_one_of_the_values_excluded_from_the_denominator(self):
        """両方に入れると、「有効画素の何%か」の分母と分子が食い違う。"""
        assert {cls.value for cls in LANDCOVER_CLASSES} & LULC_INVALID_VALUES == set()

    def test_values_and_columns_are_unique(self):
        """同じ画素値が2クラスにあると、どちらの列へ入るかが並び順で決まる。"""
        assert len({cls.value for cls in LANDCOVER_CLASSES}) == len(LANDCOVER_CLASSES)
        assert len({cls.percent_field for cls in LANDCOVER_CLASSES}) == len(LANDCOVER_CLASSES)

    def test_labels_are_distinct(self):
        """凡例と区間インスペクタが同じ名前を2つ並べない。"""
        assert len({cls.label for cls in LANDCOVER_CLASSES}) == len(LANDCOVER_CLASSES)

class TestRasterSetFingerprint:

    def test_the_same_set_in_a_different_order_gives_the_same_fingerprint(self):
        """順に依存させると、同じ構成が別物に見える。"""
        assert raster_set_fingerprint(["a.tif", "b.tif"]) == raster_set_fingerprint(["b.tif", "a.tif"])

    def test_only_the_file_name_matters(self):
        """同じラスタを別のディレクトリへ置いただけで派生物を捨て直さない。"""
        assert raster_set_fingerprint(["/data/a.tif"]) == raster_set_fingerprint(["/mnt/other/a.tif"])

    def test_adding_a_raster_changes_the_fingerprint(self):
        assert raster_set_fingerprint(["a.tif"]) != raster_set_fingerprint(["a.tif", "b.tif"])

    def test_an_empty_set_still_has_a_fingerprint(self):
        assert raster_set_fingerprint([])

    def test_it_is_short_enough_to_put_in_a_key(self):
        assert len(raster_set_fingerprint(["a.tif"])) == 16


class TestPercentagesFromPixelCounts:

    # road_graph_session（conftest.py）と同じDBを使うため、docs/conventions/testing.md
    # パターン2どおり loop_scope="module"・xdist_group="postgis" が要る。
    pytestmark = [
        pytest.mark.asyncio(loop_scope="module"),
        pytest.mark.xdist_group(name="postgis"),
        pytest.mark.postgis,
    ]

    @staticmethod
    async def _percentages(session: AsyncSession, counts: dict[int, int]):
        """1区間ぶんのヒストグラムを渡して割合の行を受け取る（該当なしはNone）。"""
        rows = ", ".join(f"(1, 0, {cls}, {n})" for cls, n in counts.items()) or "(1, 0, NULL, 0)"
        sql = class_percentages_sql(
            f"SELECT * FROM (VALUES {rows}) AS v(osm_way_id, segment_index, cls, n)"
        )
        return (await session.execute(text(sql))).first()

    async def test_a_single_class_fills_the_whole_share(self, road_graph_session):
        row = await self._percentages(road_graph_session, {LULC_BUILT: 100})

        assert row is not None
        assert row.valid_pixels == 100
        assert row.built_percent == 100.0
        assert row.trees_percent == 0.0

    async def test_the_shares_add_up_to_one_hundred(self, road_graph_session):
        row = await self._percentages(
            road_graph_session, {LULC_TREES: 30, LULC_BUILT: 20, LULC_WATER: 50}
        )

        assert row is not None
        assert sum(getattr(row, name) for name, _ in PERCENT_CLASSES) == 100.0

    async def test_clouds_and_no_data_are_left_out_of_the_denominator(self, road_graph_session):
        """分母へ入れると、雲に覆われた区間だけ全クラスの割合が一様に小さく出る。"""
        row = await self._percentages(
            road_graph_session, {LULC_TREES: 50, LULC_WATER: 50, LULC_CLOUDS: 100, 0: 100}
        )

        assert row is not None
        assert row.valid_pixels == 100
        assert row.trees_percent == 50.0
        assert row.water_percent == 50.0

    async def test_a_segment_covered_only_by_clouds_has_no_row(self, road_graph_session):
        assert await self._percentages(road_graph_session, {LULC_CLOUDS: 100}) is None

    async def test_too_few_valid_pixels_means_no_row(self, road_graph_session):
        """0と区別できるよう、行そのものを作らない。"""
        row = await self._percentages(road_graph_session, {LULC_TREES: MIN_VALID_PIXELS - 1})

        assert row is None

    async def test_exactly_the_minimum_is_enough(self, road_graph_session):
        """ちょうどの区間まで落とすと、境界の区間が静かに消える。"""
        row = await self._percentages(road_graph_session, {LULC_TREES: MIN_VALID_PIXELS})

        assert row is not None
        assert row.trees_percent == 100.0
