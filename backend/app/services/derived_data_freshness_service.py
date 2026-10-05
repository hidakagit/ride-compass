"""派生データの鮮度レポートを組み立てるサービス層。

集計の生値へ、画面がそのまま並べられる判定（作り直しが要るか）を足す。
レポートの型は`GET /api/admin/derived-data/freshness`の応答の型を兼ねる。
"""

import logging
import time
from datetime import datetime, timezone

from app.domain.strict_model import StrictModel
from app.infrastructure.debug_log import log_external_call
from app.infrastructure.derived_data_freshness import (
    DerivedDataFreshness,
    DerivedDataFreshnessQuery,
)

logger = logging.getLogger("ridecompass.derived_data_freshness")


class CoverageEntry(StrictModel):
    #: 被覆の母数（生データのソース名か親の表名）。
    parent: str
    parent_row_count: int
    #: 親にあって行が無い件数。覆うはずの表で1件でもあれば作り直しが要る。鮮度・完成度は
    #: これを見つけられない（行が無ければ古くもなければNULLでもない）。
    missing_rows: int


class ColumnEntry(StrictModel):
    """値の列1本ぶんの完成度。

    NULLには「まだ計算していない」と「確定して値が無い」がある。どちらの件数も返し、
    作り直しが要る側に数えるのは前者だけ。
    """

    column: str
    uncalculated_count: int
    absent_count: int


class SourceEntry(StrictModel):
    source: str
    #: 今の派生の表を作った取込。まだ作り直しに使っていなければNone。
    derived_run_id: int | None
    #: 成功した最新の取込。1度も成功していなければNone。
    latest_run_id: int | None
    #: 作り直しに使った取込が成功した最新の取込でない（取込が1度も成功していない・まだ作り直しに
    #: 使っていない、も含む）。画面は理由を問わずこれでソースを「作り直しが必要」に数える。
    needs_rebuild: bool


class TableEntry(StrictModel):
    table_name: str
    row_count: int
    #: 親に対して行が欠けていないか。覆うことを宣言していない表はNone。
    coverage: CoverageEntry | None
    columns: list[ColumnEntry]
    #: 作り直しが要る（値の列に未計算が残る・親に対して行が欠ける のどちらか）。
    #: 画面は理由を問わずこれで表を「作り直しが必要」に数える。
    needs_rebuild: bool


class DerivedDataFreshnessReport(StrictModel):
    computed_at: datetime
    sources: list[SourceEntry]
    tables: list[TableEntry]


def build_freshness_report(
    freshness: DerivedDataFreshness, computed_at: datetime
) -> DerivedDataFreshnessReport:
    return DerivedDataFreshnessReport(
        computed_at=computed_at,
        sources=[
            SourceEntry(
                source=source.source,
                derived_run_id=source.derived_run_id,
                latest_run_id=source.latest_run_id,
                needs_rebuild=source.needs_rebuild,
            )
            for source in freshness.sources
        ],
        tables=[
            TableEntry(
                table_name=table.table_name,
                row_count=table.row_count,
                coverage=(
                    CoverageEntry(
                        parent=table.coverage.parent,
                        parent_row_count=table.coverage.parent_row_count,
                        missing_rows=table.coverage.missing_rows,
                    )
                    if table.coverage
                    else None
                ),
                columns=[
                    ColumnEntry(
                        column=column.column,
                        uncalculated_count=column.uncalculated_count,
                        absent_count=column.absent_count,
                    )
                    for column in table.columns
                ],
                needs_rebuild=(
                    table.has_missing_rows
                    or any(column.uncalculated_count > 0 for column in table.columns)
                ),
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
        with log_external_call("admin:derived-data-freshness") as fields:
            freshness = await self._repository.get_freshness()
            fields["tables"] = len(freshness.tables)
        report = build_freshness_report(freshness, datetime.now(timezone.utc))
        stale = sum(1 for source in report.sources if source.needs_rebuild)
        incomplete = sum(1 for table in report.tables
                         for column in table.columns if column.uncalculated_count > 0)
        missing = sum(table.coverage.missing_rows for table in report.tables if table.coverage)
        logger.info(
            "derived data freshness computed tables=%d stale_sources=%d incomplete_columns=%d "
            "missing_rows=%d elapsed_ms=%d",
            len(report.tables), stale, incomplete, missing,
            round((time.monotonic() - started) * 1000),
        )
        return report
