"""`services/wbgt_service.py`——地点の暑さ指数の警戒レベルを、最寄りの情報提供地点の予測から選ぶ。

環境省の応答は形のまま上流の代役から返し、解くクライアントは本物を通す。
"""

from datetime import datetime

from cachetools import TTLCache

from app.domain.route import Coordinates
from app.infrastructure import wbgt_client
from app.services.wbgt_service import WbgtService
from tests.fake_api_http import FakeResponse, RoutingHttpClient

POINT = Coordinates(latitude=35.6812, longitude=139.7671)
SUMMER_NOW = datetime(2026, 8, 22, 15, 0, 0)
WINTER_NOW = datetime(2026, 1, 15, 12, 0, 0)

#: 地点マスタCSVのヘッダーと東京の行（使うのは地点番号・観測所名・緯度経度（度と分）・終了日の列）。
POINT_MASTER_CSV = (
    ",,地点番号,観測所名,,,,Latitude,Latitude_3,Longitude,Longitude_4,,End Year-End Month-End Day,,,,,\n"
    ",,44132,東京,,,,35,41.5,139,45.0,,9999-99-99,,,,,\n"
)


def _forecast(reference_time, forecast_time, forecast_val):
    return {"reference_time": reference_time, "wbgt_no": 44132, "forecast_val": forecast_val,
            "forecast_time": forecast_time, "flag": 0}


def _service(monkeypatch, *, point_master=POINT_MASTER_CSV, forecast=None) -> tuple[WbgtService, RoutingHttpClient]:
    """地点マスタはCSVのまま、予測は`{"status": "success", "data": forecast}`で返す（Noneなら接続の失敗）。"""
    monkeypatch.setattr(wbgt_client, "_point_master_cache", TTLCache(maxsize=1, ttl=60))
    monkeypatch.setattr(wbgt_client, "_forecast_cache", TTLCache(maxsize=8, ttl=60))

    def route(url):
        if url == wbgt_client.WBGT_POINT_MASTER_URL:
            return None if point_master is None else FakeResponse(text=point_master)
        assert url == wbgt_client.WBGT_FORECAST_API_URL
        return None if forecast is None else FakeResponse({"status": "success", "data": forecast})

    upstream = RoutingHttpClient(route)
    return WbgtService(http_client=upstream), upstream


async def test_get_status_returns_empty_outside_provision_period(monkeypatch):
    service, upstream = _service(monkeypatch)

    result = await service.get_status(POINT, now=WINTER_NOW)

    assert result.level is None
    assert upstream.requested_urls == []


async def test_get_status_returns_empty_when_point_master_fetch_fails(monkeypatch):
    service, _ = _service(monkeypatch, point_master=None)
    result = await service.get_status(POINT, now=SUMMER_NOW)
    assert result.level is None


async def test_get_status_returns_empty_when_no_points_available(monkeypatch):
    service, _ = _service(monkeypatch, point_master=POINT_MASTER_CSV.splitlines()[0] + "\n")
    result = await service.get_status(POINT, now=SUMMER_NOW)
    assert result.level is None


async def test_get_status_returns_empty_when_forecast_fetch_fails(monkeypatch):
    service, _ = _service(monkeypatch, forecast=None)
    result = await service.get_status(POINT, now=SUMMER_NOW)
    assert result.level is None


async def test_get_status_returns_empty_when_below_almost_safe_threshold(monkeypatch):
    service, _ = _service(monkeypatch, forecast=[_forecast("2026/08/22 14:00:00", "2026/08/22 15:00:00", "150")])

    result = await service.get_status(POINT, now=SUMMER_NOW)  # 15.0、21未満

    assert result.level is None
    assert result.value is None


async def test_get_status_picks_the_forecast_entry_nearest_to_now(monkeypatch):
    forecast = [
        _forecast("2026/08/22 14:00:00", "2026/08/22 15:00:00", "250"),
        _forecast("2026/08/22 14:00:00", "2026/08/22 18:00:00", "300"),
        _forecast("2026/08/22 14:00:00", "2026/08/22 21:00:00", "220"),
    ]
    service, _ = _service(monkeypatch, forecast=forecast)
    now = datetime(2026, 8, 22, 17, 30, 0)  # 18:00に最も近い

    result = await service.get_status(POINT, now=now)

    assert result.level == "severe_warning"
    assert result.label == "厳重警戒"
    assert result.value == 30.0
    assert result.observed_at == "2026/08/22 18:00:00"


async def test_get_status_uses_only_the_latest_reference_time_when_multiple_are_present(monkeypatch):
    # range_date_from/range_date_toで検索窓を広げると複数の発表回（reference_time）が
    # 混在しうる。古い発表回（14時、まだ21未満=ほぼ安全だった頃）を無視し、最新の発表回
    # （15時、既に25.0=警戒に上がった）だけを使うことを確認する。
    forecast = [
        _forecast("2026/08/22 14:00:00", "2026/08/22 15:00:00", "150"),
        _forecast("2026/08/22 15:00:00", "2026/08/22 15:00:00", "250"),
    ]
    service, _ = _service(monkeypatch, forecast=forecast)

    result = await service.get_status(POINT, now=datetime(2026, 8, 22, 15, 0, 0))

    assert result.level == "warning"
    assert result.value == 25.0


async def test_the_nearest_forecast_without_a_value_gives_nothing_rather_than_a_farther_one(monkeypatch):
    """最も近い予測の値が読めなければ、遠い時刻の値で埋めない（別の時刻の暑さを今の暑さとして出さない）。"""
    forecast = [
        _forecast("2026/08/22 14:00:00", "2026/08/22 15:00:00", None),
        _forecast("2026/08/22 14:00:00", "2026/08/22 18:00:00", "300"),
    ]
    service, _ = _service(monkeypatch, forecast=forecast)

    result = await service.get_status(POINT, now=SUMMER_NOW)

    assert result.level is None
