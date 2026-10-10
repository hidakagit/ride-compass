"""立ち寄り先（`stop_places`）を、地点の生データ（Overture の地点・国の文化財の建造物）から作り直す。

**群はここで付ける**。取込は外部が持っていた列をそのまま入れるだけで、「どの群か」は派生の側の判断である。
語の表は`domain/stop_place.py`が持ち、このバッチはそれをSQLへ渡すだけで、行を取り出さない。

同じ群・同じチェーン（`domain/stop_place.py: chain_sql`）で`MERGE_RADIUS_M`以内に並ぶ地点は、確からしさの最も
高い1つにまとめる（同じなら識別子の小さいほう）。まとまりは近い点を連ねて作るので、端と端がその距離より離れることが
ある。チェーンの分からない地点は別々の店としてまとめない。群「コンビニ」は、コンビニのチェーン（`CHAIN_WORDS`）に
当たる地点だけを入れる（`kept_sql`）。店の中の ATM の地点は、名前を店の名前へ直してから群とチェーンを決める
（`store_name_sql`）——店の隣にあれば店とまとまり、無ければ店として残る。

チェーンの分からない地点のうち名前に日本語の文字が無いもの（`japanese_name_sql`）は、群（`CONTACT_MERGE_RADIUS_M`の群だけ）が
同じで同じ連絡先（`contacts_sql`）を持つ、チェーンの分からない日本語の名前の地点があれば落とし、その地点へ寄せる（寄せ先の
名前・位置・確からしさはそのまま）。使う連絡先は、それを持つ地点が全部互いにその群の距離以内にあるものだけ——遠くの地点とも
共有する連絡先は、会社・一覧のページや、百貨店・管理事務所の代表の電話で、その場所のものでない。日本語の名前どうし・
日本語でない名前どうしは寄せない（同じ連絡先を持つ同じ施設群の中の別の場所を残す）。

寺社は文化財の建造物の所有者から出す。所有者の欄の1人ずつのうち寺社の名前（`temple_shrine_owner_sql`）を持つ建物を、
同じ名前（表記の揺れを除いた形）で`HERITAGE_MERGE_RADIUS_M`以内に連なるものごとに1つの寺社にする。位置はまとまりの
重心に最も近い建物（重心は境内の外に落ちることがある）、名前は所有者の名前。1つの建物に寺社の所有者が2人いれば、
両方の寺社に入る。

辺り（`area`）は、入れた地点の位置を含む小地域の境界の名前（`infrastructure/place_area_query.py: area_label_sql`）。
ほかの段の表も道の網も読まない。
"""

import logging
import time

import asyncpg

from app.domain.geo import ground_m_sql
from app.domain.stop_place import (
    CONTACT_MERGE_RADIUS_M,
    HERITAGE_MERGE_RADIUS_M,
    MERGE_RADIUS_M,
    StopPlaceGroup,
    chain_sql,
    chain_text_sql,
    contacts_sql,
    japanese_name_sql,
    kept_sql,
    normalized_sql,
    overture_group_sql,
    owner_lines_sql,
    owner_name_sql,
    store_name_sql,
    temple_shrine_owner_sql,
)
from app.infrastructure.place_area_query import area_label_sql
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

#: 地点の連絡先（1つの連絡先が1行）と、寄せに使える連絡先（2つ以上の地点が持ち、それを持つ地点（群を問わない）の広がりが
#: どれかの群の距離以内のもの）の広がり。広がりは経度・緯度の外接の矩形の対角の地面の m——最も離れた2点の間より短くならない
#: ので、広がりが群の距離以内なら持つ地点どうしは互いにその距離以内にある（2点ずつ測ると、コンビニのチェーンのサイトのように
#: 数千の地点が持つ連絡先で数千万回測り、地点ごとに地面の m の平面へ写すと関東の約50万行で1分半かかる）。一時の表は
#: 統計を持たないので、寄せで結ぶ表を`ANALYZE`する（無いと結合を入れ子の繰り返しで組み、関東の地点で10分を超える）。
_CONTACTS = f"""
CREATE TEMP TABLE _contacts ON COMMIT DROP AS
SELECT o.overture_id, c.contact, ST_X(o.geom) AS lon, ST_Y(o.geom) AS lat
FROM {OVERTURE_PLACES_SOURCE_SQL} o CROSS JOIN LATERAL ({contacts_sql("o.websites", "o.phones")}) c;
CREATE TEMP TABLE _contact_spans ON COMMIT DROP AS
SELECT contact, span FROM (
    SELECT contact, count(*) AS holders,
           ST_Distance(ST_MakePoint(min(lon), min(lat))::geography, ST_MakePoint(max(lon), max(lat))::geography) AS span
    FROM _contacts GROUP BY contact
) c
WHERE holders > 1 AND span <= {max(CONTACT_MERGE_RADIUS_M.values())};
ANALYZE _contacts;
ANALYZE _contact_spans;
ANALYZE _grouped_places
"""

_CONTACT_RADII = ", ".join(f"('{group}', {radius})" for group, radius in CONTACT_MERGE_RADIUS_M.items())

# 日本語の名前の地点は落とさないので、寄せ先が連なって消えることはない。
_MERGE_BY_CONTACT = f"""
DELETE FROM _grouped_places f
USING (
    SELECT DISTINCT fc.overture_id
    FROM _contact_spans s
    JOIN _contacts fc ON fc.contact = s.contact
    JOIN _contacts jc ON jc.contact = s.contact
    JOIN _grouped_places fp ON fp.overture_id = fc.overture_id
    JOIN _grouped_places j ON j.overture_id = jc.overture_id
    JOIN (VALUES {_CONTACT_RADII}) AS r(place_group, radius) ON r.place_group = fp.place_group
    WHERE s.span <= r.radius AND fp.chain IS NULL AND NOT {japanese_name_sql("fp.name")}
      AND j.place_group = fp.place_group AND j.chain IS NULL AND {japanese_name_sql("j.name")}
) merged
WHERE f.overture_id = merged.overture_id
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

_SET_AREAS = f"UPDATE stop_places s SET area = {area_label_sql('s.geom')}"


async def derive(conn: asyncpg.Connection) -> int:
    """立ち寄り先の表を入れ直し、入れた地点の数を返す。"""
    started = time.perf_counter()
    async with conn.transaction():
        await conn.execute("DELETE FROM stop_places")
        await conn.execute(_GROUPED)
        grouped = await conn.fetchval("SELECT count(*) FROM _grouped_places")
        await conn.execute(_CONTACTS)
        merged_by_contact = int((await conn.execute(_MERGE_BY_CONTACT)).split()[-1])
        inserted = int((await conn.execute(_INSERT, MERGE_RADIUS_M)).split()[-1])
        await conn.execute(_TEMPLE_BUILDINGS)
        temple_buildings = await conn.fetchval("SELECT count(*) FROM _temple_buildings")
        temples = int((await conn.execute(_INSERT_TEMPLES, HERITAGE_MERGE_RADIUS_M)).split()[-1])
        await conn.execute(_SET_AREAS)
        located = await conn.fetchval("SELECT count(*) FROM stop_places WHERE area IS NOT NULL")
    await conn.execute("ANALYZE stop_places")
    logger.info("立ち寄り先: 群に入った %d件 → 連絡先で寄せて %d件減 → まとめて %d件、寺社の文化財 %d件 → 寺社 %d件、"
                "辺りの付いた %d件 / %.1f秒", grouped, merged_by_contact, inserted, temple_buildings, temples, located,
                time.perf_counter() - started)
    return inserted + temples
