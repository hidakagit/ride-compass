"""app/batch/precompute_way_curvature.pyのrun()結合検証。

way単位の蛇行（way_geometry）は、地図タイル・区間インスペクタ・軸スタジオの分布
プレビューが読む唯一の値。Edge単位版（road_edges）と測り方のSQLを共有するため、
**同じ折れ線に対して`domain/geo.py: curvature_deg_per_km`と一致すること**を固定する。

ridecompass_test DB（conftest.pyのroad_graph_session/road_graph_repositoryフィクスチャ）への
実接続が必要。接続できない環境ではフィクスチャがpytest.skip()する。
"""

import pytest
from sqlalchemy import text

from app.batch.precompute_way_curvature import run
from app.domain.geo import LatLonPoint, curvature_deg_per_km, haversine_distance_km
from app.domain.graph import WaySpec, build_road_graph
from tests.conftest import TEST_DATABASE_URL

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

# 直線（頂点3点・方位変化なし）、ジグザグ（頂点ごとに折り返す）、頂点2点（直線＝0）。
NODES = {
    1: (35.700, 139.700), 2: (35.710, 139.700), 3: (35.720, 139.700),
    11: (35.700, 139.800), 12: (35.701, 139.801), 13: (35.702, 139.800),
    14: (35.703, 139.801), 15: (35.704, 139.800),
    21: (35.700, 139.900), 22: (35.710, 139.900),
}
WAYS = [
    WaySpec(osm_way_id=300, node_ids=[1, 2, 3], highway="residential"),
    WaySpec(osm_way_id=301, node_ids=[11, 12, 13, 14, 15], highway="residential"),
    WaySpec(osm_way_id=302, node_ids=[21, 22], highway="residential"),
]

# 球（domain/geo.py）と回転楕円体（PostGISのgeography）の違いぶんの許容差。
TOLERANCE_RATIO = 0.01


async def _seed(road_graph_repository, road_graph_session) -> None:
    graph = build_road_graph(WAYS, NODES, graph_version="v1")
    await road_graph_repository.save_graph(graph)
    # osm_raw_waysが母集団。バッチはroad_edgesを一切見ない。
    for way in WAYS:
        points = ", ".join(f"{NODES[n][1]} {NODES[n][0]}" for n in way.node_ids)
        await road_graph_session.execute(
            text(
                "INSERT INTO osm_raw_ways "
                "(osm_way_id, highway, tags, node_ids, geom, direction, updated_at) "
                "VALUES (:id, 'residential', '{}'::jsonb, :nodes, "
                f"ST_GeomFromText('LINESTRING({points})', 4326), 'both', now()) "
                "ON CONFLICT (osm_way_id) DO NOTHING"
            ),
            {"id": way.osm_way_id, "nodes": way.node_ids},
        )
    await road_graph_session.commit()


async def _stored(road_graph_session) -> dict[int, float | None]:
    rows = (
        await road_graph_session.execute(text("SELECT osm_way_id, curvature_deg_per_km FROM way_geometry"))
    ).all()
    return {r.osm_way_id: r.curvature_deg_per_km for r in rows}


def _python_value(way: WaySpec) -> float | None:
    coordinates = [NODES[n] for n in way.node_ids]
    length_m = 1000 * sum(
        haversine_distance_km(LatLonPoint(*a), LatLonPoint(*b))
        for a, b in zip(coordinates, coordinates[1:])
    )
    return curvature_deg_per_km(coordinates, length_m)


async def test_run_matches_the_python_definition(road_graph_repository, road_graph_session):
    await _seed(road_graph_repository, road_graph_session)

    assert await run(TEST_DATABASE_URL, dry_run=False) == 0

    await road_graph_session.rollback()  # バッチ側の別エンジンによる書き込みを読み直す
    stored = await _stored(road_graph_session)

    for way in WAYS:
        sql_value = stored.get(way.osm_way_id)
        python_value = _python_value(way)
        assert sql_value is not None, f"バッチが値を入れていない: {way.osm_way_id}"
        assert python_value is not None
        assert abs(sql_value - python_value) <= max(TOLERANCE_RATIO * python_value, 0.5), (
            f"way {way.osm_way_id}: SQL={sql_value} とPython={python_value} が食い違う"
        )


async def test_two_point_way_is_zero_not_missing(road_graph_repository, road_graph_session):
    """頂点2点のwayは直線＝0。Noneにすると材料が欠損し、蛇行軸が算出不能な道が増える。"""
    await _seed(road_graph_repository, road_graph_session)

    assert await run(TEST_DATABASE_URL, dry_run=False) == 0

    await road_graph_session.rollback()
    stored = await _stored(road_graph_session)
    assert stored[302] == pytest.approx(0.0, abs=0.5)
    assert stored[300] == pytest.approx(0.0, abs=0.5)
    assert stored[301] > 100


async def test_way_without_geometry_gets_a_row_with_null(road_graph_repository, road_graph_session):
    """geomがNULLのwayも行を作り、値だけNULLにする。

    `WayGeometryRow`は「行が無い＝未計算、列がNULL＝算出不能」の2状態を宣言している。
    測れないwayを対象から外すと、算出不能なwayが未計算と見分けられなくなり、再実行しても
    埋まらないwayを追い続けることになる。
    """
    await _seed(road_graph_repository, road_graph_session)
    await road_graph_session.execute(
        text(
            "INSERT INTO osm_raw_ways "
            "(osm_way_id, highway, tags, node_ids, geom, direction, updated_at) "
            "VALUES (303, 'residential', '{}'::jsonb, ARRAY[1, 2], NULL, 'both', now()) "
            "ON CONFLICT (osm_way_id) DO NOTHING"
        )
    )
    await road_graph_session.commit()

    assert await run(TEST_DATABASE_URL, dry_run=False) == 0

    await road_graph_session.rollback()
    stored = await _stored(road_graph_session)
    assert 303 in stored, "geomがNULLのwayの行が作られていない（未計算と区別できない）"
    assert stored[303] is None


async def test_run_dry_run_writes_nothing(road_graph_repository, road_graph_session):
    await _seed(road_graph_repository, road_graph_session)

    assert await run(TEST_DATABASE_URL, dry_run=True) == 0

    await road_graph_session.rollback()
    assert await _stored(road_graph_session) == {}
