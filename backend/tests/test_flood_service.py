from app.services import flood_service
from app.services.flood_service import FloodService
from tests.jma_area_fixtures import CHIYODA_POINT, CLASS10_CODE, CLASS20_CODE, OFFSHORE_POINT, patch_area_lookup


def _patch(monkeypatch, tmp_path, **kwargs):
    patch_area_lookup(monkeypatch, tmp_path, flood_service, "fetch_flood_documents", **kwargs)


async def test_get_forecasts_returns_empty_when_the_point_is_in_no_area(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    result = await FloodService(http_client=None).get_forecasts(OFFSHORE_POINT)
    assert result.forecasts == []


async def test_get_forecasts_returns_empty_when_area_data_fetch_fails(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, area_data=None)
    result = await FloodService(http_client=None).get_forecasts(CHIYODA_POINT)
    assert result.forecasts == []


async def test_get_forecasts_returns_empty_when_area_resolution_fails(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, class20_code="9999900")
    result = await FloodService(http_client=None).get_forecasts(CHIYODA_POINT)
    assert result.forecasts == []


async def test_get_forecasts_returns_empty_when_flood_documents_fetch_fails(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, documents=None)
    result = await FloodService(http_client=None).get_forecasts(CHIYODA_POINT)
    assert result.forecasts == []


async def test_get_forecasts_returns_matching_active_forecast(monkeypatch, tmp_path):
    documents = [
        {
            "status": "通常",
            "reportDatetime": "2026-08-22T17:50:00+09:00",
            "item": {"name": "レベル４氾濫危険警報", "code": "40", "condition": "レベル４氾濫危険警報（発表）"},
            "riverCode": "830304004400",
            "riverName": "神田川",
            "class20Codes": [CLASS20_CODE],
            "class10Codes": [CLASS10_CODE],
        }
    ]
    _patch(monkeypatch, tmp_path, documents=documents)

    result = await FloodService(http_client=None).get_forecasts(CHIYODA_POINT)

    assert len(result.forecasts) == 1
    assert result.forecasts[0].river_name == "神田川"
    assert result.forecasts[0].badge_level == "severe_warning"


async def test_get_forecasts_ignores_cleared_and_non_matching_and_test_operation_entries(monkeypatch, tmp_path):
    documents = [
        # 解除済み（対象外）
        {
            "status": "通常",
            "reportDatetime": "2026-08-22T20:30:00+09:00",
            "item": {"name": "レベル２氾濫注意報解除", "code": "10", "condition": "レベル２氾濫注意報解除"},
            "riverCode": "830304004900",
            "riverName": "善福寺川",
            "class20Codes": [CLASS20_CODE],
            "class10Codes": [CLASS10_CODE],
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
            "class20Codes": [CLASS20_CODE],
            "class10Codes": [CLASS10_CODE],
        },
    ]
    _patch(monkeypatch, tmp_path, documents=documents)

    result = await FloodService(http_client=None).get_forecasts(CHIYODA_POINT)

    assert result.forecasts == []


async def test_get_forecasts_returns_multiple_rivers_when_both_match(monkeypatch, tmp_path):
    documents = [
        {
            "status": "通常",
            "reportDatetime": "2026-08-22T17:50:00+09:00",
            "item": {"name": "レベル４氾濫危険警報", "code": "40", "condition": "レベル４氾濫危険警報（発表）"},
            "riverCode": "830304004400",
            "riverName": "神田川",
            "class20Codes": [CLASS20_CODE],
            "class10Codes": [CLASS10_CODE],
        },
        {
            "status": "通常",
            "reportDatetime": "2026-08-22T17:20:00+09:00",
            "item": {"name": "レベル２氾濫注意報", "code": "21", "condition": "レベル２氾濫注意報"},
            "riverCode": "830304004900",
            "riverName": "善福寺川",
            "class20Codes": [CLASS20_CODE],
            "class10Codes": [CLASS10_CODE],
        },
    ]
    _patch(monkeypatch, tmp_path, documents=documents)

    result = await FloodService(http_client=None).get_forecasts(CHIYODA_POINT)

    river_names = sorted(f.river_name for f in result.forecasts)
    assert river_names == ["善福寺川", "神田川"]
