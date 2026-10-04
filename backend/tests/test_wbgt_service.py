"""`services/wbgt_service.py`——地点の暑さ指数の警戒レベルを、最寄りの情報提供地点の予測から選ぶ。

環境省の応答は形のまま上流の代役から返し、解くクライアントは本物を通す。
"""

from datetime import datetime

import httpx
import pytest
import respx
from cachetools import TTLCache

from app.domain.route import Coordinates
from app.infrastructure import wbgt_client
from app.services.wbgt_service import WbgtService
from tests.fake_http import client_for

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


def _service(monkeypatch, *, point_master=POINT_MASTER_CSV, forecast=None) -> tuple[WbgtService, respx.Router]:
    """地点マスタはCSVのまま、予測は`{"status": "success", "data": forecast}`で返す（Noneなら接続の失敗）。"""
    monkeypatch.setattr(wbgt_client, "_point_master_cache", TTLCache(maxsize=1, ttl=60))
    monkeypatch.setattr(wbgt_client, "_forecast_cache", TTLCache(maxsize=8, ttl=60))

    upstream = respx.Router()
    master = upstream.get(wbgt_client.WBGT_POINT_MASTER_URL)
    if point_master is None:
        master.mock(side_effect=httpx.ConnectError)
    else:
        master.respond(text=point_master)
    forecasts = upstream.get(wbgt_client.WBGT_FORECAST_API_URL)
    if forecast is None:
        forecasts.mock(side_effect=httpx.ConnectError)
    else:
        forecasts.respond(json={"status": "success", "data": forecast})
    return WbgtService(http_client=client_for(upstream)), upstream


async def test_a_value_outside_the_provision_period_is_shown(monkeypatch):
    """配信元は発表の期間の外でも値を返す年があり、その日の段を隠さない。"""
    service, _ = _service(monkeypatch, forecast=[_forecast("2026/10/28 08:00:00", "2026/10/28 09:00:00", "230")])

    result = await service.get_status(POINT, now=datetime(2026, 10, 28, 9, 0, 0))

    assert result is not None and result.reading is not None
    assert result.reading.level == "advisory"


@pytest.mark.parametrize("failure", [
    {"point_master": None},
    {"point_master": POINT_MASTER_CSV.splitlines()[0] + "\n"},  # 運用中の地点が1つも読めない
    {"forecast": None},
    {"forecast": []},  # 検索窓に発表が無い
])
@pytest.mark.parametrize(("now", "within_period"), [(SUMMER_NOW, True), (WINTER_NOW, False)])
async def test_without_a_current_value_only_inside_the_period_is_unknown(monkeypatch, failure, now, within_period):
    """期間の中で取れなかったことを段なしで返すと、画面は警戒が要らないと見せる。期間の外は値が無いのが常で、
    失敗と出すと提供していない時期に「取得できませんでした」が出る。"""
    service, _ = _service(monkeypatch, **failure)

    result = await service.get_status(POINT, now=now)

    if within_period:
        assert result is None
    else:
        assert result is not None and result.reading is None


@pytest.mark.parametrize(("now", "logged"), [(SUMMER_NOW, True), (WINTER_NOW, False)])
async def test_no_issuance_is_logged_only_inside_the_period(monkeypatch, caplog, now, logged):
    """配信元の失敗はクライアントが出すが、発表の無い成功はここで出さないと502の理由がどこにも残らない。
    期間の外の発表の無い成功は正常で、出すと冬のあいだ出続ける。"""
    service, _ = _service(monkeypatch, forecast=[])

    with caplog.at_level("WARNING", logger="ridecompass.wbgt_service"):
        await service.get_status(POINT, now=now)

    assert any("発表がありません" in record.getMessage() for record in caplog.records) is logged


async def test_get_status_returns_empty_when_below_almost_safe_threshold(monkeypatch):
    service, _ = _service(monkeypatch, forecast=[_forecast("2026/08/22 14:00:00", "2026/08/22 15:00:00", "150")])

    result = await service.get_status(POINT, now=SUMMER_NOW)  # 15.0、21未満

    assert result is not None and result.reading is None


async def test_get_status_picks_the_forecast_entry_nearest_to_now(monkeypatch):
    forecast = [
        _forecast("2026/08/22 14:00:00", "2026/08/22 15:00:00", "250"),
        _forecast("2026/08/22 14:00:00", "2026/08/22 18:00:00", "300"),
        _forecast("2026/08/22 14:00:00", "2026/08/22 21:00:00", "220"),
    ]
    service, _ = _service(monkeypatch, forecast=forecast)
    now = datetime(2026, 8, 22, 17, 30, 0)  # 18:00に最も近い

    result = await service.get_status(POINT, now=now)

    assert result is not None and result.reading is not None
    assert result.reading.level == "severe_warning"
    assert result.reading.label == "厳重警戒"
    assert result.reading.value == 30.0
    assert result.reading.observed_at == "2026/08/22 18:00:00"


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

    assert result is not None and result.reading is not None
    assert result.reading.level == "warning"
    assert result.reading.value == 25.0


async def test_the_nearest_forecast_without_a_value_is_unknown_rather_than_a_farther_one(monkeypatch):
    """最も近い予測の値が読めなければ、遠い時刻の値で埋めない（別の時刻の暑さを今の暑さとして出さない）。"""
    forecast = [
        _forecast("2026/08/22 14:00:00", "2026/08/22 15:00:00", None),
        _forecast("2026/08/22 14:00:00", "2026/08/22 18:00:00", "300"),
    ]
    service, _ = _service(monkeypatch, forecast=forecast)

    assert await service.get_status(POINT, now=SUMMER_NOW) is None
