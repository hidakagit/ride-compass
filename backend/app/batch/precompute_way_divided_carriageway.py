"""「上下線が分かれた道の片側か」（way_geometry.divided_carriageway）の事前計算バッチ。

OSMは中央分離帯のある道路の上下線を別々のwayとして持ち、その一本ずつに oneway=yes を
付ける。そのため `osm_raw_ways.direction` だけでは「一方通行規制の道」と「上下線が分かれた
道の片側」を区別できず、一方通行レイヤーが後者まで塗ってしまう（後者は道路としては双方向で、
逆方向は数m隣にある）。判定は逆向きに並走する相方の有無で行う（測り方のSQLは
`road_graph_repository.py: _RECOMPUTE_WAY_DIVIDED_CARRIAGEWAY_SQL`）。

母集団は`osm_raw_ways`全域。`precompute_way_curvature.py`と同じ`way_geometry`の行を
触るが、更新する列は分かれているため実行順は問わない。

migration 0040適用後、本番でも初回実行が必須（他のprecomputeバッチと同じ運用）。
osm_raw_waysが変わった場合（PBF再取込）は再実行し、タイル世代
（region_service.py: ROAD_SURFACE_TILE_VERSION）を対上げしてキャッシュ済みタイルの
陳腐化を断つこと。

実行方法（backendディレクトリから）:
    .venv\Scripts\python.exe -m app.batch.precompute_way_divided_carriageway
    .venv\Scripts\python.exe -m app.batch.precompute_way_divided_carriageway --database-url ...
    --dry-runで対象件数のログのみ（DB書き込みなし）
"""

import logging
import sys
from datetime import datetime, timezone

from sqlalchemy import select, text

from app.batch._common import batch_session_factory, run_chunked_precompute, run_simple_batch_cli
from app.domain.derived_data_versions import WAY_DIVIDED_CARRIAGEWAY_ALGORITHM_VERSION
from app.infrastructure.road_graph_models import OsmRawWayRow
from app.infrastructure.road_graph_repository import RoadGraphRepository

logger = logging.getLogger("ridecompass.precompute_way_divided_carriageway")

# 1チャンクあたりのway数。1件ごとに近傍探索（GiST）が要るぶん他のway系バッチより重いため
# 小さめに取り、チャンク単位の進捗が見えるようにする。
CHUNK_SIZE = 5_000

ALGORITHM_VERSION = WAY_DIVIDED_CARRIAGEWAY_ALGORITHM_VERSION

_LATEST_SUCCEEDED_OSM_RUN_ID_SQL = text("SELECT MAX(id) FROM osm_import_runs WHERE status = 'succeeded'")


def _target_way_ids_stmt():
    # 双方向のwayも対象に含めてfalseの行を作る。母集団をdirection <> 'both'へ絞ると、
    # 「行が無い＝未判定」と「判定してfalseだった」が区別できなくなる。
    return select(OsmRawWayRow.osm_way_id)


async def run(database_url: str | None, dry_run: bool) -> int:
    stmt = _target_way_ids_stmt()
    async with batch_session_factory(database_url) as session_factory:
        now = datetime.now(timezone.utc)

        async def handle_chunk(chunk: list[int]) -> int:
            async with session_factory() as session:
                source_osm_run_id = (await session.execute(_LATEST_SUCCEEDED_OSM_RUN_ID_SQL)).scalar_one()
                repository = RoadGraphRepository(session)
                await repository.recompute_way_divided_carriageway(
                    chunk, now, source_osm_run_id, ALGORITHM_VERSION
                )
                await session.commit()
            return len(chunk)

        return await run_chunked_precompute(
            session_factory, stmt, CHUNK_SIZE, handle_chunk,
            logger=logger,
            target_label="対象way数",
            empty_warning="対象wayが0件のため更新をスキップします（osm_raw_waysが空の可能性）",
            dry_run=dry_run,
        )


def main(argv: list[str] | None = None) -> int:
    return run_simple_batch_cli(argv, description="上下線分離の判定バッチ", run_fn=run)


if __name__ == "__main__":
    sys.exit(main())
