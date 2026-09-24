"""取込の入口。`source_profile.yaml`が挙げるソースを、共通の経路で取り込む。

    .venv\\Scripts\\python.exe -m app.batch.ingest_cli --source accident
    .venv\\Scripts\\python.exe -m app.batch.ingest_cli --all
    .venv\\Scripts\\python.exe -m app.batch.ingest_cli --source accident --database-url ...

ソースごとにバッチを増やさない——増えるのはアダプタ1本とプロファイルの1エントリだけ。
"""

import argparse
import logging
import sys
from collections.abc import Awaitable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncpg  # noqa: E402

from app.batch._common import asyncpg_dsn, run_batch_cli  # noqa: E402
from app.batch.ingest import ingest_source  # noqa: E402
from app.batch.source_profile import SourceProfile, load_source_profile  # noqa: E402

logger = logging.getLogger("ridecompass.ingest_cli")


async def run(source_names: list[str], database_url: str, profile: SourceProfile) -> int:
    conn = await asyncpg.connect(asyncpg_dsn(database_url))
    try:
        for name in source_names:
            async with conn.transaction():
                run_id = await ingest_source(conn, profile, name)
                logger.info("source=%s run_id=%d", name, run_id)
    finally:
        await conn.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="外部ソースを共通の経路で取り込む")
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--all", action="store_true")
    # 母集団の宣言はプロファイルが持つ。狭い範囲で試すときは別のプロファイルを指す
    # ——引数で範囲を上書きできるようにすると、宣言がファイルの外へ散る。
    parser.add_argument("--profile", default=None, type=Path)

    def start(args: argparse.Namespace, database_url: str) -> Awaitable[int]:
        profile = load_source_profile(args.profile)
        names = [s.name for s in profile.sources] if args.all else args.source
        if not names:
            parser.error("--source か --all が必要です")
        unknown = [n for n in names if n not in {s.name for s in profile.sources}]
        if unknown:
            parser.error(f"プロファイルに無いソースです: {unknown}")
        return run(names, database_url, profile)

    return run_batch_cli(parser, start)


if __name__ == "__main__":
    raise SystemExit(main())
