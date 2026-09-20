"""取込の入口。`source_profile.yaml`が挙げるソースを、共通の経路で取り込む。

    .venv\\Scripts\\python.exe -m app.batch.ingest_cli --source accident
    .venv\\Scripts\\python.exe -m app.batch.ingest_cli --all
    .venv\\Scripts\\python.exe -m app.batch.ingest_cli --source accident --database-url ...

ソースごとにバッチを増やさない——増えるのはアダプタ1本とプロファイルの1エントリだけ。
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncpg  # noqa: E402

from app.batch import source_adapters  # noqa: F401,E402  アダプタの登録が目的
from app.batch._common import asyncpg_dsn, with_derived_data_revision_bump  # noqa: E402
from app.batch.ingest import ingest_source  # noqa: E402
from app.batch.source_profile import load_source_profile  # noqa: E402
from app.config import settings  # noqa: E402

logger = logging.getLogger("ridecompass.ingest_cli")


async def run(source_names: list[str], database_url: str) -> int:
    profile = load_source_profile()
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
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="外部ソースを共通の経路で取り込む")
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()

    profile = load_source_profile()
    names = [s.name for s in profile.sources] if args.all else args.source
    if not names:
        parser.error("--source か --all が必要です")
    unknown = [n for n in names if n not in {s.name for s in profile.sources}]
    if unknown:
        parser.error(f"プロファイルに無いソースです: {unknown}")

    database_url = args.database_url or settings.database_url
    # 生データが入れ替わると、それを読んで作ったキャッシュは古くなる。派生の世代を
    # 進めて下流を作り直させる（ソース別の世代へ移すまでは、既存の仕組みに乗せる）。
    return asyncio.run(with_derived_data_revision_bump(
        run(names, database_url), database_url=database_url, dry_run=False))


if __name__ == "__main__":
    raise SystemExit(main())
