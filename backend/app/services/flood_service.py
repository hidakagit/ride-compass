"""緯度経度からJMA指定河川洪水予報バッジ向けの情報を組み立てるサービス。"""

from __future__ import annotations

import httpx
from cachetools import TTLCache

from app.domain.flood_forecast import ActiveFloodForecast, extract_active_flood_forecast
from app.domain.route import Coordinates
from app.infrastructure.flood_client import fetch_flood_documents
from app.infrastructure.jma_area_boundaries import OutsideAreas, resolve_point_area
from app.domain.strict_model import StrictModel


class FloodForecasts(StrictModel):
    forecasts: list[ActiveFloodForecast]


class FloodService:
    def __init__(self, http_client: httpx.AsyncClient, *, area_data_cache: TTLCache, flood_cache: TTLCache):
        self._http_client = http_client
        self._area_data_cache = area_data_cache
        self._flood_cache = flood_cache

    async def get_forecasts(self, point: Coordinates) -> FloodForecasts | None:
        """出発地点近傍の指定河川洪水予報を取得する。

        エリア解決か予報の取得に失敗したらNone（出ているかが分からない）。空は、地点がどの区域にも
        入らないときと、取れた予報にその区域のものが無いときだけ。
        """
        resolved = await resolve_point_area(self._http_client, self._area_data_cache, point.latitude, point.longitude)
        if resolved is None:
            return None
        if isinstance(resolved, OutsideAreas):
            return FloodForecasts(forecasts=[])

        bulletins = await fetch_flood_documents(self._http_client, self._flood_cache)
        if bulletins is None:
            return None

        return FloodForecasts(forecasts=[
            forecast
            for bulletin in bulletins
            if (forecast := extract_active_flood_forecast(bulletin, resolved.class20_code, resolved.class10_code))
            is not None
        ])
