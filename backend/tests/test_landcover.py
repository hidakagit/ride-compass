"""`domain/landcover.py`——土地被覆クラスの宣言と、画素数を割合へ畳むSQL・ラスタ構成の指紋。

ここで見ないもの:
- タイルの塗り（ラスタの読み取り・再投影） → `test_landcover_raster.py`
- タイルの配信とキャッシュの鍵 → `test_landcover_tile.py`
- 割合を区間・道へ書き込むこと → `batch/derive_raster_materials.py`の責務（ここでは見ない）

割合のSQLはDB側で動くため、DBへ通して確かめる（`postgis`）。期待値の画素数は
`MIN_VALID_PIXELS`とクラス値の宣言から作り、数字を書き写さない。
"""

import pytest
from sqlalchemy import text

from app.domain import landcover

# ---- クラスの宣言（本番のデータそのものに対する不変条件） ----


def test_every_class_has_its_own_pixel_value_and_percent_column():
    values = [c.value for c in landcover.LANDCOVER_CLASSES]
    fields = [c.percent_field for c in landcover.LANDCOVER_CLASSES]

    assert values, "土地被覆クラスが1つも宣言されていない"
    assert len(set(values)) == len(values)
    assert len(set(fields)) == len(fields)


def test_every_class_can_be_told_apart_in_the_legend_and_the_inspector():
    # 凡例と区間インスペクタは表示名と色でクラスを見分ける
    labels = [c.label for c in landcover.LANDCOVER_CLASSES]
    colors = [c.color.lower() for c in landcover.LANDCOVER_CLASSES]

    assert len(set(labels)) == len(labels)
    assert len(set(colors)) == len(colors)


def test_no_class_is_one_of_the_pixel_values_left_out_of_the_denominator():
    assert not {c.value for c in landcover.LANDCOVER_CLASSES} & landcover.LULC_INVALID_VALUES


def test_every_percent_column_is_named_so_that_its_count_column_can_be_derived():
    # 割合のSQLは`_percent`を外した名前で画素数の列を作る。外れない名前だと両方が同じ列名になる
    assert all(c.percent_field.endswith("_percent") for c in landcover.LANDCOVER_CLASSES)


def test_sql_column_order_follows_the_pixel_value_not_the_display_order():
    # 表示順を変えても焼き込み済みの列順が動かない
    values = [value for _, value in landcover.PERCENT_CLASSES]

    assert values == sorted(values)


# ---- ラスタ構成の指紋 ----


def test_fingerprint_does_not_depend_on_the_order_or_the_directory():
    assert landcover.raster_set_fingerprint(["/a/zone53.tif", "/a/zone54.tif"]) == landcover.raster_set_fingerprint(
        ["/b/zone54.tif", "/c/zone53.tif"]
    )


def test_fingerprint_changes_when_a_raster_is_added():
    assert landcover.raster_set_fingerprint(["/a/zone53.tif"]) != landcover.raster_set_fingerprint(
        ["/a/zone53.tif", "/a/zone54.tif"]
    )


# ---- 画素数から割合へ（DB） ----


def _counts(rows: list[tuple[int, int, int, int]]) -> str:
    values = ", ".join(f"({way}::bigint, {seg}, {cls}, {n}::bigint)" for way, seg, cls, n in rows)
    return f"SELECT * FROM (VALUES {values}) AS c(osm_way_id, segment_index, cls, n)"


async def _percentages(session, rows: list[tuple[int, int, int, int]]) -> dict[tuple[int, int], dict]:
    result = await session.execute(text(landcover.class_percentages_sql(_counts(rows))))
    return {(r.osm_way_id, r.segment_index): dict(r._mapping) for r in result.all()}


def _field(value: int) -> str:
    return next(c.percent_field for c in landcover.LANDCOVER_CLASSES if c.value == value)


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.xdist_group(name="postgis")
@pytest.mark.postgis
class TestClassPercentages:
    async def test_each_class_gets_its_share_of_the_valid_pixels(self, road_graph_session):
        n = landcover.MIN_VALID_PIXELS
        rows = await _percentages(
            road_graph_session, [(1, 0, landcover.LULC_TREES, 3 * n), (1, 0, landcover.LULC_BUILT, n)]
        )

        row = rows[(1, 0)]
        assert row["valid_pixels"] == 4 * n
        assert float(row[_field(landcover.LULC_TREES)]) == pytest.approx(75.0)
        assert float(row[_field(landcover.LULC_BUILT)]) == pytest.approx(25.0)

    @pytest.mark.parametrize("cls", landcover.LANDCOVER_CLASSES, ids=lambda c: c.percent_field)
    async def test_every_class_lands_in_its_own_column(self, road_graph_session, cls):
        rows = await _percentages(road_graph_session, [(1, 0, cls.value, landcover.MIN_VALID_PIXELS)])

        assert float(rows[(1, 0)][cls.percent_field]) == pytest.approx(100.0)

    async def test_a_segment_with_only_no_data_and_cloud_pixels_has_no_row(self, road_graph_session):
        invalid = [(1, 0, value, 10 * landcover.MIN_VALID_PIXELS) for value in sorted(landcover.LULC_INVALID_VALUES)]

        assert await _percentages(road_graph_session, invalid) == {}

    async def test_a_class_with_no_pixels_is_zero_not_missing(self, road_graph_session):
        rows = await _percentages(road_graph_session, [(1, 0, landcover.LULC_TREES, landcover.MIN_VALID_PIXELS)])

        absent = [c.percent_field for c in landcover.LANDCOVER_CLASSES if c.value != landcover.LULC_TREES]
        assert absent, "樹木以外のクラスが無い"
        assert all(rows[(1, 0)][field] == 0 for field in absent)

    async def test_no_data_and_cloud_pixels_leave_the_denominator(self, road_graph_session):
        n = landcover.MIN_VALID_PIXELS
        invalid = [(1, 0, value, 5 * n) for value in sorted(landcover.LULC_INVALID_VALUES)]

        rows = await _percentages(road_graph_session, [(1, 0, landcover.LULC_WATER, n), *invalid])

        assert rows[(1, 0)]["valid_pixels"] == n
        assert float(rows[(1, 0)][_field(landcover.LULC_WATER)]) == pytest.approx(100.0)

    async def test_a_segment_with_too_few_valid_pixels_has_no_row(self, road_graph_session):
        n = landcover.MIN_VALID_PIXELS
        rows = await _percentages(
            road_graph_session,
            [
                (1, 0, landcover.LULC_TREES, n),  # ちょうど下限は返る
                (2, 0, landcover.LULC_TREES, n - 1),
                # 無効画素が多くても、有効画素が足りなければ返らない
                (3, 0, landcover.LULC_TREES, n - 1),
                (3, 0, max(landcover.LULC_INVALID_VALUES), 10 * n),
            ],
        )

        assert set(rows) == {(1, 0)}

    async def test_segments_of_the_same_way_are_counted_separately(self, road_graph_session):
        n = landcover.MIN_VALID_PIXELS
        rows = await _percentages(
            road_graph_session, [(1, 0, landcover.LULC_TREES, n), (1, 1, landcover.LULC_CROPS, n)]
        )

        assert float(rows[(1, 0)][_field(landcover.LULC_TREES)]) == pytest.approx(100.0)
        assert float(rows[(1, 1)][_field(landcover.LULC_CROPS)]) == pytest.approx(100.0)

    async def test_a_row_reads_straight_into_the_percentages_model(self, road_graph_session):
        # 集計SQLが吐く列と、それを受けるモデルの項目は同じ宣言から作る——食い違えば受け取れない
        rows = await _percentages(road_graph_session, [(1, 0, landcover.LULC_TREES, landcover.MIN_VALID_PIXELS)])

        row = {k: v for k, v in rows[(1, 0)].items() if k not in ("osm_way_id", "segment_index")}
        model = landcover.LandcoverPercentages(**row)
        assert model.valid_pixels == landcover.MIN_VALID_PIXELS
