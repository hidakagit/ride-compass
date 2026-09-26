"""緯度経度から暑さ指数（WBGT）警告バッジ向けの情報を組み立てるサービス。"""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx

from app.domain.warning_levels import WarningBadgeLevel
from app.domain.route import Coordinates
from app.domain.wbgt import is_within_provision_period, wbgt_level
from app.domain.wbgt_points import nearest_point
from app.infrastructure.wbgt_client import WbgtForecast, fetch_forecast, fetch_point_master
from app.domain.strict_model import StrictModel

# 発表（reference_time）は概ね毎時だが遅延もありうるため、直近この時間幅で発表時刻を
# 検索する（1〜2時間の遅延は起こりうる前提で余裕を持たせる）。
_FORECAST_SEARCH_WINDOW_HOURS = 6


class WbgtStatus(StrictModel):
    level: WarningBadgeLevel | None
    label: str | None
    value: float | None
    observed_at: str | None


def _empty_status() -> WbgtStatus:
    return WbgtStatus(level=None, label=None, value=None, observed_at=None)


class WbgtService:
    def __init__(self, http_client: httpx.AsyncClient):
        self._http_client = http_client

    async def get_status(self, point: Coordinates, now: datetime) -> WbgtStatus:
        """出発地点の`now`（JST）時点の暑さ指数警戒レベルを取得する。

        提供期間外は取得自体を行わない。地点解決・予測値取得のどこで失敗しても例外にせず
        空を返す（他の警報系バッジと共有するfail-open方針）。警告として意味を持たない低い
        レベルも空へ倒す。
        """
        if not is_within_provision_period(now):
            return _empty_status()

        points = await fetch_point_master(self._http_client)
        if not points:
            return _empty_status()

        nearest = nearest_point(point.latitude, point.longitude, points)
        if nearest is None:
            return _empty_status()

        range_to = now.strftime("%Y%m%d%H%M%S")
        range_from = (now - timedelta(hours=_FORECAST_SEARCH_WINDOW_HOURS)).strftime("%Y%m%d%H%M%S")
        forecasts = await fetch_forecast(self._http_client, nearest.no, range_from, range_to)
        if not forecasts:
            return _empty_status()

        forecast = _pick_nearest_forecast(forecasts, now)
        if forecast is None or forecast.wbgt is None:
            return _empty_status()

        level_info = wbgt_level(forecast.wbgt)
        if level_info is None:
            return _empty_status()
        level, label = level_info
        return WbgtStatus(level=level, label=label, value=forecast.wbgt, observed_at=forecast.forecast_time_text)


def _pick_nearest_forecast(forecasts: list[WbgtForecast], now: datetime) -> WbgtForecast | None:
    """最新の発表回に絞ったうえで、現在時刻に最も近い対象時刻の予測を選ぶ。

    検索窓を広げて取得したレスポンスには発表回（reference_time）が複数混ざる。絞らずに
    「現在時刻に最も近い」を選ぶと、新しい発表回で既に置き換わっている値を拾いうる。
    """
    if not forecasts:
        return None
    latest_reference_time = max(forecast.reference_time for forecast in forecasts)

    now_naive = now.replace(tzinfo=None)
    best: WbgtForecast | None = None
    best_diff: float | None = None
    for forecast in forecasts:
        if forecast.reference_time != latest_reference_time or forecast.forecast_time is None:
            continue
        diff = abs((forecast.forecast_time - now_naive).total_seconds())
        if best_diff is None or diff < best_diff:
            best, best_diff = forecast, diff
    return best
