"""材料ごとの欠損割合レポートを組み立てるサービス層。

`infrastructure/material_coverage.py`（集計クエリ・材料id→判定式の宣言テーブル）の生の
件数と、`domain/material_catalog.py: MATERIAL_CATALOG`（表示名・dtype）を突き合わせ、
管理画面がそのまま表示できる1材料1行のレポートにする。組み立て自体は純関数
（`build_material_coverage_report`）でDBに依存しない。
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.material_catalog import MATERIAL_CATALOG, MaterialDType
from app.infrastructure.debug_log import log_external_call
from app.infrastructure.material_coverage import (
    MATERIAL_COVERAGE_EXCLUSIONS,
    MATERIAL_COVERAGE_SPECS,
    MaterialCoverageCounts,
    MaterialCoverageQuery,
    MissingSemantics,
    Population,
)

logger = logging.getLogger("ridecompass.material_coverage")


@dataclass(frozen=True)
class MaterialCoverageEntry:
    material_id: str
    label: str
    dtype: MaterialDType
    # 集計対象外の材料は population/total/missing/missing_ratio/missing_semantics がNoneで
    # excluded_reason が理由を持つ。
    population: Population | None
    total: int | None
    missing: int | None
    missing_ratio: float | None
    source: str
    missing_semantics: MissingSemantics | None
    excluded_reason: str | None


@dataclass(frozen=True)
class MaterialCoverageReport:
    computed_at: datetime
    way_total: int
    edge_total: int
    materials: list[MaterialCoverageEntry]


def build_material_coverage_report(counts: MaterialCoverageCounts, computed_at: datetime) -> MaterialCoverageReport:
    """`MATERIAL_CATALOG`の全材料を、カタログの登録順のまま1行ずつレポートへ載せる。
    集計対象・対象外のどちらにも無い材料は`ValueError`（宣言テーブルの追加漏れを
    黙って空行にしない）。"""
    entries: list[MaterialCoverageEntry] = []
    for material_id, spec in MATERIAL_CATALOG.items():
        coverage = MATERIAL_COVERAGE_SPECS.get(material_id)
        if coverage is not None:
            total = counts.way_total if coverage.population == "way" else counts.edge_total
            missing = counts.missing_by_material[material_id]
            entries.append(
                MaterialCoverageEntry(
                    material_id=material_id,
                    label=spec.full_label(),
                    dtype=spec.dtype,
                    population=coverage.population,
                    total=total,
                    missing=missing,
                    missing_ratio=(missing / total) if total > 0 else None,
                    source=coverage.source,
                    missing_semantics=coverage.missing_semantics,
                    excluded_reason=None,
                )
            )
            continue
        excluded_reason = MATERIAL_COVERAGE_EXCLUSIONS.get(material_id)
        if excluded_reason is None:
            raise ValueError(
                f"材料 '{material_id}' はMATERIAL_COVERAGE_SPECS/MATERIAL_COVERAGE_EXCLUSIONSのどちらにも未登録"
            )
        entries.append(
            MaterialCoverageEntry(
                material_id=material_id,
                label=spec.full_label(),
                dtype=spec.dtype,
                population=None,
                total=None,
                missing=None,
                missing_ratio=None,
                source="",
                missing_semantics=None,
                excluded_reason=excluded_reason,
            )
        )
    return MaterialCoverageReport(
        computed_at=computed_at, way_total=counts.way_total, edge_total=counts.edge_total, materials=entries
    )


class MaterialCoverageService:
    def __init__(self, repository: MaterialCoverageQuery):
        self._repository = repository

    async def get_material_coverage(self) -> MaterialCoverageReport:
        """DB例外は呼び出し元（router）へそのまま伝播させる。管理者向けの診断APIのため、
        空のレポートへ倒して「欠損0件」に見せるより失敗を明示する方が安全。"""
        started = time.monotonic()
        with log_external_call("material-coverage") as fields:
            counts = await self._repository.get_material_coverage_counts()
            fields["way_total"] = counts.way_total
            fields["edge_total"] = counts.edge_total
        report = build_material_coverage_report(counts, datetime.now(timezone.utc))
        logger.info(
            "material coverage computed way_total=%d edge_total=%d materials=%d elapsed_ms=%d",
            counts.way_total, counts.edge_total, len(report.materials), round((time.monotonic() - started) * 1000),
        )
        return report
