"""標高と勾配の値の規則（`domain/attributes.py: elevation_values_sql`）。

配信元（https://maps.gsi.go.jp/development/hyokochi.html ）:
「元となる標高モデルデータ標高点の値は、地表面の測定値に基づいているため、構造物
（建物、高架橋等）の高さを反映したものではありません。」

**判定はDB側で行うため、DBへ通して確かめる。**頂点と標高を直に与える——この規則が
負うのは「取れた標高をどう値にするか」で、どの画素を読むかは`derive_raster_materials`の
側の仕事である。
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.attributes import MAX_PLAUSIBLE_AVERAGE_GRADE_PERCENT, elevation_values_sql

# road_graph_session（conftest.py）と同じDBを使うため、docs/conventions/testing.mdのパターン2どおり
# loop_scope="module"・xdist_group="postgis"が必須。
pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

#: 同じ経度で約111mずつ北へ並ぶ3点。
A = (35.700, 139.700)
B = (35.701, 139.700)
C = (35.702, 139.700)


async def values(session: AsyncSession, points, elevations, *, on_structure: bool = False):
    rows = ", ".join(
        "(1, 0, {}, {}, {}, {}, {})".format(
            i + 1, lon, lat, "NULL" if e is None else e, str(on_structure).lower())
        for i, ((lat, lon), e) in enumerate(zip(points, elevations)))
    sql = elevation_values_sql(
        f"SELECT * FROM (VALUES {rows})"
        " AS v(osm_way_id, segment_index, ord, lon, lat, elev, on_structure)")
    return (await session.execute(text(sql))).first()


async def test_構造物では中間の頂点を捨てて両端だけで組む(road_graph_session):
    """谷を渡る平らな橋。中間の点が指しているのは桁ではなく谷底。"""
    v = await values(road_graph_session, [A, B, C], [50.0, 10.0, 50.0], on_structure=True)

    assert v.elevation_gain_m == 0.0
    assert v.elevation_loss_m == 0.0
    assert v.average_grade == 0.0
    assert v.max_grade == 0.0
    assert v.min_grade == 0.0
    # 橋台・坑口は道が地面と接する位置なので、両端の標高は残す。
    assert v.start_elevation_m == 50.0
    assert v.end_elevation_m == 50.0


async def test_構造物でも両端の高低差は残る(road_graph_session):
    v = await values(road_graph_session, [A, B, C], [50.0, 10.0, 62.0], on_structure=True)

    assert v.elevation_gain_m == 12.0
    assert v.elevation_loss_m == 0.0


async def test_構造物でない道は中間の起伏を積む(road_graph_session):
    v = await values(road_graph_session, [A, B, C], [50.0, 10.0, 50.0])

    assert v.elevation_gain_m == 40.0
    assert v.elevation_loss_m == 40.0


async def test_ありえない平均勾配は値を持たせない(road_graph_session):
    """0.02度≒2.2mで20m上がると9000%になる。公道としてありえない＝DEMの読み違い。"""
    near = (35.70002, 139.700)
    v = await values(road_graph_session, [A, near], [10.0, 30.0])

    assert v.average_grade is None
    assert MAX_PLAUSIBLE_AVERAGE_GRADE_PERCENT == 40.0


async def test_標高が取れない点は評価から外す(road_graph_session):
    v = await values(road_graph_session, [A, B, C], [10.0, None, 14.0])

    # 欠損を挟む対はgain/lossへ寄与させない（欠損区間の起伏が均されてしまうため）。
    assert v.elevation_gain_m == 0.0
    assert v.start_elevation_m == 10.0
    assert v.end_elevation_m == 14.0


async def test_有効な標高が2点未満なら行を返さない(road_graph_session):
    assert await values(road_graph_session, [A, B], [None, 12.0]) is None


async def test_欠損を挟む対は勾配へ寄与させない(road_graph_session):
    """欠損を飛ばして隣接扱いすると、その区間の起伏が均された勾配として混入する。"""
    v = await values(road_graph_session, [A, B, C], [10.0, None, 40.0])

    assert v.max_grade is None
    assert v.min_grade is None
    # 距離は両端の座標から正確に出せるので、平均勾配は持てる。
    assert v.average_grade is not None
