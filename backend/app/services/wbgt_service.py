"""緯度経度から暑さ指数（WBGT）警告バッジ向けの情報を組み立てるサービス。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx
import numpy as np

from app.domain.warning_levels import WarningBadgeLevel
from app.domain.route import Coordinates
from app.domain.geo import nearest_point_index
from app.domain.wbgt import WbgtForecast, current_forecast, is_within_provision_period, wbgt_level
from app.infrastructure.wbgt_client import fetch_forecast, fetch_point_master
from app.domain.strict_model import StrictModel

# 発表（reference_time）は概ね毎時だが遅延もありうるため、直近この時間幅で発表時刻を
# 検索する（1〜2時間の遅延は起こりうる前提で余裕を持たせる）。
_FORECAST_SEARCH_WINDOW_HOURS = 6

logger = logging.getLogger("ridecompass.wbgt_service")


class WbgtReading(StrictModel):
    level: WarningBadgeLevel
    label: str
    value: float
    observed_at: str


class WbgtStatus(StrictModel):
    #: 警告として出す段の値。提供期間の外で値が得られないときと、警告として意味を持たない低いレベルのときはNone。
    reading: WbgtReading | None


def _empty_status() -> WbgtStatus:
    return WbgtStatus(reading=None)


class WbgtService:
    def __init__(self, http_client: httpx.AsyncClient):
        self._http_client = http_client

    async def get_status(self, point: Coordinates, now: datetime) -> WbgtStatus | None:
        """出発地点の`now`（JST）時点の暑さ指数警戒レベルを取得する。

        空（段なし）を返すのは、警告として意味を持たない低いレベルのときと、提供期間の外で今の時刻の値が
        得られない（取得の失敗も含む）ときだけ。提供期間の中で今の時刻の値が得られなければNone（警戒レベルが
        分からない）。
        """
        forecast = await self._current_forecast(point, now)
        if forecast is None or forecast.wbgt is None:
            # 提供期間の外は値が無いのが常で、失敗と出すと提供していない時期に「取得できませんでした」が出る。
            return None if is_within_provision_period(now) else _empty_status()

        level_info = wbgt_level(forecast.wbgt)
        if level_info is None:
            return _empty_status()
        level, label = level_info
        return WbgtStatus(
            reading=WbgtReading(level=level, label=label, value=forecast.wbgt, observed_at=forecast.forecast_time_text)
        )

    async def _current_forecast(self, point: Coordinates, now: datetime) -> WbgtForecast | None:
        points = await fetch_point_master(self._http_client)
        if not points:
            return None

        nearest_index = nearest_point_index(
            point.latitude, point.longitude,
            np.array([p.latitude for p in points]), np.array([p.longitude for p in points]),
        )
        if nearest_index is None:
            return None
        nearest = points[nearest_index]

        range_from = now - timedelta(hours=_FORECAST_SEARCH_WINDOW_HOURS)
        forecasts = await fetch_forecast(self._http_client, nearest.no, range_from, now)
        if forecasts is None:
            return None
        if not forecasts and is_within_provision_period(now):
            # 提供期間の中で発表が無いのは配信の止まりで、配信元の失敗ではないためクライアントは出さず、ここで出さないと未取得の理由が残らない。
            logger.warning(
                "暑さ指数の検索窓に発表がありません wbgt_no=%s range_from=%s range_to=%s",
                nearest.no, range_from.isoformat(), now.isoformat(),
            )
        return current_forecast(forecasts, now)
