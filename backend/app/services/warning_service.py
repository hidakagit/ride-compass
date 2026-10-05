"""緯度経度からJMA警報・注意報バッジ向けの情報を組み立てるサービス。"""

from __future__ import annotations

import httpx
from cachetools import TTLCache

from app.domain.jma_area import ResolvedArea, resolve_area
from app.domain.jma_warning import ActiveWarning, WarningBulletin, collect_active_warnings
from app.domain.route import Coordinates
from app.infrastructure.jma_area_boundaries import AreaBoundariesUnavailableError, find_class20_code
from app.infrastructure.jma_warning_client import fetch_area_data, fetch_warning_documents
from app.domain.strict_model import StrictModel


class WeatherWarnings(StrictModel):
    area_name: str | None
    report_datetime: str | None
    warnings: list[ActiveWarning]


class WarningService:
    def __init__(self, http_client: httpx.AsyncClient, *, area_data_cache: TTLCache, warning_cache: TTLCache):
        self._http_client = http_client
        self._area_data_cache = area_data_cache
        self._warning_cache = warning_cache

    async def get_warnings(self, point: Coordinates) -> WeatherWarnings | None:
        """出発地点の警報・注意報バッジ情報を取得する。

        地点→区域→警報エリアの解決か、警報自体の取得に失敗したらNone（出ているかが分からない）。
        「警報なし」は、地点がどの区域にも入らないときと、取れた電文がその区域に警報を持たないときだけ。
        """
        try:
            class20_code = await find_class20_code(point.latitude, point.longitude)
        except AreaBoundariesUnavailableError:
            return None
        if class20_code is None:
            return _empty_warnings()

        area_master = await fetch_area_data(self._http_client, self._area_data_cache)
        if area_master is None:
            return None

        resolved = resolve_area(class20_code, area_master)
        if resolved is None:
            return None

        bulletins = await fetch_warning_documents(self._http_client, resolved.office_code, self._warning_cache)
        if bulletins is None:
            return None

        return _build_warnings(bulletins, resolved)


def _empty_warnings() -> WeatherWarnings:
    return WeatherWarnings(area_name=None, report_datetime=None, warnings=[])


def _build_warnings(bulletins: list[WarningBulletin], resolved: ResolvedArea) -> WeatherWarnings:
    warnings, report_datetime = collect_active_warnings(bulletins, resolved.class20_code, resolved.class10_code)
    if not warnings:
        return _empty_warnings()
    return WeatherWarnings(
        area_name=resolved.class10_name,
        report_datetime=report_datetime,
        warnings=warnings,
    )
