"""派生データ鮮度台帳の管理API（改善計画T571）。

`GET /api/admin/derived-data/freshness`（Basic認証必須）は、`edge_attribute_counts`・
`way_attribute_counts`・`designation_attributes`について「参照している生データの世代が
最新の取込より古いままではないか」を機械判定して返す管理画面向けの集計API
（`services/derived_data_freshness_service.py`・`infrastructure/derived_data_freshness.py`）。
`elevation_attributes`は世代比較ではなく完成度（`road_edges`との行数差分）を別枠で返す
——`source_*_import_run_id`列を持たないため他3件と同じ判定はできない。

`material_catalog.py`の`GET /api/admin/material-catalog/coverage`（材料の欠損割合、
完成度）とは別の切り口——本APIは「行はあるが古い世代のままではないか」という鮮度を見る。
認可を要求する理由・DB例外の扱いは`get_material_coverage`と同じ（全表走査を伴うため
認可なしに公開しない、DB例外は503へ変換し空レポートへ倒さない）。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError

from app.api.admin_auth import require_admin_basic_auth
from app.api.dependencies import get_derived_data_freshness_service
from app.services.derived_data_freshness_service import DerivedDataFreshnessService

router = APIRouter()


class SourceFreshnessEntry(BaseModel):
    label: str
    run_table: str
    latest_available_run_id: int | None
    earliest_reflected_run_id: int | None
    null_count: int
    is_stale: bool


class AlgorithmVersionFreshnessEntry(BaseModel):
    owner: str
    current_version: str
    oldest_version: str | None
    null_count: int
    is_stale: bool


class GenerationFreshnessEntry(BaseModel):
    table_name: str
    row_count: int
    sources: list[SourceFreshnessEntry]
    algorithm_version: AlgorithmVersionFreshnessEntry | None
    is_stale: bool


class ElevationCompletenessEntry(BaseModel):
    road_edges_total: int
    uncalculated_count: int


class DerivedDataFreshnessResponse(BaseModel):
    computed_at: str
    generations: list[GenerationFreshnessEntry]
    elevation: ElevationCompletenessEntry


@router.get(
    "/api/admin/derived-data/freshness",
    response_model=DerivedDataFreshnessResponse,
    dependencies=[Depends(require_admin_basic_auth)],
)
async def get_derived_data_freshness(
    service: DerivedDataFreshnessService = Depends(get_derived_data_freshness_service),
) -> DerivedDataFreshnessResponse:
    """`edge_attribute_counts`・`way_attribute_counts`・`designation_attributes`の
    鮮度不整合（`is_stale`）と、`elevation_attributes`の完成度を返す。

    DB例外は`get_material_coverage`と同じく503へ変換する（診断用APIのため
    空レポートへ倒さない）。
    """
    try:
        report = await service.get_freshness_report()
    except DBAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="派生データ鮮度台帳の集計に失敗しました（DB接続・migration適用状況を確認してください）",
        ) from exc
    return DerivedDataFreshnessResponse(
        computed_at=report.computed_at.isoformat(),
        generations=[
            GenerationFreshnessEntry(
                table_name=entry.table_name,
                row_count=entry.row_count,
                sources=[
                    SourceFreshnessEntry(
                        label=source.label,
                        run_table=source.run_table,
                        latest_available_run_id=source.latest_available_run_id,
                        earliest_reflected_run_id=source.earliest_reflected_run_id,
                        null_count=source.null_count,
                        is_stale=source.is_stale,
                    )
                    for source in entry.sources
                ],
                algorithm_version=(
                    AlgorithmVersionFreshnessEntry(
                        owner=entry.algorithm_version.owner,
                        current_version=entry.algorithm_version.current_version,
                        oldest_version=entry.algorithm_version.oldest_version,
                        null_count=entry.algorithm_version.null_count,
                        is_stale=entry.algorithm_version.is_stale,
                    )
                    if entry.algorithm_version is not None
                    else None
                ),
                is_stale=entry.is_stale,
            )
            for entry in report.generations
        ],
        elevation=ElevationCompletenessEntry(
            road_edges_total=report.elevation.road_edges_total,
            uncalculated_count=report.elevation.uncalculated_count,
        ),
    )
