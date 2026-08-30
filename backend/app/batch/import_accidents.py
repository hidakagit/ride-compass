"""警察庁交通事故統計オープンデータ→PostGIS取込バッチ
（docs/external-data-sources-review-2026-08-16.md §4.1、docs/improvement-plan.md T50）。

年ごとの本票CSV（`honhyo_{year}.csv`）を、年号だけで組み立てられる公開URLから直接取得し
（backend/data/accidents/へ一時保存、git管理外）、関東7都県に絞って`accident_points`へ
取り込む。pyosmium非依存の純CSVバッチのため、import_pbf.pyのようなストリーミング
producer/consumerは不要（1年分は最大でも数十万行、csv.readerで素直に処理できる）だが、
ステージング→MERGEの流儀とrun記録テーブルの持ち方はimport_pbf.pyを踏襲する。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.import_accidents --years 2022-2024 \\
        --database-url postgresql+asyncpg://ridecompass:ridecompass@localhost:5432/ridecompass

--yearsは"2022-2024"のような範囲表記、"2022,2024"のような個別指定、その混在
（"2022-2023,2024"）を受け付ける。

**2019〜2021年は未対応**（2026-08-16実データ確認）: 本票CSVの列構成が2022年以降と異なる
（サポカー・認知機能検査経過日数等の列が無い58列構成。2022年以降は68列）。
COL_*定数はいずれも2022年以降の68列レイアウトを前提にしており、異なる列数のCSVを渡すと
iter_kanto_rowsがValueErrorで即座に失敗する（黙って0件スキップにしない設計、詳細は同関数の
コメント参照）。2019〜2021年分を取り込みたい場合は、まず該当年のヘッダ列を確認したうえで
別のCOL_*定数セットを追加すること。
"""

import argparse
import asyncio
import csv
import logging
import sys
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import httpx
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.batch._common import asyncpg_dsn, download_to_path, reap_stale_running_import_runs, status_count
from app.domain.accident import (
    build_accident_id,
    involves_bicycle,
    is_fatal,
    is_kanto_prefecture,
    latitude_from_raw,
    longitude_from_raw,
)
from app.infrastructure import accident_models  # noqa: F401  Base.metadataへモデル登録するためのimport
from app.infrastructure.migrate import apply_pending_migrations
from app.infrastructure.road_graph_repository import create_tables

logger = logging.getLogger("app.batch.import_accidents")

HONHYO_URL_TEMPLATE = "https://www.npa.go.jp/publications/statistics/koutsuu/opendata/{year}/honhyo_{year}.csv"
# backend/app/batch/import_accidents.py から見て backend/data/accidents/
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "accidents"

# 本票CSVの列インデックス（0始まり）。2026-08-16にhonhyo_2023.csvの実ヘッダで確認済み
# （資料区分,都道府県コード,警察署等コード,本票番号,事故内容,死者数,...,
# 当事者種別（当事者A）,当事者種別（当事者B）,...,地点　緯度（北緯）,地点　経度（東経）,...）。
# 列順は年による変化が無いことをdry-runで年ごとに確認すること（COL定義がずれると
# 全行が黙って対象外になりうるため、_REQUIRED_COLUMNSで列数不一致は検知する）。
COL_PREFECTURE_CODE = 1
COL_POLICE_STATION_CODE = 2
COL_HONHYO_NUMBER = 3
COL_DEATH_COUNT = 5
COL_PARTY_TYPE_A = 38
COL_PARTY_TYPE_B = 39
COL_LATITUDE = 60
COL_LONGITUDE = 61
_REQUIRED_COLUMNS = 68

_STAGE_DDL = (
    "CREATE TEMP TABLE _stage_accident_points "
    "(accident_id text, occurred_year int, fatal boolean, involves_bicycle boolean, "
    "lon float8, lat float8)"
)
_MERGE_SQL = """
INSERT INTO accident_points (accident_id, occurred_year, fatal, involves_bicycle, attrs, geom, updated_at)
SELECT accident_id, occurred_year, fatal, involves_bicycle, '{}'::jsonb,
       ST_SetSRID(ST_MakePoint(lon, lat), 4326), $1
FROM _stage_accident_points
ON CONFLICT (accident_id) DO UPDATE SET
    fatal = EXCLUDED.fatal,
    involves_bicycle = EXCLUDED.involves_bicycle,
    geom = EXCLUDED.geom,
    updated_at = EXCLUDED.updated_at
"""


def parse_years(text: str) -> list[int]:
    """"2019-2024"（範囲）・"2019,2021"（個別）・その混在を年のリストへ変換する。"""
    years: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            years.extend(range(int(start), int(end) + 1))
        else:
            years.append(int(part))
    return years


async def _download_year(client: httpx.AsyncClient, year: int) -> Path | None:
    """本票CSVを年号から組み立てたURLで直接取得し、DATA_DIRへ保存する（改善計画T80、
    骨格はapp/batch/_common.py: download_to_pathへ共通化済み）。"""
    dest = DATA_DIR / f"honhyo_{year}.csv"
    url = HONHYO_URL_TEMPLATE.format(year=year)
    return await download_to_path(
        client, url, dest, logger=logger, label="本票CSV", context=f"year={year}", timeout_seconds=180.0
    )


def iter_kanto_rows(csv_path: Path, year: int) -> Iterator[tuple]:
    """CSVファイルを1行ずつ読み、関東7都県の行だけをステージング用タプルへ変換する
    （全件をメモリへ展開しない）。列数不足・緯度経度が変換不能な行はカウントし、
    最後にまとめてWARNINGを出す（1行ごとのログでバッチ全体のログが埋まらないようにする、
    かつ「欠損データを無理に補完しない」方針はdomain/accident.py側で担保済み）。
    """
    skipped = 0
    with open(csv_path, encoding="cp932", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        # 列数不一致は個々の行のスキップ理由（欠損データ）ではなく、CSVの列構成自体が
        # 想定と異なることを意味する（2026-08-16実データ確認: 2019〜2021年のCSVは
        # サポカー・認知機能検査経過日数等の列が無い58列構成で、2022年以降の68列構成とは
        # 別スキーマ。実際に2019年分をこの前提でインポートし、全行が列不足スキップになる
        # ことで発覚した）。行単位のWARNINGで握りつぶさず、その年のバッチ実行自体を
        # 失敗させて呼び出し側に知らせる（schema_migrationsと同じ「気づける形で落とす」方針）。
        if header is not None and len(header) != _REQUIRED_COLUMNS:
            raise ValueError(
                f"year={year}: 想定と異なる列数のCSVです（想定{_REQUIRED_COLUMNS}列、実際{len(header)}列）。"
                "年によってCSVスキーマが変わっている可能性があるため、この年の列位置定数"
                "（COL_*）を個別に確認してください。"
            )
        for row in reader:
            if len(row) < _REQUIRED_COLUMNS:
                skipped += 1
                continue
            prefecture_code = row[COL_PREFECTURE_CODE]
            if not is_kanto_prefecture(prefecture_code):
                continue
            lat = latitude_from_raw(row[COL_LATITUDE])
            lon = longitude_from_raw(row[COL_LONGITUDE])
            if lat is None or lon is None:
                skipped += 1
                continue
            accident_id = build_accident_id(
                prefecture_code, row[COL_POLICE_STATION_CODE], row[COL_HONHYO_NUMBER], year
            )
            yield (
                accident_id,
                year,
                is_fatal(row[COL_DEATH_COUNT]),
                involves_bicycle(row[COL_PARTY_TYPE_A], row[COL_PARTY_TYPE_B]),
                lon,
                lat,
            )
    if skipped:
        logger.warning("year=%d: 列不足・座標変換不能で%d件スキップしました", year, skipped)


async def run_import(years: list[int], database_url: str | None, dry_run: bool) -> int:
    started = time.perf_counter()
    sqlalchemy_url = database_url or settings.database_url

    csv_paths: dict[int, Path] = {}
    async with httpx.AsyncClient() as client:
        for year in years:
            path = await _download_year(client, year)
            if path is not None:
                csv_paths[year] = path

    if not csv_paths:
        logger.error("取得できた本票CSVが1件もありません")
        return 1

    if dry_run:
        total_matched = 0
        for year, path in sorted(csv_paths.items()):
            count = sum(1 for _ in iter_kanto_rows(path, year))
            total_matched += count
            logger.info("dry-run year=%d: 関東該当%d件", year, count)
        logger.info(
            "dry-run完了: years=%s matched=%d elapsed=%.1fs（DB書き込みなし）",
            sorted(csv_paths), total_matched, time.perf_counter() - started,
        )
        return 0

    engine = create_async_engine(sqlalchemy_url)
    try:
        await create_tables(engine)
        await apply_pending_migrations(engine)
    finally:
        await engine.dispose()

    conn = await asyncpg.connect(asyncpg_dsn(sqlalchemy_url))
    total_matched = 0
    total_upserted = 0
    try:
        # 改善計画T467: 前回実行がプロセスクラッシュでrunning状態のまま取り残されていないか
        # 確認し、あれば自己修復する（_common.py: reap_stale_running_import_runs参照）。
        reaped = await reap_stale_running_import_runs(conn, "accident_import_runs")
        if reaped:
            logger.warning(
                "クラッシュで取り残されたrunning状態のaccident_import_runsを%d件failedへ遷移しました", reaped
            )
        for year, path in sorted(csv_paths.items()):
            run_started_at = datetime.now(timezone.utc)
            run_id = await conn.fetchval(
                "INSERT INTO accident_import_runs (occurred_year, file_name, status, started_at) "
                "VALUES ($1, $2, 'running', $3) RETURNING id",
                year, path.name, run_started_at,
            )
            try:
                await conn.execute(_STAGE_DDL)
                records = list(iter_kanto_rows(path, year))
                await conn.copy_records_to_table(
                    "_stage_accident_points",
                    records=records,
                    columns=["accident_id", "occurred_year", "fatal", "involves_bicycle", "lon", "lat"],
                )
                merge_status = await conn.execute(_MERGE_SQL, run_started_at)
                upserted = status_count(merge_status)
                total_matched += len(records)
                total_upserted += upserted
                await conn.execute(
                    "UPDATE accident_import_runs SET status='succeeded', finished_at=$2, accident_count=$3 "
                    "WHERE id=$1",
                    run_id, datetime.now(timezone.utc), len(records),
                )
                logger.info(
                    "取込完了 year=%d matched=%d upserted=%d elapsed=%.1fs",
                    year, len(records), upserted, time.perf_counter() - started,
                )
            except BaseException:
                await conn.execute(
                    "UPDATE accident_import_runs SET status='failed', finished_at=$2 WHERE id=$1",
                    run_id, datetime.now(timezone.utc),
                )
                raise
            finally:
                await conn.execute("DROP TABLE IF EXISTS _stage_accident_points")
    finally:
        await conn.close()

    logger.info(
        "全年取込完了: years=%s matched=%d upserted=%d elapsed=%.1fs",
        sorted(csv_paths), total_matched, total_upserted, time.perf_counter() - started,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="警察庁交通事故統計オープンデータ→PostGIS取込バッチ（外部静的データソース T50）"
    )
    parser.add_argument(
        "--years", required=True, help='取込対象年（例: "2019-2024" または "2019,2021,2023"）'
    )
    parser.add_argument("--database-url", default=None, help="取込先DB（省略時はsettings.database_url）")
    parser.add_argument("--dry-run", action="store_true", help="件数集計のみでDBへ書き込まない")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    years = parse_years(args.years)
    return asyncio.run(run_import(years, args.database_url, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
