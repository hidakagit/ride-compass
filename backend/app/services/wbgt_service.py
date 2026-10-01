"""緯度経度から暑さ指数（WBGT）警告バッジ向けの情報を組み立てるサービス。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx
import numpy as np

from app.domain.warning_levels import WarningBadgeLevel
from app.domain.route import Coordinates
from app.domain.geo import nearest_point_index
from app.domain.wbgt import current_forecast, is_within_provision_period, wbgt_level
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
    #: 警告として出す段の値。提供期間外と、警告として意味を持たない低いレベルのときはNone。
    reading: WbgtReading | None


def _empty_status() -> WbgtStatus:
    return WbgtStatus(reading=None)


class WbgtService:
    def __init__(self, http_client: httpx.AsyncClient):
        self._http_client = http_client

    async def get_status(self, point: Coordinates, now: datetime) -> WbgtStatus | None:
        """出発地点の`now`（JST）時点の暑さ指数警戒レベルを取得する。

        空（段なし）を返すのは、提供期間外（取得自体を行わない）と、警告として意味を持たない低い
        レベルのときだけ。地点解決・予測値の取得に失敗したか、提供期間の中で今の時刻の値が
        得られなければNone（警戒レベルが分からない）。
        """
        if not is_within_provision_period(now):
            return _empty_status()

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
        if not forecasts:
            # 提供期間の中で発表が無いのは配信の止まりで、段なしにすると警戒が要らないと見せる。
            logger.warning(
                "暑さ指数の検索窓に発表がありません wbgt_no=%s range_from=%s range_to=%s",
                nearest.no, range_from.isoformat(), now.isoformat(),
            )
            return None

        forecast = current_forecast(forecasts, now)
        if forecast is None or forecast.wbgt is None:
            return None

        level_info = wbgt_level(forecast.wbgt)
        if level_info is None:
            return _empty_status()
        level, label = level_info
        return WbgtStatus(
            reading=WbgtReading(level=level, label=label, value=forecast.wbgt, observed_at=forecast.forecast_time_text)
        )
