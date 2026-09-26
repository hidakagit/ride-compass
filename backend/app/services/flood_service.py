"""緯度経度からJMA指定河川洪水予報バッジ向けの情報を組み立てるサービス。"""

from __future__ import annotations

import httpx

from app.domain.flood_forecast import ActiveFloodForecast, extract_active_flood_forecast
from app.domain.jma_area import resolve_area
from app.domain.route import Coordinates
from app.infrastructure.flood_client import fetch_flood_documents
from app.infrastructure.jma_area_boundaries import find_class20_code
from app.infrastructure.jma_warning_client import fetch_area_data
from app.domain.strict_model import StrictModel


class FloodForecasts(StrictModel):
    forecasts: list[ActiveFloodForecast]


class FloodService:
    def __init__(self, http_client: httpx.AsyncClient):
        self._http_client = http_client

    async def get_forecasts(self, point: Coordinates) -> FloodForecasts:
        """出発地点近傍の指定河川洪水予報を取得する。

        エリア解決・予報取得のどこで失敗しても例外にせず空を返す（警報・WBGTと共有する
        fail-open方針）。
        """
        class20_code = await find_class20_code(point.latitude, point.longitude)
        if class20_code is None:
            return FloodForecasts(forecasts=[])

        area_data = await fetch_area_data(self._http_client)
        if area_data is None:
            return FloodForecasts(forecasts=[])

        resolved = resolve_area(class20_code, area_data)
        if resolved is None:
            return FloodForecasts(forecasts=[])

        documents = await fetch_flood_documents(self._http_client)
        if documents is None:
            return FloodForecasts(forecasts=[])

        forecasts: list[ActiveFloodForecast] = []
        for entry in documents:
            if not isinstance(entry, dict) or entry.get("status") != "通常":
                continue  # status"通常"以外は訓練・試験電文
            forecast = extract_active_flood_forecast(entry, resolved.class20_code, resolved.class10_code)
            if forecast is not None:
                forecasts.append(forecast)
        return FloodForecasts(forecasts=forecasts)
