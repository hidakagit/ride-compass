"""`services/flood_service.py`——地点の区域に該当する、現在の指定河川洪水予報を集める。

電文は気象庁の応答の形のまま上流の代役から返し、解くクライアントとdomainの取り出しは本物を通す。

ここで見ないもの:
- 電文1件が発表中か・区域にかかるか → `test_flood_forecast_domain.py`
- 訓練・試験の電文を落とすこと → `test_flood_client.py`
- 地点から区域を引くこと → `test_jma_area_boundaries.py`
"""

import pytest

from app.infrastructure import jma_area_boundaries
from app.infrastructure.flood_client import new_flood_cache
from app.infrastructure.jma_warning_client import new_area_data_cache
from app.services.flood_service import FloodService
from tests.jma_area_fixtures import CHIYODA_POINT, CLASS10_CODE, CLASS20_CODE, OFFSHORE_POINT, area_lookup_upstream


def _service(monkeypatch, tmp_path, **kwargs) -> FloodService:
    return FloodService(
        area_lookup_upstream(monkeypatch, tmp_path, **kwargs),
        area_data_cache=new_area_data_cache(),
        flood_cache=new_flood_cache(),
    )


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


async def test_get_forecasts_collects_every_active_forecast_and_leaves_out_the_rest(monkeypatch, tmp_path):
    documents = [
        _bulletin(),
        _bulletin(
            reportDatetime="2026-08-22T17:20:00+09:00",
            item={"name": "レベル２氾濫注意報", "code": "21", "condition": "レベル２氾濫注意報"},
            riverCode="830304004900",
            riverName="善福寺川",
        ),
        _bulletin(
            item={"name": "レベル２氾濫注意報解除", "code": "10", "condition": "レベル２氾濫注意報解除"},
            riverName="妙正寺川",
        ),
    ]

    result = await _service(monkeypatch, tmp_path, flood_documents=documents).get_forecasts(CHIYODA_POINT)

    assert sorted(f.river_code for f in result.forecasts) == ["830304004400", "830304004900"]
