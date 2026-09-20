"""ノードに付く値（`node_materials`）のうち、種別と交差点まわりを埋める。

**種別（`kind`）は取込ではなく、ここで付ける。**取込は外部が持っていたタグをそのまま
入れるだけで、「これはPOIか」「どの種別か」という判断は派生の側の仕事である。判断が
変わったら、生データを取り直さずにここを流し直せばよい。

**処理はDB内で完結する。**タグを読むためだけに行を取り出さない。タグから種別への
引き当ては`domain/traffic.py`が表と式で持ち、このバッチはそれをSQLへ渡すだけである。

`branch_count`は`derive_topology.py`が先に埋める。このバッチは種別・信号の有無・
集まる道の最大階級を足す。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.derive_node_materials
"""

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncpg  # noqa: E402

from app.batch._common import asyncpg_dsn, with_derived_data_revision_bump  # noqa: E402
from app.config import settings  # noqa: E402
from app.domain.traffic import (  # noqa: E402
    HIGHWAY_RANK,
    TRAFFIC_SIGNAL_SQL,
    tag_kind_sql,
)

logger = logging.getLogger("ridecompass.derive_node_materials")

#: 信号とみなす半径（m）。交差点そのものではなく流入路ごとに信号ノードが置かれるため、
#: `osm_node_id`の一致では大半を取りこぼす。
SIGNAL_RADIUS_M = 25.0

#: タグから種別・信号を判定する側が期待する形（`id`・`tags`）へ生データを写す。
#: タグの無いノード（形状の頂点）はどの規則にも当たらないので、先に落とす。
_SOURCE_NODES = ("SELECT natural_key::bigint AS id, attrs AS tags FROM source_features"
                 " WHERE source = 'osm_node' AND attrs <> '{}'::jsonb")

_UPSERT_KIND = f"""
INSERT INTO node_materials (osm_node_id, kind, source_run_id)
SELECT id, kind, $1 FROM ({tag_kind_sql(_SOURCE_NODES)}) k
ON CONFLICT (osm_node_id) DO UPDATE SET kind = EXCLUDED.kind
"""

_SIGNAL_NODES = f"""
CREATE TEMP TABLE _signal_nodes ON COMMIT DROP AS
SELECT s.id AS osm_node_id FROM ({_SOURCE_NODES}) s WHERE {TRAFFIC_SIGNAL_SQL}
"""

#: 信号は流入路ごとに別ノードで置かれるため、半径で拾う。
#:
#: `&&`の前置フィルタを先に置くのは、`::geography`へのキャストがgeometryのGiSTを
#: 使えなくするため。矩形で絞ってから正確な距離を測る。
_UPDATE_SIGNALS = """
UPDATE node_materials nm
SET has_traffic_signals = EXISTS (
    SELECT 1 FROM source_features sig
    JOIN _signal_nodes sk ON sk.osm_node_id = sig.natural_key::bigint
    WHERE sig.source = 'osm_node'
      AND sig.geom && ST_Expand(self.geom, $2)
      AND ST_DWithin(sig.geom::geography, self.geom::geography, $1)
)
FROM source_features self
WHERE self.source = 'osm_node' AND self.natural_key = nm.osm_node_id::text
"""

#: そのノードに集まる道の最大階級。順位表はdomain側が持ち、SQLへ書き写さない。
_UPDATE_MAX_RANK_TEMPLATE = """
WITH ranked AS (
    SELECT e.from_node_id AS node_id, r.rank FROM road_edges e
    JOIN source_features w ON w.source = 'osm_way' AND w.natural_key = e.osm_way_id::text
    JOIN (VALUES {values}) AS r(highway, rank) ON r.highway = w.attrs->>'highway'
    UNION ALL
    SELECT e.to_node_id, r.rank FROM road_edges e
    JOIN source_features w ON w.source = 'osm_way' AND w.natural_key = e.osm_way_id::text
    JOIN (VALUES {values}) AS r(highway, rank) ON r.highway = w.attrs->>'highway'
),
best AS (SELECT node_id, max(rank) AS max_rank FROM ranked GROUP BY node_id)
UPDATE node_materials nm SET max_highway_rank = best.max_rank
FROM best WHERE best.node_id = nm.osm_node_id
"""


async def _latest_run(conn: asyncpg.Connection, source: str) -> int:
    run_id = await conn.fetchval(
        "SELECT max(run_id) FROM source_runs WHERE source = $1 AND status = 'succeeded'", source)
    if run_id is None:
        raise RuntimeError(f"'{source}' の取込が成功していません")
    return run_id


async def derive(conn: asyncpg.Connection) -> int:
    run_id = await _latest_run(conn, "osm_node")
    started = time.perf_counter()

    values = ", ".join(f"('{h}', {r})" for h, r in sorted(HIGHWAY_RANK.items()))
    async with conn.transaction():
        classified = int((await conn.execute(_UPSERT_KIND, run_id)).split()[-1])
        await conn.execute(_SIGNAL_NODES)
        await conn.execute("CREATE UNIQUE INDEX ON _signal_nodes (osm_node_id)")
        signals = await conn.fetchval("SELECT count(*) FROM _signal_nodes")
        await conn.execute("ANALYZE _signal_nodes")
        # 緯度が高いほど1度は短い。取りこぼさないよう余裕を持たせる。
        await conn.execute(_UPDATE_SIGNALS, SIGNAL_RADIUS_M,
                           SIGNAL_RADIUS_M / 111_000.0 * 2.0)
        await conn.execute(_UPDATE_MAX_RANK_TEMPLATE.format(values=values))

    logger.info("ノードの値を埋めた: 種別が付いた %d点 / 信号 %d点 / %.1f秒",
                classified, signals, time.perf_counter() - started)
    return classified


async def run(database_url: str) -> int:
    conn = await asyncpg.connect(asyncpg_dsn(database_url))
    try:
        await derive(conn)
    finally:
        await conn.close()
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="ノードに付く値を埋める")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()
    database_url = args.database_url or settings.database_url
    # 派生が変われば、それを読んで作ったキャッシュは古くなる。
    return asyncio.run(with_derived_data_revision_bump(
        run(database_url), database_url=database_url, dry_run=False))


if __name__ == "__main__":
    raise SystemExit(main())
