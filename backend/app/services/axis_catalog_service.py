"""軸カタログ（`GET /api/axis-catalog`）が、軸の宣言のほかに要る値を1回で読む。"""

from collections.abc import Iterable
from dataclasses import dataclass

from app.domain.dynamic_way_values import WayValueConditionName
from app.services.dedicated_way_values import dedicated_way_value_conditions
from app.services.region_service import RegionService


@dataclass(frozen=True)
class AxisCatalogSources:
    # 事故データの収録年（`RegionService.get_accident_years`）。
    accident_years: list[int]
    # 系統名 → 配信するタイルの世代（`RegionService.tile_versions`）。
    tile_versions: dict[str, str]
    # 軸id → 地図が専用way値配信の要求へ載せる条件の名前（`dedicated_way_value_conditions`）。
    dynamic_way_value_conditions: dict[str, list[WayValueConditionName]]


async def axis_catalog_sources(region_service: RegionService, axis_ids: Iterable[str]) -> AxisCatalogSources:
    """`axis_ids`の軸について、カタログが配る値のうちDBと配信の実装から読むもの。"""
    return AxisCatalogSources(
        accident_years=await region_service.get_accident_years(),
        tile_versions=await region_service.tile_versions(),
        dynamic_way_value_conditions={axis_id: dedicated_way_value_conditions(axis_id) for axis_id in axis_ids},
    )
