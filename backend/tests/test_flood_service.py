from app.services import flood_service
from app.services.flood_service import FloodService
from tests.jma_area_fixtures import CHIYODA_POINT, patch_area_lookup


def _patch(monkeypatch, **kwargs):
    patch_area_lookup(monkeypatch, flood_service, "fetch_flood_documents", **kwargs)


async def test_get_forecasts_returns_empty_when_municipality_code_lookup_fails(monkeypatch):
    _patch(monkeypatch, muni_cd=None)
    result = await FloodService(http_client=None).get_forecasts(CHIYODA_POINT)
    assert result.forecasts == []


async def test_get_forecasts_returns_empty_when_area_data_fetch_fails(monkeypatch):
    _patch(monkeypatch, area_data=None)
    result = await FloodService(http_client=None).get_forecasts(CHIYODA_POINT)
    assert result.forecasts == []


async def test_get_forecasts_returns_empty_when_area_resolution_fails(monkeypatch):
    _patch(monkeypatch, muni_cd="99999")
    result = await FloodService(http_client=None).get_forecasts(CHIYODA_POINT)
    assert result.forecasts == []


async def test_get_forecasts_returns_empty_when_flood_documents_fetch_fails(monkeypatch):
    _patch(monkeypatch, documents=None)
    result = await FloodService(http_client=None).get_forecasts(CHIYODA_POINT)
    assert result.forecasts == []


async def test_get_forecasts_returns_matching_active_forecast(monkeypatch):
    documents = [
        {
            "status": "通常",
            "reportDatetime": "2026-08-22T17:50:00+09:00",
            "item": {"name": "レベル４氾濫危険警報", "code": "40", "condition": "レベル４氾濫危険警報（発表）"},
            "riverCode": "830304004400",
            "riverName": "神田川",
            "class20Codes": ["1310100"],
            "class10Codes": ["130010"],
        }
    ]
    _patch(monkeypatch, documents=documents)

    result = await FloodService(http_client=None).get_forecasts(CHIYODA_POINT)

    assert len(result.forecasts) == 1
    assert result.forecasts[0].river_name == "神田川"
    assert result.forecasts[0].badge_level == "severe_warning"


async def test_get_forecasts_ignores_cleared_and_non_matching_and_test_operation_entries(monkeypatch):
    documents = [
        # 解除済み（対象外）
        {
            "status": "通常",
            "reportDatetime": "2026-08-22T20:30:00+09:00",
            "item": {"name": "レベル２氾濫注意報解除", "code": "10", "condition": "レベル２氾濫注意報解除"},
            "riverCode": "830304004900",
            "riverName": "善福寺川",
            "class20Codes": ["1310100"],
            "class10Codes": ["130010"],
        },
        # 対象エリア外（対象外）
        {
            "status": "通常",
            "reportDatetime": "2026-08-22T17:50:00+09:00",
            "item": {"name": "レベル４氾濫危険警報", "code": "40", "condition": "レベル４氾濫危険警報（発表）"},
            "riverCode": "999999",
            "riverName": "無関係川",
            "class20Codes": ["9999999"],
            "class10Codes": ["999999"],
        },
        # 訓練電文（対象外）
        {
            "status": "訓練",
            "reportDatetime": "2026-08-22T17:50:00+09:00",
            "item": {"name": "レベル４氾濫危険警報", "code": "40", "condition": "レベル４氾濫危険警報（発表）"},
            "riverCode": "830304004400",
            "riverName": "神田川",
            "class20Codes": ["1310100"],
            "class10Codes": ["130010"],
        },
    ]
    _patch(monkeypatch, documents=documents)

    result = await FloodService(http_client=None).get_forecasts(CHIYODA_POINT)

    assert result.forecasts == []


async def test_get_forecasts_returns_multiple_rivers_when_both_match(monkeypatch):
    documents = [
        {
            "status": "通常",
            "reportDatetime": "2026-08-22T17:50:00+09:00",
            "item": {"name": "レベル４氾濫危険警報", "code": "40", "condition": "レベル４氾濫危険警報（発表）"},
            "riverCode": "830304004400",
            "riverName": "神田川",
            "class20Codes": ["1310100"],
            "class10Codes": ["130010"],
        },
        {
            "status": "通常",
            "reportDatetime": "2026-08-22T17:20:00+09:00",
            "item": {"name": "レベル２氾濫注意報", "code": "21", "condition": "レベル２氾濫注意報"},
            "riverCode": "830304004900",
            "riverName": "善福寺川",
            "class20Codes": ["1310100"],
            "class10Codes": ["130010"],
        },
    ]
    _patch(monkeypatch, documents=documents)

    result = await FloodService(http_client=None).get_forecasts(CHIYODA_POINT)

    river_names = sorted(f.river_name for f in result.forecasts)
    assert river_names == ["善福寺川", "神田川"]
