"""立ち寄り先（`stop_places`）を、地点の生データから作り直す。

**群はここで付ける**。取込は外部が持っていた列をそのまま入れるだけで、「どの群か」は派生の側の判断である。
語の表は`domain/stop_place.py`が持ち、このバッチはそれをSQLへ渡すだけで、行を取り出さない。

同じ群・同じチェーン（`domain/stop_place.py: chain_sql`）で`MERGE_RADIUS_M`以内に並ぶ地点は、確からしさの最も
高い1つにまとめる（同じなら識別子の小さいほう）。まとまりは近い点を連ねて作るので、端と端がその距離より離れることが
ある。チェーンの分からない地点は別々の店としてまとめない。群「コンビニ」は、コンビニのチェーン（`CHAIN_WORDS`）に
当たる地点だけを入れる（`kept_sql`）。店の中の ATM の地点は、名前を店の名前へ直してから群とチェーンを決める
（`store_name_sql`）——店の隣にあれば店とまとまり、無ければ店として残る。

道の網とは何も読み合わないので、どの段の後ろに置いてもよい。
"""

import logging
import time

import asyncpg

from app.domain.stop_place import (
    MERGE_RADIUS_M,
    chain_sql,
    chain_text_sql,
    kept_sql,
    normalized_sql,
    overture_group_sql,
    store_name_sql,
)
from app.infrastructure.source_models import OVERTURE_PLACES_SOURCE_SQL, Source

logger = logging.getLogger("ridecompass.derive_stop_places")

#: 地面の m で測る平面の座標。Web Mercator の座標をその点の緯度の cos 倍すると、近くの2点の間は地面の m に
#: なる（Mercator はその緯度で 1/cos 倍に伸びる。まとめる距離の中で緯度はほぼ変わらない）。
_GROUND_M_GEOM = "ST_Scale(ST_Transform(o.geom, 3857), cos(radians(ST_Y(o.geom))), cos(radians(ST_Y(o.geom))))"

_GROUPED = f"""
CREATE TEMP TABLE _grouped_places ON COMMIT DROP AS
SELECT c.overture_id, c.name, c.normalized_name, c.brand, c.confidence, c.geom, c.place_group, c.chain
FROM (
    SELECT g.*, {chain_sql(chain_text_sql("g.normalized_name"), chain_text_sql("g.normalized_brand"))} AS chain
    FROM (
        SELECT n.*, {normalized_sql("n.name")} AS normalized_name, {normalized_sql("n.brand")} AS normalized_brand
        FROM (
            SELECT o.overture_id, {store_name_sql("o.name")} AS name, o.brand, o.confidence, o.geom,
                   {overture_group_sql("o.hierarchy")} AS place_group
            FROM {OVERTURE_PLACES_SOURCE_SQL} o
        ) n
    ) g
    WHERE g.place_group IS NOT NULL
) c
WHERE {kept_sql("c.place_group", "c.chain")}
"""

_INSERT = f"""
INSERT INTO stop_places (source, source_key, name, search_name, place_group, confidence, brand, geom)
SELECT DISTINCT ON (place_group, chain, merge_key)
       '{Source.OVERTURE_PLACE}', overture_id, name, normalized_name, place_group, confidence, brand, geom
FROM (
    -- まとまりの番号は群・チェーンごとに0から振られるので、鍵は群・チェーンと組にして使う。
    SELECT o.*, 'c' || ST_ClusterDBSCAN({_GROUND_M_GEOM}, eps := $1, minpoints := 1)
                       OVER (PARTITION BY o.place_group, o.chain) AS merge_key
    FROM _grouped_places o WHERE o.chain IS NOT NULL
    UNION ALL
    SELECT o.*, 'p' || o.overture_id FROM _grouped_places o WHERE o.chain IS NULL
) keyed
ORDER BY place_group, chain, merge_key, confidence DESC, overture_id
"""


async def derive(conn: asyncpg.Connection) -> int:
    """立ち寄り先の表を入れ直し、入れた地点の数を返す。"""
    started = time.perf_counter()
    async with conn.transaction():
        await conn.execute("DELETE FROM stop_places")
        await conn.execute(_GROUPED)
        grouped = await conn.fetchval("SELECT count(*) FROM _grouped_places")
        inserted = int((await conn.execute(_INSERT, MERGE_RADIUS_M)).split()[-1])
    await conn.execute("ANALYZE stop_places")
    logger.info("立ち寄り先: 群に入った %d件 → まとめて %d件 / %.1f秒",
                grouped, inserted, time.perf_counter() - started)
    return inserted
