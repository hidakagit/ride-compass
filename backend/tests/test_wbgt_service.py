"""`services/wbgt_service.py`——地点の暑さ指数の警戒レベルを、最寄りの情報提供地点の予測から選ぶ。

環境省の応答は形のまま上流の代役から返し、解くクライアントは本物を通す。
"""

from datetime import datetime

import pytest
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


@pytest.mark.parametrize("now", [WINTER_NOW, datetime(2026, 4, 10, 12, 0, 0), datetime(2026, 10, 28, 12, 0, 0)])
async def test_get_status_returns_empty_outside_provision_period(monkeypatch, now):
    """4月・10月でも期間の外なら配信元は値を返さないので、取りに行くと「取得できませんでした」になる。"""
    service, upstream = _service(monkeypatch, forecast=[])

    result = await service.get_status(POINT, now=now)

    assert result.level is None
    assert upstream.requested_urls == []


@pytest.mark.parametrize("failure", [
    {"point_master": None},
    {"point_master": POINT_MASTER_CSV.splitlines()[0] + "\n"},  # 運用中の地点が1つも読めない
    {"forecast": None},
    {"forecast": []},  # 検索窓に発表が無い
])
async def test_get_status_is_unknown_rather_than_empty_when_no_current_value_is_obtained(monkeypatch, failure):
    """取れなかったことを段なし（「ほぼ安全」・期間外と同じ空）で返すと、画面は警戒が要らないと見せる。"""
    service, _ = _service(monkeypatch, **failure)
    assert await service.get_status(POINT, now=SUMMER_NOW) is None


async def test_no_issuance_inside_the_period_is_logged(monkeypatch, caplog):
    """配信元の失敗はクライアントが出すが、発表の無い成功はここで出さないと502の理由がどこにも残らない。"""
    service, _ = _service(monkeypatch, forecast=[])

    with caplog.at_level("WARNING", logger="ridecompass.wbgt_service"):
        await service.get_status(POINT, now=SUMMER_NOW)

    assert any("発表がありません" in record.getMessage() for record in caplog.records)


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


async def test_the_nearest_forecast_without_a_value_is_unknown_rather_than_a_farther_one(monkeypatch):
    """最も近い予測の値が読めなければ、遠い時刻の値で埋めない（別の時刻の暑さを今の暑さとして出さない）。"""
    forecast = [
        _forecast("2026/08/22 14:00:00", "2026/08/22 15:00:00", None),
        _forecast("2026/08/22 14:00:00", "2026/08/22 18:00:00", "300"),
    ]
    service, _ = _service(monkeypatch, forecast=forecast)

    assert await service.get_status(POINT, now=SUMMER_NOW) is None
