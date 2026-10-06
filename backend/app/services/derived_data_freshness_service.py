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
    SourceFreshness,
    TableFreshness,
)

logger = logging.getLogger("ridecompass.derived_data_freshness")


class SourceEntry(SourceFreshness):
    #: 作り直しに使った取込が成功した最新の取込でない（取込が1度も成功していない・まだ作り直しに
    #: 使っていない、も含む）。画面は理由を問わずこれでソースを「作り直しが必要」に数える。
    needs_rebuild: bool


class TableEntry(TableFreshness):
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
                **dict(source),
                needs_rebuild=source.latest_run_id is None or source.derived_run_id != source.latest_run_id,
            )
            for source in freshness.sources
        ],
        tables=[
            TableEntry(
                **dict(table),
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
