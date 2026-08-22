from datetime import datetime

from app.domain.route import Coordinates
from app.domain.wbgt_points import WbgtPoint
from app.services import wbgt_service
from app.services.wbgt_service import WbgtService

POINT = Coordinates(latitude=35.6812, longitude=139.7671)
TOKYO_POINT = WbgtPoint(no="44132", name="東京", latitude=35.6917, longitude=139.75)
SUMMER_NOW = datetime(2026, 8, 22, 15, 0, 0)
WINTER_NOW = datetime(2026, 1, 15, 12, 0, 0)


def _patch(monkeypatch, *, point_master=(TOKYO_POINT,), forecast=None):
    async def fake_point_master(client):
        return list(point_master) if point_master is not None else None

    async def fake_forecast(client, wbgt_no, range_from, range_to):
        return forecast

    monkeypatch.setattr(wbgt_service, "fetch_point_master", fake_point_master)
    monkeypatch.setattr(wbgt_service, "fetch_forecast", fake_forecast)


async def test_get_status_returns_empty_outside_provision_period(monkeypatch):
    calls = []

    async def fail_if_called(*args, **kwargs):
        calls.append(args)
        raise AssertionError("提供期間外はfetch_point_masterを呼んではならない")

    monkeypatch.setattr(wbgt_service, "fetch_point_master", fail_if_called)

    result = await WbgtService(http_client=None).get_status(POINT, now=WINTER_NOW)

    assert result.level is None
    assert calls == []


async def test_get_status_returns_empty_when_point_master_fetch_fails(monkeypatch):
    _patch(monkeypatch, point_master=None)
    result = await WbgtService(http_client=None).get_status(POINT, now=SUMMER_NOW)
    assert result.level is None


async def test_get_status_returns_empty_when_no_points_available(monkeypatch):
    _patch(monkeypatch, point_master=())
    result = await WbgtService(http_client=None).get_status(POINT, now=SUMMER_NOW)
    assert result.level is None


async def test_get_status_returns_empty_when_forecast_fetch_fails(monkeypatch):
    _patch(monkeypatch, forecast=None)
    result = await WbgtService(http_client=None).get_status(POINT, now=SUMMER_NOW)
    assert result.level is None


async def test_get_status_returns_empty_when_below_almost_safe_threshold(monkeypatch):
    forecast = [
        {"reference_time": "2026/08/22 14:00:00", "forecast_time": "2026/08/22 15:00:00", "forecast_val": "150"},
    ]  # 15.0、21未満
    _patch(monkeypatch, forecast=forecast)
    result = await WbgtService(http_client=None).get_status(POINT, now=SUMMER_NOW)
    assert result.level is None
    assert result.value is None


async def test_get_status_picks_the_forecast_entry_nearest_to_now(monkeypatch):
    forecast = [
        {"reference_time": "2026/08/22 14:00:00", "forecast_time": "2026/08/22 15:00:00", "forecast_val": "250"},
        {"reference_time": "2026/08/22 14:00:00", "forecast_time": "2026/08/22 18:00:00", "forecast_val": "300"},
        {"reference_time": "2026/08/22 14:00:00", "forecast_time": "2026/08/22 21:00:00", "forecast_val": "220"},
    ]
    _patch(monkeypatch, forecast=forecast)
    now = datetime(2026, 8, 22, 17, 30, 0)  # 18:00に最も近い

    result = await WbgtService(http_client=None).get_status(POINT, now=now)

    assert result.level == "severe_warning"
    assert result.label == "厳重警戒"
    assert result.value == 30.0
    assert result.observed_at == "2026/08/22 18:00:00"


async def test_get_status_uses_only_the_latest_reference_time_when_multiple_are_present(monkeypatch):
    # range_date_from/range_date_toで検索窓を広げると複数の発表回（reference_time）が
    # 混在しうる。古い発表回（14時、まだ21未満=ほぼ安全だった頃）を無視し、最新の発表回
    # （15時、既に25.0=警戒に上がった）だけを使うことを確認する。
    forecast = [
        {"reference_time": "2026/08/22 14:00:00", "forecast_time": "2026/08/22 15:00:00", "forecast_val": "150"},
        {"reference_time": "2026/08/22 15:00:00", "forecast_time": "2026/08/22 15:00:00", "forecast_val": "250"},
    ]
    _patch(monkeypatch, forecast=forecast)
    now = datetime(2026, 8, 22, 15, 0, 0)

    result = await WbgtService(http_client=None).get_status(POINT, now=now)

    assert result.level == "warning"
    assert result.value == 25.0
