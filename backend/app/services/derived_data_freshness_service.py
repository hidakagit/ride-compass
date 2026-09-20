"""派生データの鮮度レポートを組み立てるサービス層。

集計（`infrastructure/derived_data_freshness.py`）の生値へ、画面がそのまま並べられる
判定（古いか・未計算が残っているか）を足すだけ。組み立て自体は純関数でDBに依存しない。
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from app.infrastructure.debug_log import log_external_call
from app.infrastructure.derived_data_freshness import (
    DerivedDataFreshness,
    DerivedDataFreshnessQuery,
)

logger = logging.getLogger("ridecompass.derived_data_freshness")


@dataclass(frozen=True)
class ColumnEntry:
    column: str
    null_count: int
    #: NULLが「まだ計算していない」を意味する列で、実際にNULLが残っている。
    is_incomplete: bool


@dataclass(frozen=True)
class TableEntry:
    table_name: str
    row_count: int
    source: str | None
    oldest_run_id: int | None
    latest_run_id: int | None
    #: 生データを取り直したのに派生を流し直していない。
    is_stale: bool
    #: 被覆の母数の呼び名。覆うことを宣言していない表はNone。
    coverage_parent: str | None
    coverage_parent_row_count: int | None
    #: 親にあって行が無い件数。覆うはずの表で1件でもあれば作り直しが要る。
    missing_rows: int | None
    columns: list[ColumnEntry]


@dataclass(frozen=True)
class DerivedDataFreshnessReport:
    computed_at: datetime
    tables: list[TableEntry]


def build_freshness_report(
    freshness: DerivedDataFreshness, computed_at: datetime
) -> DerivedDataFreshnessReport:
    return DerivedDataFreshnessReport(
        computed_at=computed_at,
        tables=[
            TableEntry(
                table_name=table.table_name,
                row_count=table.row_count,
                source=table.source,
                oldest_run_id=table.oldest_run_id,
                latest_run_id=table.latest_run_id,
                is_stale=table.is_stale,
                coverage_parent=table.coverage.parent if table.coverage else None,
                coverage_parent_row_count=(
                    table.coverage.parent_row_count if table.coverage else None),
                missing_rows=table.coverage.missing_rows if table.coverage else None,
                columns=[
                    ColumnEntry(
                        column=column.column,
                        null_count=column.null_count,
                        is_incomplete=column.counts_as_uncalculated and column.null_count > 0,
                    )
                    for column in table.columns
                ],
            )
            for table in freshness.tables
        ],
    )


class DerivedDataFreshnessService:
    def __init__(self, repository: DerivedDataFreshnessQuery):
        self._repository = repository

    async def get_freshness_report(self) -> DerivedDataFreshnessReport:
        """DB例外は呼び出し元（router）へそのまま伝播させる。管理者向けの診断APIのため、
        空のレポートへ倒して「鮮度不整合なし」に見せるより失敗を明示する方が安全。"""
        started = time.monotonic()
        with log_external_call("derived-data-freshness") as fields:
            freshness = await self._repository.get_freshness()
            fields["tables"] = len(freshness.tables)
        report = build_freshness_report(freshness, datetime.now(timezone.utc))
        stale = sum(1 for table in report.tables if table.is_stale)
        incomplete = sum(1 for table in report.tables
                         for column in table.columns if column.is_incomplete)
        missing = sum(table.missing_rows or 0 for table in report.tables)
        logger.info(
            "derived data freshness computed tables=%d stale_tables=%d incomplete_columns=%d "
            "missing_rows=%d elapsed_ms=%d",
            len(report.tables), stale, incomplete, missing,
            round((time.monotonic() - started) * 1000),
        )
        return report
