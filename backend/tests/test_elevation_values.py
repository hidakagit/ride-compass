"""`domain/attributes.py: elevation_values_sql`——区間の頂点列の標高から、区間の標高と勾配を出すSQL。

PostGISで実行して、返った行を見る。頂点は赤道の上に経度0.001度おきに置く——赤道に沿った測地線の長さは
楕円体の長半径（6378137m）×経度差（ラジアン）で、1歩が約111.32mになる。

ここで見ないもの:
- 区間ごとの頂点列と標高を作り、結果を派生の表へ書くこと → `test_derive_elevation.py`
- `ElevationAttribute.reversed_as`そのものの入れ替え → `test_attributes.py`
"""

import math
import random
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.domain.attributes import MAX_PLAUSIBLE_AVERAGE_GRADE_PERCENT, ElevationAttribute, elevation_values_sql

pytestmark = pytest.mark.asyncio(loop_scope="module")

STEP_DEG = 0.001
STEP_M = 6378137.0 * math.radians(STEP_DEG)


def rise(percent: float, steps: int = 1) -> float:
    """`steps`歩ぶんの水平距離で、勾配`percent`になる高さ。"""
    return STEP_M * steps * percent / 100


async def values(session, segments: dict[tuple[int, int], list], on_structure=frozenset()) -> dict:
    """`{(道, 区間番号): [頂点ごとの標高（Noneは欠損）]}`をSQLへ通し、`{(道, 区間番号): 行}`で返す。"""
    rows = []
    for (way, segment), elevations in segments.items():
        structure = "true" if (way, segment) in on_structure else "false"
        for ord_, elev in enumerate(elevations):
            elev_sql = "NULL" if elev is None else repr(float(elev))
            rows.append(
                f"({way}, {segment}, {ord_}, {ord_ * STEP_DEG}::float8, 0.0::float8, {elev_sql}::float8, {structure})"
            )
    relation = (
        f"SELECT * FROM (VALUES {', '.join(rows)}) AS v(osm_way_id, segment_index, ord, lon, lat, elev, on_structure)"
    )
    result = await session.execute(text(elevation_values_sql(relation)))
    return {
        (row.osm_way_id, row.segment_index): {
            key: (float(value) if isinstance(value, Decimal) else value)
            for key, value in row._mapping.items()
            if key not in ("osm_way_id", "segment_index")
        }
        for row in result
    }


async def one(session, elevations, on_structure=False) -> dict:
    rows = await values(session, {(1, 0): elevations}, on_structure={(1, 0)} if on_structure else frozenset())
    return rows[(1, 0)]


async def test_a_road_that_climbs_and_descends_counts_both(road_graph_session):
    row = await one(road_graph_session, [100.0, 100.0 + rise(6), 100.0 + rise(6) - rise(2)])

    assert row["start_elevation_m"] == 100.0
    assert row["end_elevation_m"] == pytest.approx(100.0 + rise(4), abs=0.05)
    assert row["elevation_gain_m"] == pytest.approx(rise(6), abs=0.05)
    assert row["elevation_loss_m"] == pytest.approx(rise(2), abs=0.05)
    assert row["average_grade"] == pytest.approx(2.0, abs=0.005)


async def test_values_are_rounded_to_a_tenth_of_a_metre_and_a_hundredth_of_a_percent(road_graph_session):
    row = await one(road_graph_session, [100.04, 100.04 + rise(3.333)])

    assert row["start_elevation_m"] == 100.0
    assert row["average_grade"] == 3.33


async def test_a_vertex_without_elevation_is_left_out(road_graph_session):
    """欠損を挟んだ2点の差は獲得・喪失に入れない。両端の値と平均勾配は欠損の外から出る。"""
    row = await one(road_graph_session, [100.0, None, 100.0 + rise(5, 2), 100.0 + rise(5, 2) + rise(1)])

    assert row["start_elevation_m"] == 100.0
    assert row["elevation_gain_m"] == pytest.approx(rise(1), abs=0.05)
    assert row["elevation_loss_m"] == 0.0
    assert row["average_grade"] == pytest.approx((rise(5, 2) + rise(1)) / (3 * STEP_M) * 100, abs=0.005)


async def test_missing_first_and_last_vertices_move_the_ends_inward(road_graph_session):
    row = await one(road_graph_session, [None, 50.0, 50.0 + rise(2), None])

    assert (row["start_elevation_m"], row["end_elevation_m"]) == (50.0, pytest.approx(50.0 + rise(2), abs=0.05))
    assert row["average_grade"] == pytest.approx(2.0, abs=0.005)


async def test_a_segment_with_fewer_than_two_known_vertices_has_no_row(road_graph_session):
    rows = await values(
        road_graph_session,
        {(1, 0): [100.0, None, None], (3, 0): [100.0, 101.0]},
    )

    assert set(rows) == {(3, 0)}


async def test_gaps_only_between_known_vertices_give_no_climb_but_still_an_average(road_graph_session):
    row = await one(road_graph_session, [100.0, None, 100.0 + rise(3, 2)])

    assert (row["elevation_gain_m"], row["elevation_loss_m"]) == (0.0, 0.0)
    assert row["average_grade"] == pytest.approx(3.0, abs=0.005)


async def test_a_structure_uses_only_its_two_ends(road_graph_session):
    """橋の途中の頂点は下の谷を指すので、谷の起伏を獲得・喪失に入れない。"""
    row = await one(road_graph_session, [100.0, 60.0, 70.0, 100.0 + rise(1, 3)], on_structure=True)

    assert row["elevation_gain_m"] == pytest.approx(rise(1, 3), abs=0.05)
    assert row["elevation_loss_m"] == 0.0
    assert row["average_grade"] == pytest.approx(1.0, abs=0.005)


async def test_a_descending_structure_counts_only_the_loss(road_graph_session):
    row = await one(road_graph_session, [100.0, 140.0, 100.0 - rise(2, 2)], on_structure=True)

    assert row["elevation_gain_m"] == 0.0
    assert row["elevation_loss_m"] == pytest.approx(rise(2, 2), abs=0.05)


@pytest.mark.parametrize(
    ("percent", "kept"),
    [
        (MAX_PLAUSIBLE_AVERAGE_GRADE_PERCENT - 0.5, True),
        (MAX_PLAUSIBLE_AVERAGE_GRADE_PERCENT + 0.5, False),
    ],
)
async def test_an_implausible_average_grade_has_no_value(road_graph_session, percent, kept):
    """平均勾配が公道としてありえない区間は、平均勾配を持たない。獲得・喪失と両端の標高はそのまま出る。"""
    row = await one(road_graph_session, [0.0, rise(percent)])

    assert (row["average_grade"] is not None) is kept
    assert row["elevation_gain_m"] + row["elevation_loss_m"] == pytest.approx(abs(rise(percent)), abs=0.05)


async def test_vertices_at_the_same_place_give_no_grade(road_graph_session):
    relation = (
        "SELECT * FROM (VALUES (1, 0, 0, 139.0::float8, 35.0::float8, 10.0::float8, false),"
        " (1, 0, 1, 139.0::float8, 35.0::float8, 12.0::float8, false))"
        " AS v(osm_way_id, segment_index, ord, lon, lat, elev, on_structure)"
    )
    [row] = (await road_graph_session.execute(text(elevation_values_sql(relation)))).mappings().all()

    assert float(row["elevation_gain_m"]) == 2.0
    assert row["average_grade"] is None


async def test_segments_are_computed_separately(road_graph_session):
    rows = await values(road_graph_session, {(1, 0): [0.0, rise(3)], (1, 1): [0.0, -rise(3)], (2, 0): [5.0, 5.0]})

    assert rows[(1, 0)]["average_grade"] == pytest.approx(3.0, abs=0.005)
    assert rows[(1, 1)]["average_grade"] == pytest.approx(-3.0, abs=0.005)
    assert rows[(2, 0)]["average_grade"] == 0.0


def attribute(row: dict, edge_id: str) -> ElevationAttribute:
    """SQLの行のうち、属性が持つ欄（始点・終点の標高は派生の表にだけ残る）。"""
    return ElevationAttribute(edge_id=edge_id, **{name: row[name] for name in ElevationAttribute.model_fields.keys() - {"edge_id"}})


async def test_running_the_vertices_backwards_gives_the_reverse_of_the_attribute(road_graph_session):
    """`reversed_as`が導く逆方向の値は、同じ頂点列を逆順に辿ってSQLで出した値に一致する。
    起伏・欠損・構造物を含む区間を乱数で作って確かめる（種は固定）。"""
    generator = random.Random(192)
    segments: dict[tuple[int, int], list] = {}
    structures = set()
    for way in range(1, 121):
        elevation = generator.uniform(0, 500)
        profile = []
        for _ in range(generator.randint(2, 8)):
            elevation += generator.uniform(-1, 1) * rise(12)
            profile.append(None if generator.random() < 0.15 else round(elevation, 3))
        segments[(way, 0)] = profile
        if generator.random() < 0.2:
            structures.add((way, 0))

    forward = await values(road_graph_session, segments, on_structure=structures)
    backward = await values(
        road_graph_session, {key: profile[::-1] for key, profile in segments.items()}, on_structure=structures
    )

    assert forward.keys() == backward.keys()
    assert len(forward) > 80  # 有効な頂点が2点未満で落ちる区間を除いても、多くの区間を比べている
    for key in forward:
        expected = attribute(forward[key], "f").reversed_as("r").model_dump()
        actual = attribute(backward[key], "r").model_dump()
        for name, value in expected.items():
            if isinstance(value, float):
                tolerance = 0.011 if name.endswith("grade") else 0.11
                assert actual[name] == pytest.approx(value, abs=tolerance), (key, name)
            else:
                assert actual[name] == value, (key, name)
