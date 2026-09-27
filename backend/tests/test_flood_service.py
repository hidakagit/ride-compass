"""`services/flood_service.py`——地点の区域に該当する、現在の指定河川洪水予報を集める。

電文は気象庁の応答の形のまま上流の代役から返し、解くクライアントとdomainの取り出しは本物を通す。
"""

import pytest

from app.infrastructure import jma_area_boundaries
from app.services.flood_service import FloodService
from tests.jma_area_fixtures import CHIYODA_POINT, CLASS10_CODE, CLASS20_CODE, OFFSHORE_POINT, area_lookup_upstream


def _service(monkeypatch, tmp_path, **kwargs) -> FloodService:
    return FloodService(http_client=area_lookup_upstream(monkeypatch, tmp_path, **kwargs))


def _bulletin(**overrides) -> dict:
    """指定河川洪水予報（flood_xml.json）の1件。項目は実際の応答の形のまま。"""
    bulletin = {
        "status": "通常",
        "reportDatetime": "2026-08-22T17:50:00+09:00",
        "item": {"name": "レベル４氾濫危険警報", "code": "40", "condition": "レベル４氾濫危険警報（発表）"},
        "riverCode": "830304004400",
        "riverName": "神田川",
        "class20Codes": [CLASS20_CODE],
        "class10Codes": [CLASS10_CODE],
    }
    bulletin.update(overrides)
    return bulletin


async def test_get_forecasts_returns_empty_when_the_point_is_in_no_area(monkeypatch, tmp_path):
    result = await _service(monkeypatch, tmp_path).get_forecasts(OFFSHORE_POINT)
    assert result.forecasts == []


@pytest.mark.parametrize("failure", [
    {"area_data": None},
    {"class20_code": "9999900"},  # 境界が返した区域を地域マスタで辿れない
    {"flood_documents": None},
])
async def test_get_forecasts_is_unknown_rather_than_empty_when_a_step_fails(monkeypatch, tmp_path, failure):
    """取れなかったことを「予報なし」と同じ空で返すと、画面は氾濫予報が出ていないと見せる。"""
    assert await _service(monkeypatch, tmp_path, **failure).get_forecasts(CHIYODA_POINT) is None


async def test_get_forecasts_is_unknown_when_area_boundaries_are_unreadable(monkeypatch, tmp_path):
    service = _service(monkeypatch, tmp_path, flood_documents=[])
    monkeypatch.setattr(jma_area_boundaries, "BOUNDARY_PATH", tmp_path / "missing.json")
    assert await service.get_forecasts(CHIYODA_POINT) is None


async def test_get_forecasts_returns_matching_active_forecast(monkeypatch, tmp_path):
    result = await _service(monkeypatch, tmp_path, flood_documents=[_bulletin()]).get_forecasts(CHIYODA_POINT)

    assert len(result.forecasts) == 1
    assert result.forecasts[0].river_name == "神田川"
    assert result.forecasts[0].badge_level == "severe_warning"
    assert result.forecasts[0].condition == "レベル４氾濫危険警報（発表）"


async def test_get_forecasts_ignores_cleared_and_non_matching_and_test_operation_entries(monkeypatch, tmp_path):
    documents = [
        # 解除済み（対象外）
        _bulletin(
            item={"name": "レベル２氾濫注意報解除", "code": "10", "condition": "レベル２氾濫注意報解除"},
            riverName="善福寺川",
        ),
        # 対象エリア外（対象外）
        _bulletin(riverName="無関係川", class20Codes=["9999999"], class10Codes=["999999"]),
        # 訓練電文（対象外）
        _bulletin(status="訓練"),
    ]

    result = await _service(monkeypatch, tmp_path, flood_documents=documents).get_forecasts(CHIYODA_POINT)

    assert result.forecasts == []


async def test_get_forecasts_returns_multiple_rivers_when_both_match(monkeypatch, tmp_path):
    documents = [
        _bulletin(),
        _bulletin(
            reportDatetime="2026-08-22T17:20:00+09:00",
            item={"name": "レベル２氾濫注意報", "code": "21", "condition": "レベル２氾濫注意報"},
            riverCode="830304004900",
            riverName="善福寺川",
        ),
    ]

    result = await _service(monkeypatch, tmp_path, flood_documents=documents).get_forecasts(CHIYODA_POINT)

    assert sorted(f.river_name for f in result.forecasts) == ["善福寺川", "神田川"]
