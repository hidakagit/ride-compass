"""派生を作り直す入口。**順番はここだけが持つ**。

生データを差し替えたら、下流を全部作り直す。段は次の依存で決まっており、飛ばせない:
形（`road_edges`）が無いと材料の行が作れず、ノードの枝数が無いと交差点を数えられず、
区間の値が無いと道の値を導けない。

    .venv\\Scripts\\python.exe -m app.batch.derive_cli
    .venv\\Scripts\\python.exe -m app.batch.derive_cli --from counts

途中から流し直すのは、ある段のやり方だけを変えたとき（分類器を直した・しきい値を
変えた）。生データを取り直したときは最初から通す。
"""

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncpg  # noqa: E402

from app.batch import (  # noqa: E402
    derive_counts,
    derive_node_materials,
    derive_raster_materials,
    derive_topology,
    derive_way_materials,
)
from app.batch._common import (  # noqa: E402
    asyncpg_dsn,
    format_duration,
    with_derived_data_revision_bump,
)
from app.config import settings  # noqa: E402

logger = logging.getLogger("ridecompass.derive_cli")

STAGES: tuple[tuple[str, object], ...] = (
    ("topology", derive_topology.derive),
    ("nodes", derive_node_materials.derive),
    ("counts", derive_counts.derive),
    ("raster", derive_raster_materials.derive),
    ("ways", derive_way_materials.derive),
)


async def run(database_url: str, start_from: str | None) -> int:
    names = [name for name, _ in STAGES]
    begin = names.index(start_from) if start_from else 0
    conn = await asyncpg.connect(asyncpg_dsn(database_url))
    started = time.perf_counter()
    try:
        for index, (name, stage) in enumerate(STAGES[begin:], start=1):
            stage_started = time.perf_counter()
            logger.info("段 %s を開始（%d/%d）", name, index, len(STAGES) - begin)
            await stage(conn)
            logger.info("段 %s 完了 / %s", name,
                        format_duration(time.perf_counter() - stage_started))
    finally:
        await conn.close()
    logger.info("派生を作り直した: %s / %s",
                "→".join(names[begin:]), format_duration(time.perf_counter() - started))
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="生データから派生を作り直す")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--from", dest="start_from", default=None,
                        choices=[name for name, _ in STAGES])
    args = parser.parse_args()
    database_url = args.database_url or settings.database_url
    return asyncio.run(with_derived_data_revision_bump(
        run(database_url, args.start_from), database_url=database_url, dry_run=False))


if __name__ == "__main__":
    raise SystemExit(main())
