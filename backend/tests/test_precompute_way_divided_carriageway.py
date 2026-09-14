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
from tests.conftest import TEST_DATABASE_URL

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

    assert await run(TEST_DATABASE_URL, dry_run=False) == 0

    await road_graph_session.rollback()  # バッチ側の別エンジンによる書き込みを読み直す
    divided = await _divided(road_graph_session)

    assert divided[9001] is True, "carriagewayタグだけで確定できていない"
    assert divided[9011] is True and divided[9012] is True, "同じrefの対向が見つかっていない"
    assert divided[9021] is True and divided[9022] is True, "無名の上下線分離を拾えていない"
    assert divided[9031] is False and divided[9032] is False, "街区を挟んだ並走を対にしている"
    assert divided[9041] is False and divided[9042] is False, "連続する区間を相方と見なしている"
    assert divided[9051] is False, "双方向の道を上下線分離にしている"
