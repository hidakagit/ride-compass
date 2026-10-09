"""立ち寄り先（`stop_places`）を、地点の生データ（Overture の地点・国の文化財の建造物）から作り直す。

**群はここで付ける**。取込は外部が持っていた列をそのまま入れるだけで、「どの群か」は派生の側の判断である。
語の表は`domain/stop_place.py`が持ち、このバッチはそれをSQLへ渡すだけで、行を取り出さない。

同じ群・同じチェーン（`domain/stop_place.py: chain_sql`）で`MERGE_RADIUS_M`以内に並ぶ地点は、確からしさの最も
高い1つにまとめる（同じなら識別子の小さいほう）。まとまりは近い点を連ねて作るので、端と端がその距離より離れることが
ある。チェーンの分からない地点は別々の店としてまとめない。群「コンビニ」は、コンビニのチェーン（`CHAIN_WORDS`）に
当たる地点だけを入れる（`kept_sql`）。店の中の ATM の地点は、名前を店の名前へ直してから群とチェーンを決める
（`store_name_sql`）——店の隣にあれば店とまとまり、無ければ店として残る。

寺社は文化財の建造物の所有者から出す。所有者の欄の1人ずつのうち寺社の名前（`temple_shrine_owner_sql`）を持つ建物を、
同じ名前（表記の揺れを除いた形）で`HERITAGE_MERGE_RADIUS_M`以内に連なるものごとに1つの寺社にする。位置はまとまりの
重心に最も近い建物（重心は境内の外に落ちることがある）、名前は所有者の名前。1つの建物に寺社の所有者が2人いれば、
両方の寺社に入る。

辺り（`area`）は、入れた地点の位置を住所の辞書で逆引きして入れる（`infrastructure/address_dictionary.py: areas`）。
逆引きはSQLでできないので、ここだけ位置を取り出してスレッドで引き、一時の表から書き戻す。辞書を開けなければ止まる。

道の網とは何も読み合わないので、どの段の後ろに置いてもよい。
"""

import asyncio
import logging
import time

import asyncpg

from app.domain.geo import ground_m_sql
from app.domain.stop_place import (
    HERITAGE_MERGE_RADIUS_M,
    MERGE_RADIUS_M,
    StopPlaceGroup,
    chain_sql,
    chain_text_sql,
    kept_sql,
    normalized_sql,
    overture_group_sql,
    owner_lines_sql,
    owner_name_sql,
    store_name_sql,
    temple_shrine_owner_sql,
)
from app.infrastructure import address_dictionary
from app.infrastructure.source_models import BUNKA_HERITAGES_SOURCE_SQL, OVERTURE_PLACES_SOURCE_SQL, Source

logger = logging.getLogger("ridecompass.derive_stop_places")

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
    SELECT o.*, 'c' || ST_ClusterDBSCAN({ground_m_sql("o.geom")}, eps := $1, minpoints := 1)
                       OVER (PARTITION BY o.place_group, o.chain) AS merge_key
    FROM _grouped_places o WHERE o.chain IS NOT NULL
    UNION ALL
    SELECT o.*, 'p' || o.overture_id FROM _grouped_places o WHERE o.chain IS NULL
) keyed
ORDER BY place_group, chain, merge_key, confidence DESC, overture_id
"""

#: 寺社の所有者ごとの建物（1つの建物に寺社の所有者が2人いれば2行）。
_TEMPLE_BUILDINGS = f"""
CREATE TEMP TABLE _temple_buildings ON COMMIT DROP AS
SELECT h.heritage_id, h.geom, o.name, {normalized_sql("o.name")} AS normalized_name
FROM {BUNKA_HERITAGES_SOURCE_SQL} h
CROSS JOIN LATERAL (
    SELECT DISTINCT {owner_name_sql("line")} AS name FROM {owner_lines_sql("h.owners")} AS line
) o
WHERE {temple_shrine_owner_sql("o.name")}
"""

# 鍵は名前とまとまりの中の最も小さい文化財の ID の組（1つの建物が2つの寺社に入ると、ID だけでは重なる）。
_INSERT_TEMPLES = f"""
INSERT INTO stop_places (source, source_key, name, search_name, place_group, confidence, brand, geom)
SELECT DISTINCT ON (normalized_name, merge_key)
       '{Source.BUNKA_HERITAGE}', first_id || ' ' || normalized_name, name, normalized_name,
       '{StopPlaceGroup.TEMPLE_SHRINE}', 1, NULL, geom
FROM (
    SELECT c.*, min(c.heritage_id) OVER temple AS first_id, ST_Centroid(ST_Collect(c.geom) OVER temple) AS center
    FROM (
        SELECT b.*, ST_ClusterDBSCAN({ground_m_sql("b.geom")}, eps := $1, minpoints := 1)
                    OVER (PARTITION BY b.normalized_name) AS merge_key
        FROM _temple_buildings b
    ) c
    WINDOW temple AS (PARTITION BY c.normalized_name, c.merge_key)
) centered
ORDER BY normalized_name, merge_key, ST_Distance({ground_m_sql("geom")}, {ground_m_sql("center")}), heritage_id
"""


_POSITIONS = "SELECT source, source_key, ST_X(geom) AS longitude, ST_Y(geom) AS latitude FROM stop_places"

_AREAS = "CREATE TEMP TABLE _areas (source text, source_key text, area text) ON COMMIT DROP"

_SET_AREAS = """
UPDATE stop_places s SET area = a.area FROM _areas a WHERE s.source = a.source AND s.source_key = a.source_key
"""


async def _fill_areas(conn: asyncpg.Connection) -> int:
    """入れた地点の辺りを入れ、辺りの付いた地点の数を返す。"""
    places = await conn.fetch(_POSITIONS)
    names = await asyncio.to_thread(address_dictionary.areas, [(p["longitude"], p["latitude"]) for p in places])
    await conn.execute(_AREAS)
    await conn.copy_records_to_table("_areas", records=[
        (place["source"], place["source_key"], name) for place, name in zip(places, names, strict=True)])
    await conn.execute(_SET_AREAS)
    return sum(name is not None for name in names)


async def derive(conn: asyncpg.Connection) -> int:
    """立ち寄り先の表を入れ直し、入れた地点の数を返す。"""
    started = time.perf_counter()
    async with conn.transaction():
        await conn.execute("DELETE FROM stop_places")
        await conn.execute(_GROUPED)
        grouped = await conn.fetchval("SELECT count(*) FROM _grouped_places")
        inserted = int((await conn.execute(_INSERT, MERGE_RADIUS_M)).split()[-1])
        await conn.execute(_TEMPLE_BUILDINGS)
        temple_buildings = await conn.fetchval("SELECT count(*) FROM _temple_buildings")
        temples = int((await conn.execute(_INSERT_TEMPLES, HERITAGE_MERGE_RADIUS_M)).split()[-1])
        located = await _fill_areas(conn)
    await conn.execute("ANALYZE stop_places")
    logger.info("立ち寄り先: 群に入った %d件 → まとめて %d件、寺社の文化財 %d件 → 寺社 %d件、辺りの付いた %d件 / %.1f秒",
                grouped, inserted, temple_buildings, temples, located, time.perf_counter() - started)
    return inserted + temples
