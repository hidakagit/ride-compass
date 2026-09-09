"""road_edges.curvature_deg_per_km（蛇行の強さ）の事前計算バッチ。

折れ線の頂点ごとの方位変化を積み上げ距離kmで割った値。既存行はmigration 0035の適用後も
NULL（未計算）のままで、再splitされない限り埋まらないため、適用後の実行が必須。
NULLは「未計算」であって0（まっすぐ）ではない——0で埋めると、未計算の区間が
「まっすぐな良い道」として評価に混ざる。

計算はPostGISの`ST_Azimuth`で完結し、Pythonへ行を持ち出さない（本番500万行規模のため）。
`domain/geo.py: curvature_deg_per_km`と同じ定義（連続する同一頂点は`ST_Azimuth`がNULLを
返すので自然に除かれる）。road_edgesが変わった場合（PBF再取込・再split）は再実行が必要。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.precompute_edge_curvature
    .venv\\Scripts\\python.exe -m app.batch.precompute_edge_curvature --database-url ...
    --dry-runで対象件数のログのみ（DB書き込みなし）
"""

import logging
import sys
import time

from sqlalchemy import func, select, text

from app.batch._common import batch_session_factory, run_simple_batch_cli
from app.infrastructure.road_graph_models import RoadEdgeRow

logger = logging.getLogger("ridecompass.precompute_edge_curvature")

# 1文で全件更新すると本番規模では長時間ロックを取り続けるため、edge_idの範囲で分割する。
CHUNK_SIZE = 200_000

_RECOMPUTE_SQL = text(
    """
    WITH target AS (
        SELECT edge_id, geom, distance_m
        FROM road_edges
        WHERE distance_m > 0
        ORDER BY edge_id
        LIMIT :limit OFFSET :offset
    ),
    vertex AS (
        SELECT t.edge_id, (dp.path)[1] AS i, dp.geom AS point
        FROM target t, LATERAL ST_DumpPoints(t.geom) dp
    ),
    leg AS (
        SELECT edge_id, i,
               -- geographyへキャストして測地線上の方位角を取る。geometry（4326）のまま
               -- ST_Azimuthを呼ぶと経度・緯度をそのままx/yとして扱う平面計算になり、
               -- 緯度による経度の縮みを無視するため domain/geo.py: bearing_between
               -- （球面三角法）と値が食い違う。同じEdgeに2つの定義が生まれるのを防ぐ。
               degrees(ST_Azimuth(
                   point::geography,
                   LEAD(point) OVER (PARTITION BY edge_id ORDER BY i)::geography
               )) AS az
        FROM vertex
    ),
    turn AS (
        SELECT edge_id,
               abs(az - LEAD(az) OVER (PARTITION BY edge_id ORDER BY i)) AS raw_delta
        FROM leg
        WHERE az IS NOT NULL
    ),
    total AS (
        SELECT edge_id, SUM(LEAST(raw_delta, 360 - raw_delta)) AS deg
        FROM turn
        WHERE raw_delta IS NOT NULL
        GROUP BY edge_id
    )
    UPDATE road_edges e
    SET curvature_deg_per_km = COALESCE(total.deg, 0) / (e.distance_m / 1000)
    FROM target t
    LEFT JOIN total ON total.edge_id = t.edge_id
    WHERE e.edge_id = t.edge_id
    """
)


async def run(database_url: str | None, dry_run: bool) -> int:
    started = time.perf_counter()
    async with batch_session_factory(database_url) as session_factory:
        async with session_factory() as session:
            edge_count = (
                await session.execute(
                    select(func.count()).select_from(RoadEdgeRow).where(RoadEdgeRow.distance_m > 0)
                )
            ).scalar_one()

        logger.info("対象road_edges: %d件（%d件ずつ更新）", edge_count, CHUNK_SIZE)
        if dry_run:
            logger.info("dry-run完了: DB書き込みなし elapsed=%.1fs", time.perf_counter() - started)
            return 0
        if edge_count == 0:
            logger.warning("road_edgesが0件のため更新をスキップします")
            return 0

        updated = 0
        for offset in range(0, edge_count, CHUNK_SIZE):
            chunk_started = time.perf_counter()
            async with session_factory() as session:
                result = await session.execute(_RECOMPUTE_SQL, {"limit": CHUNK_SIZE, "offset": offset})
                await session.commit()
            updated += result.rowcount or 0
            logger.info(
                "更新 %d/%d件 chunk_ms=%d",
                updated, edge_count, round((time.perf_counter() - chunk_started) * 1000),
            )

        logger.info("蛇行の事前計算完了: %d件 elapsed=%.1fs", updated, time.perf_counter() - started)
        return 0


def main(argv: list[str] | None = None) -> int:
    return run_simple_batch_cli(argv, description="road_edges.curvature_deg_per_km事前計算バッチ", run_fn=run)


if __name__ == "__main__":
    sys.exit(main())
