"""派生データ鮮度台帳レポートを組み立てるサービス層。

`infrastructure/derived_data_freshness.py`（集計クエリ・テーブルごとの宣言）の生の
件数から、管理画面がそのまま表示できるテーブル1件1行のレポートを組み立てる。
組み立て自体は純関数（`build_freshness_report`）でDBに依存しない。
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from app.infrastructure.debug_log import log_external_call
from app.infrastructure.derived_data_freshness import (
    COMPLETENESS_SPECS,
    GENERATION_FRESHNESS_SPECS,
    DerivedDataFreshnessCounts,
    DerivedDataFreshnessQuery,
)

logger = logging.getLogger("ridecompass.derived_data_freshness")


@dataclass(frozen=True)
class SourceFreshnessEntry:
    label: str
    run_table: str
    latest_available_run_id: int | None
    earliest_reflected_run_id: int | None
    null_count: int
    is_stale: bool


@dataclass(frozen=True)
class AlgorithmVersionFreshnessEntry:
    owner: str
    current_version: str
    oldest_version: str | None
    null_count: int
    is_stale: bool


@dataclass(frozen=True)
class GenerationFreshnessEntry:
    table_name: str
    row_count: int
    sources: list[SourceFreshnessEntry]
    # designation_attributesはalgorithm_version比較の対象外のためNone。
    algorithm_version: AlgorithmVersionFreshnessEntry | None
    is_stale: bool


@dataclass(frozen=True)
class CompletenessEntry:
    """世代比較ではなく完成度（母集団のうち未計算の件数）。系譜列を持たない派生データは
    この形で見る（`infrastructure/derived_data_freshness.py: CompletenessSpec`）。"""

    label: str
    population: int
    uncalculated_count: int
    owner: str
    note: str
    #: 未計算の行が残っている（取込で母集団が増えたのにバッチを再実行していない可能性）。
    is_incomplete: bool


@dataclass(frozen=True)
class DerivedDataFreshnessReport:
    computed_at: datetime
    generations: list[GenerationFreshnessEntry]
    completeness: list[CompletenessEntry]


def build_freshness_report(counts: DerivedDataFreshnessCounts, computed_at: datetime) -> DerivedDataFreshnessReport:
    generations: list[GenerationFreshnessEntry] = []
    for gen_counts, spec in zip(counts.generations, GENERATION_FRESHNESS_SPECS, strict=True):
        sources: list[SourceFreshnessEntry] = []
        table_is_stale = False
        for source_spec in spec.sources:
            latest_available = gen_counts.latest_available.get(source_spec.source_column)
            earliest_reflected = gen_counts.source_min[source_spec.source_column]
            is_stale = latest_available is not None and (
                earliest_reflected is None or earliest_reflected < latest_available
            )
            table_is_stale = table_is_stale or is_stale
            sources.append(
                SourceFreshnessEntry(
                    label=source_spec.label,
                    run_table=source_spec.run_table,
                    latest_available_run_id=latest_available,
                    earliest_reflected_run_id=earliest_reflected,
                    null_count=gen_counts.source_null_count[source_spec.source_column],
                    is_stale=is_stale,
                )
            )

        algorithm_version_entry = None
        if spec.algorithm_version_current is not None:
            is_av_stale = gen_counts.row_count > 0 and (
                gen_counts.algorithm_version_min is None
                or gen_counts.algorithm_version_min != spec.algorithm_version_current
            )
            table_is_stale = table_is_stale or is_av_stale
            algorithm_version_entry = AlgorithmVersionFreshnessEntry(
                owner=spec.algorithm_version_owner,
                current_version=spec.algorithm_version_current,
                oldest_version=gen_counts.algorithm_version_min,
                null_count=gen_counts.algorithm_version_null_count,
                is_stale=is_av_stale,
            )

        generations.append(
            GenerationFreshnessEntry(
                table_name=gen_counts.table_name,
                row_count=gen_counts.row_count,
                sources=sources,
                algorithm_version=algorithm_version_entry,
                is_stale=table_is_stale,
            )
        )

    completeness = [
        CompletenessEntry(
            label=c.label,
            population=c.population,
            uncalculated_count=c.uncalculated,
            owner=spec.owner,
            note=spec.note,
            is_incomplete=c.uncalculated > 0,
        )
        for c, spec in zip(counts.completeness, COMPLETENESS_SPECS, strict=True)
    ]

    return DerivedDataFreshnessReport(
        computed_at=computed_at,
        generations=generations,
        completeness=completeness,
    )


class DerivedDataFreshnessService:
    def __init__(self, repository: DerivedDataFreshnessQuery):
        self._repository = repository

    async def get_freshness_report(self) -> DerivedDataFreshnessReport:
        """DB例外は呼び出し元（router）へそのまま伝播させる。管理者向けの診断APIのため、
        空のレポートへ倒して「鮮度不整合なし」に見せるより失敗を明示する方が安全。"""
        started = time.monotonic()
        with log_external_call("derived-data-freshness") as fields:
            counts = await self._repository.get_freshness_counts()
            fields["tables"] = len(counts.generations)
        report = build_freshness_report(counts, datetime.now(timezone.utc))
        stale_table_count = sum(1 for entry in report.generations if entry.is_stale)
        logger.info(
            "derived data freshness computed tables=%d stale_tables=%d elapsed_ms=%d",
            len(report.generations), stale_table_count, round((time.monotonic() - started) * 1000),
        )
        return report
