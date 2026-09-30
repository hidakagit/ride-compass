"""材料ごとの欠損割合レポートを組み立てるサービス層。

レポートの型は`GET /api/admin/material-catalog/coverage`の応答の型を兼ねる。
"""

import logging
import time
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import Field

from app.domain.material_catalog import MATERIAL_CATALOG, MaterialDType, MissingSemantics, Population
from app.domain.strict_model import StrictModel
from app.infrastructure.debug_log import log_external_call
from app.infrastructure.material_coverage import (
    MATERIAL_COVERAGE_EXCLUSIONS,
    MATERIAL_COVERAGE_SPECS,
    MaterialCoverageCounts,
    MaterialCoverageQuery,
)

logger = logging.getLogger("ridecompass.material_coverage")


class MaterialCoverageCounted(StrictModel):
    kind: Literal["counted"] = "counted"
    material_id: str
    label: str
    dtype: MaterialDType
    population: Population
    total: int
    missing: int
    # 0〜1（total=0の場合はNone）。
    missing_ratio: float | None
    # 欠損判定の根拠（どのテーブル・列・タグの不在を欠損とみなすか）。
    source: str
    missing_semantics: MissingSemantics


class MaterialCoverageExcluded(StrictModel):
    kind: Literal["excluded"] = "excluded"
    material_id: str
    label: str
    dtype: MaterialDType
    excluded_reason: str


# 材料1つぶん。件数と欠損の扱いは集計した材料だけが、理由は集計対象外の材料だけが持つ。
MaterialCoverageEntry = Annotated[MaterialCoverageCounted | MaterialCoverageExcluded, Field(discriminator="kind")]


class MaterialCoverageReport(StrictModel):
    computed_at: datetime
    way_total: int
    edge_total: int
    materials: list[MaterialCoverageEntry]


def build_material_coverage_report(counts: MaterialCoverageCounts, computed_at: datetime) -> MaterialCoverageReport:
    """カタログの登録順のまま1材料1行にする。

    集計対象・対象外のどちらの宣言にも無い材料は`ValueError`。材料を足して宣言を書き
    忘れたことを、黙った空行にしない。
    """
    entries: list[MaterialCoverageEntry] = []
    for material_id, spec in MATERIAL_CATALOG.items():
        coverage = MATERIAL_COVERAGE_SPECS.get(material_id)
        if coverage is not None:
            total = counts.way_total if coverage.population == "way" else counts.edge_total
            missing = counts.missing_by_material[material_id]
            entries.append(
                MaterialCoverageCounted(
                    material_id=material_id,
                    label=spec.full_label(),
                    dtype=spec.dtype,
                    population=coverage.population,
                    total=total,
                    missing=missing,
                    missing_ratio=(missing / total) if total > 0 else None,
                    source=coverage.source,
                    missing_semantics=coverage.missing_semantics,
                )
            )
            continue
        excluded_reason = MATERIAL_COVERAGE_EXCLUSIONS.get(material_id)
        if excluded_reason is None:
            raise ValueError(
                f"材料 '{material_id}' はMATERIAL_COVERAGE_SPECS/MATERIAL_COVERAGE_EXCLUSIONSのどちらにも未登録"
            )
        entries.append(
            MaterialCoverageExcluded(
                material_id=material_id, label=spec.full_label(), dtype=spec.dtype, excluded_reason=excluded_reason
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
