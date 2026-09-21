"""クラスごとの画素数から割合を出す規則（`domain/landcover.py: class_percentages_sql`）。

**判定はDB側で行うため、DBへ通して確かめる。**

クラス値と画素数を直に与える——この規則が負うのは「数えた結果をどう割合にするか」で、
どの画素を数えるかは`derive_raster_materials`の側の仕事である。
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.landcover import (
    LULC_BUILT,
    LULC_CLOUDS,
    LULC_TREES,
    LULC_WATER,
    MIN_VALID_PIXELS,
    PERCENT_CLASSES,
    class_percentages_sql,
)

# road_graph_session（conftest.py）と同じDBを使うため、docs/conventions/testing.mdのパターン2どおり
# loop_scope="module"・xdist_group="postgis"が必須。
pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]


async def percentages(session: AsyncSession, counts: dict[int, int]):
    """1区間ぶんのヒストグラムを渡して、割合の行を受け取る（該当なしはNone）。"""
    rows = ", ".join(f"(1, 0, {cls}, {n})" for cls, n in counts.items()) or "(1, 0, NULL, 0)"
    sql = class_percentages_sql(
        f"SELECT * FROM (VALUES {rows}) AS v(osm_way_id, segment_index, cls, n)")
    return (await session.execute(text(sql))).first()


async def test_雲だけなら値を持たない(road_graph_session):
    assert await percentages(road_graph_session, {LULC_CLOUDS: 100}) is None


async def test_有効画素が下限に満たなければ値を持たない(road_graph_session):
    row = await percentages(road_graph_session, {LULC_TREES: MIN_VALID_PIXELS - 1})
    assert row is None


async def test_市街地だけなら市街地が百パーセント(road_graph_session):
    row = await percentages(road_graph_session, {LULC_BUILT: 100})
    assert row is not None
    assert row.valid_pixels == 100
    assert row.built_percent == 100.0
    assert row.trees_percent == 0.0
    assert row.water_percent == 0.0


async def test_雲と欠測は分母から外す(road_graph_session):
    row = await percentages(
        road_graph_session, {LULC_TREES: 50, LULC_WATER: 50, LULC_CLOUDS: 100, 0: 100})
    assert row is not None
    # 有効画素はTrees+Waterの100のみ。
    assert row.valid_pixels == 100
    assert row.trees_percent == 50.0
    assert row.water_percent == 50.0


async def test_混ざっていても合計は百パーセント(road_graph_session):
    row = await percentages(
        road_graph_session, {LULC_TREES: 30, LULC_BUILT: 20, LULC_WATER: 50})
    assert row is not None
    total = sum(getattr(row, name) for name, _ in PERCENT_CLASSES)
    assert total == 100.0
