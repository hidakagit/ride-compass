"""緯度経度からJMA指定河川洪水予報バッジ向けの情報を組み立てるサービス。"""

from __future__ import annotations

import httpx
from cachetools import TTLCache

from app.domain.flood_forecast import ActiveFloodForecast, extract_active_flood_forecast
from app.domain.jma_area import resolve_area
from app.domain.route import Coordinates
from app.infrastructure.flood_client import fetch_flood_documents
from app.infrastructure.jma_area_boundaries import AreaBoundariesUnavailableError, find_class20_code
from app.infrastructure.jma_warning_client import fetch_area_data
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
        try:
            class20_code = await find_class20_code(point.latitude, point.longitude)
        except AreaBoundariesUnavailableError:
            return None
        if class20_code is None:
            return FloodForecasts(forecasts=[])

        area_master = await fetch_area_data(self._http_client, self._area_data_cache)
        if area_master is None:
            return None

        resolved = resolve_area(class20_code, area_master)
        if resolved is None:
            return None

        bulletins = await fetch_flood_documents(self._http_client, self._flood_cache)
        if bulletins is None:
            return None

        forecasts: list[ActiveFloodForecast] = []
        for bulletin in bulletins:
            forecast = extract_active_flood_forecast(bulletin, resolved.class20_code, resolved.class10_code)
            if forecast is not None:
                forecasts.append(forecast)
        return FloodForecasts(forecasts=forecasts)
