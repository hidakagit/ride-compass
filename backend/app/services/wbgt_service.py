"""緯度経度から暑さ指数（WBGT）警告バッジ向けの情報を組み立てるサービス。"""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
from pydantic import BaseModel

from app.domain.route import Coordinates
from app.domain.wbgt import is_within_provision_period, wbgt_level
from app.domain.wbgt_points import nearest_point
from app.infrastructure.wbgt_client import fetch_forecast, fetch_point_master
from app.services.route_generator import JST

# 発表（reference_time）は概ね毎時だが遅延もありうるため、直近この時間幅で発表時刻を
# 検索する（1〜2時間の遅延は起こりうる前提で余裕を持たせる）。
_FORECAST_SEARCH_WINDOW_HOURS = 6


class WbgtStatus(BaseModel):
    level: str | None
    label: str | None
    value: float | None
    observed_at: str | None


def _empty_status() -> WbgtStatus:
    return WbgtStatus(level=None, label=None, value=None, observed_at=None)


class WbgtService:
    def __init__(self, http_client: httpx.AsyncClient):
        self._http_client = http_client

    async def get_status(self, point: Coordinates, now: datetime | None = None) -> WbgtStatus:
        """出発地点の暑さ指数警戒レベルを取得する。

        提供期間外（11〜3月）は取得自体を行わずに空を返す。
        地点解決・予測値取得のどこで失敗しても例外にせず空を返す（他の警報系バッジと
        共有するfail-open方針。「ほぼ安全」（21未満）も警告として意味を持たないため空を返す）。
        """
        now = now or datetime.now(JST)
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
        data = await fetch_forecast(self._http_client, nearest.no, range_from, range_to)
        if not data:
            return _empty_status()

        entry = _pick_nearest_forecast(data, now)
        if entry is None:
            return _empty_status()

        try:
            value = float(entry["forecast_val"]) / 10.0
        except (KeyError, TypeError, ValueError):
            return _empty_status()

        level_info = wbgt_level(value)
        if level_info is None:
            return _empty_status()
        level, label = level_info
        return WbgtStatus(level=level, label=label, value=value, observed_at=entry.get("forecast_time"))


def _pick_nearest_forecast(data: list[dict], now: datetime) -> dict | None:
    """予測値列（複数の発表回=reference_timeが混在しうる）の中から、最新の発表回に
    絞った上で現在時刻に最も近いforecast_timeを選ぶ。

    range_date_from/range_date_toで検索窓を広げて取得したレスポンスには、直近数時間ぶんの
    発表回（reference_time）が複数含まれうる（例: 14時発表〜19時発表の6回分）。古い発表回の
    予測値を混ぜて「現在時刻に最も近い」を選ぶと、本来は最新の発表回で置き換わっている
    はずの値を誤って採用しうるため、まず最新のreference_timeだけに絞り込む。
    """
    latest_reference_time: str | None = None
    for entry in data:
        reference_time = entry.get("reference_time")
        if reference_time and (latest_reference_time is None or reference_time > latest_reference_time):
            latest_reference_time = reference_time
    if latest_reference_time is None:
        return None

    now_naive = now.replace(tzinfo=None)
    best: dict | None = None
    best_diff: float | None = None
    for entry in data:
        if entry.get("reference_time") != latest_reference_time:
            continue
        raw_time = entry.get("forecast_time")
        if not raw_time:
            continue
        try:
            forecast_time = datetime.strptime(raw_time, "%Y/%m/%d %H:%M:%S")
        except ValueError:
            continue
        diff = abs((forecast_time - now_naive).total_seconds())
        if best_diff is None or diff < best_diff:
            best, best_diff = entry, diff
    return best
