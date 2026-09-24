"""派生を作り直す入口。**順番はここだけが持つ**。

生データを差し替えたら、下流を全部作り直す。段は次の依存で決まっており、飛ばせない:
形（`road_edges`）が無いと材料の行が作れず、ノードの枝数が無いと交差点を数えられず、
区間の値が無いと道の値を導けない。

    .venv\\Scripts\\python.exe -m app.batch.derive_cli
    .venv\\Scripts\\python.exe -m app.batch.derive_cli --from counts

途中から流し直すのは、ある段のやり方だけを変えたとき（分類器を直した・しきい値を
変えた）。生データを取り直したときは最初から通す。`--from`はその段から後ろを全部流す。

後ろの段がみな直前の段の値を読むわけではない。面を線へ落とす段（`raster`）はノードの値も
数の値も読まず、数の段が作る道1本の行へ書き込むためにその後ろにある。そのため`--from`は、
変えた段の値を読まない段まで流し直すことがある。段は単独の入口を持たない——どの段がどの段の
値を読むかは宣言されておらず、1段だけ流してそれを読む段を流し忘れると、古い入力から作った
値が残る。
"""

import argparse
import logging
import sys
import time
from collections.abc import Awaitable, Callable
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
from app.batch._common import asyncpg_dsn, format_duration, run_batch_cli  # noqa: E402

logger = logging.getLogger("ridecompass.derive_cli")

STAGES: tuple[tuple[str, Callable[[asyncpg.Connection], Awaitable[object]]], ...] = (
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
    parser = argparse.ArgumentParser(description="生データから派生を作り直す")
    parser.add_argument("--from", dest="start_from", default=None,
                        choices=[name for name, _ in STAGES])
    return run_batch_cli(parser, lambda args, database_url: run(database_url, args.start_from))


if __name__ == "__main__":
    raise SystemExit(main())
