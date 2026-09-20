r"""まっさらなDBを、使える状態まで立ち上げる。

**順番はここだけが持つ**: スキーマ → 取込 → 派生。手で並べると、どれかが抜けたまま
「動いているように見える」状態ができる。

**拡張は入れずに要求する。** `CREATE EXTENSION`はスーパーユーザーでしか打てないため、
足りなければ`create_tables()`が何を実行すればよいかを告げて止まる。

**外部ソースの取得は含まない。** `.pbf`・標高タイル・土地被覆のGeoTIFFは先に手元へ
写しておく（`scripts/fetch_dem_tiles.py`・`scripts/fetch_lulc_raster.py`）——取込の
途中でHTTPを叩くと、外部の一時的な失敗ひとつで数時間ぶんがやり直しになる。

途中で落ちても`--from`で続きから流せる。段ごとの所要を出すので、時間がどこへ
消えたかが後から分かる。

実行方法（backendディレクトリから）:
    .venv\Scripts\python.exe scripts\bootstrap_database.py
    .venv\Scripts\python.exe scripts\bootstrap_database.py --from ingest
    .venv\Scripts\python.exe scripts\bootstrap_database.py --profile path/to/profile.yaml
"""

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.batch import derive_cli, ingest_cli  # noqa: E402
from app.batch._common import format_duration, with_derived_data_revision_bump  # noqa: E402
from app.batch.source_profile import load_source_profile  # noqa: E402
from app.config import settings  # noqa: E402
from app.infrastructure.road_graph_repository import create_tables  # noqa: E402

logger = logging.getLogger("ridecompass.bootstrap_database")


async def _schema(database_url: str, profile_path: Path | None) -> None:
    engine = create_async_engine(database_url)
    try:
        await create_tables(engine)
    finally:
        await engine.dispose()


async def _ingest(database_url: str, profile_path: Path | None) -> None:
    profile = load_source_profile(profile_path)
    await ingest_cli.run([s.name for s in profile.sources], database_url, profile_path)


async def _derive(database_url: str, profile_path: Path | None) -> None:
    await derive_cli.run(database_url, None)


#: 上から順に流す。後ろの段は前の段の出力を読む。
PHASES: tuple[tuple[str, object], ...] = (
    ("schema", _schema),
    ("ingest", _ingest),
    ("derive", _derive),
)


async def run(database_url: str, profile_path: Path | None, start_from: str | None) -> int:
    names = [name for name, _ in PHASES]
    begin = names.index(start_from) if start_from else 0
    started = time.perf_counter()
    for index, (name, phase) in enumerate(PHASES[begin:], start=1):
        phase_started = time.perf_counter()
        logger.info("=== %s を開始（%d/%d）===", name, index, len(PHASES) - begin)
        await phase(database_url, profile_path)
        logger.info("=== %s 完了 / %s ===", name,
                    format_duration(time.perf_counter() - phase_started))
    logger.info("DBを立ち上げた: %s / 合計 %s",
                "→".join(names[begin:]), format_duration(time.perf_counter() - started))
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="まっさらなDBを使える状態まで立ち上げる")
    parser.add_argument("--database-url", default=None)
    # 母集団の宣言はプロファイルが持つ。狭い範囲で試すときは別のプロファイルを指す。
    parser.add_argument("--profile", default=None, type=Path)
    parser.add_argument("--from", dest="start_from", default=None,
                        choices=[name for name, _ in PHASES],
                        help="途中から流し直す。前の段の出力が残っていることが前提")
    args = parser.parse_args()

    database_url = args.database_url or settings.database_url
    # 生データも派生も入れ替わるので、それを読んで作ったキャッシュは全部古くなる。
    return asyncio.run(with_derived_data_revision_bump(
        run(database_url, args.profile, args.start_from),
        database_url=database_url, dry_run=False))


if __name__ == "__main__":
    raise SystemExit(main())
