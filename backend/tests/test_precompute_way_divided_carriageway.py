"""app/batch/precompute_way_divided_carriageway.pyのrun()結合検証。

一方通行レイヤーが「一方通行規制の道」だけを塗れるかは、この判定の切り分けで決まる。
3条件（carriagewayタグ／同じref-nameの相方／全長にわたって寄り添う相方）それぞれが
効くことと、**効いてはいけない形で効かないこと**——同じ道を分割した連続する区間、
街区を挟んで並ぶ別々の一方通行——を固定する。

ridecompass_test DB（conftest.pyのroad_graph_session/road_graph_repositoryフィクスチャ）への
実接続が必要。接続できない環境ではフィクスチャがpytest.skip()する。
"""

import json

import pytest
from sqlalchemy import text

from app.batch.precompute_way_divided_carriageway import run
from tests.conftest import postgis_database_url

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

# 緯度35.7度で経度0.0001度は約9m、0.0004度は約36m。上下線分離（中央値10m前後）と
# 街区を挟んだ並走（中央値19m）の両方を作り分けられる幅で置く。
_LON = 139.700
_GAP_SMALL = 0.00012   # 約11m: 中央分離帯
_GAP_LARGE = 0.00030   # 約27m: 街区を挟む

# 南北に伸びる線。北向き（south→north）と南向きを作り分ける。
_LAT_S, _LAT_N = 35.700, 35.710


def _line(lon: float, northbound: bool) -> str:
    a, b = (_LAT_S, _LAT_N) if northbound else (_LAT_N, _LAT_S)
    return f"LINESTRING({lon} {a}, {lon} {b})"


async def _insert(session, osm_way_id: int, wkt: str, *, highway: str, direction: str, tags: dict) -> None:
    await session.execute(
        text(
            "INSERT INTO osm_raw_ways (osm_way_id, highway, tags, node_ids, geom, direction, updated_at) "
            "VALUES (:id, :highway, CAST(:tags AS jsonb), ARRAY[]::bigint[], "
            "ST_GeomFromText(:wkt, 4326), :direction, now()) "
            "ON CONFLICT (osm_way_id) DO UPDATE SET geom = EXCLUDED.geom, tags = EXCLUDED.tags, "
            "direction = EXCLUDED.direction, highway = EXCLUDED.highway"
        ),
        {"id": osm_way_id, "highway": highway, "tags": json.dumps(tags), "wkt": wkt, "direction": direction},
    )


async def _divided(session) -> dict[int, bool]:
    rows = (await session.execute(text("SELECT osm_way_id, divided FROM way_divided_carriageway"))).all()
    return {r.osm_way_id: r.divided for r in rows}


async def test_each_condition_decides_what_it_should(road_graph_session):
    # 条件1: carriagewayタグ。相方がいなくても単独で確定する。
    await _insert(road_graph_session, 9001, _line(_LON, True),
                  highway="primary", direction="forward", tags={"carriageway": "dual"})

    # 条件2: 同じrefの対向一方通行が近くにある（名前で同一性が分かる）。
    await _insert(road_graph_session, 9011, _line(_LON + 0.01, True),
                  highway="primary", direction="forward", tags={"ref": "国道1号"})
    await _insert(road_graph_session, 9012, _line(_LON + 0.01 + _GAP_SMALL, False),
                  highway="primary", direction="forward", tags={"ref": "国道1号"})

    # 条件3: 無名だが全長にわたって対向の相方が寄り添う。
    await _insert(road_graph_session, 9021, _line(_LON + 0.02, True),
                  highway="tertiary", direction="forward", tags={})
    await _insert(road_graph_session, 9022, _line(_LON + 0.02 + _GAP_SMALL, False),
                  highway="tertiary", direction="forward", tags={})

    # 効いてはいけない形1: 街区を挟んで並ぶ、別々の一方通行の生活道路。
    await _insert(road_graph_session, 9031, _line(_LON + 0.03, True),
                  highway="residential", direction="forward", tags={})
    await _insert(road_graph_session, 9032, _line(_LON + 0.03 + _GAP_LARGE, False),
                  highway="residential", direction="forward", tags={})

    # 効いてはいけない形2: 同じ一方通行を分割した連続する区間（端点を共有し距離0だが同じ向き）。
    await _insert(road_graph_session, 9041,
                  f"LINESTRING({_LON + 0.04} 35.700, {_LON + 0.04} 35.705)",
                  highway="residential", direction="forward", tags={"name": "みなみ通り"})
    await _insert(road_graph_session, 9042,
                  f"LINESTRING({_LON + 0.04} 35.705, {_LON + 0.04} 35.710)",
                  highway="residential", direction="forward", tags={"name": "みなみ通り"})

    # 双方向の道は、隣に何があっても対象外。
    await _insert(road_graph_session, 9051, _line(_LON + 0.05, True),
                  highway="primary", direction="both", tags={"ref": "県道2号"})
    await _insert(road_graph_session, 9052, _line(_LON + 0.05 + _GAP_SMALL, False),
                  highway="primary", direction="forward", tags={"ref": "県道2号"})
    await road_graph_session.commit()

    assert await run(postgis_database_url(), dry_run=False) == 0

    await road_graph_session.rollback()  # バッチ側の別エンジンによる書き込みを読み直す
    divided = await _divided(road_graph_session)

    assert divided[9001] is True, "carriagewayタグだけで確定できていない"
    assert divided[9011] is True and divided[9012] is True, "同じrefの対向が見つかっていない"
    assert divided[9021] is True and divided[9022] is True, "無名の上下線分離を拾えていない"
    assert divided[9031] is False and divided[9032] is False, "街区を挟んだ並走を対にしている"
    assert divided[9041] is False and divided[9042] is False, "連続する区間を相方と見なしている"
    assert divided[9051] is False, "双方向の道を上下線分離にしている"


# 東西に伸びる道と、それに対して測地線方位で48度ずれた相方。許容角は45度なので、
# 測地線方位で測れば「対向ではない」が正しい。経度緯度を平面として扱うと方位の差が
# 緯度の余弦ぶん縮んで42度に見え、許容角の内側へ入ってしまう。
_EAST_WEST_WKT = "LINESTRING(139.700 35.700, 139.701 35.700)"
_OFF_BY_48_DEG_WKT = "LINESTRING(139.7005000 35.6998200, 139.7002039 35.7000870)"


async def test_travel_bearing_is_geodesic_not_planar(road_graph_session):
    """方位は測地線で測る。平面近似だと東西方向の道で許容角の内側へ誤って入る。

    相方は同じrefを持ち40m以内に居るので、方位の判定だけが結果を分ける
    （highwayを変えてあるため条件3では対にならない）。
    """
    await _insert(road_graph_session, 9061, _EAST_WEST_WKT,
                  highway="primary", direction="forward", tags={"ref": "国道9号"})
    await _insert(road_graph_session, 9062, _OFF_BY_48_DEG_WKT,
                  highway="secondary", direction="forward", tags={"ref": "国道9号"})
    await road_graph_session.commit()

    assert await run(postgis_database_url(), dry_run=False) == 0

    await road_graph_session.rollback()
    divided = await _divided(road_graph_session)

    assert divided[9061] is False, "48度ずれた相方を対向と見なしている（平面近似のまま）"
    assert divided[9062] is False
