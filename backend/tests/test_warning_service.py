from app.services import warning_service
from app.services.warning_service import WarningService
from tests.jma_area_fixtures import CHIYODA_POINT, patch_area_lookup


def _patch(monkeypatch, **kwargs):
    patch_area_lookup(monkeypatch, warning_service, "fetch_warning_documents", **kwargs)


async def test_get_warnings_returns_empty_when_municipality_code_lookup_fails(monkeypatch):
    _patch(monkeypatch, muni_cd=None)
    result = await WarningService(http_client=None).get_warnings(CHIYODA_POINT)
    assert result.warnings == []
    assert result.area_name is None


async def test_get_warnings_returns_empty_when_area_data_fetch_fails(monkeypatch):
    _patch(monkeypatch, area_data=None)
    result = await WarningService(http_client=None).get_warnings(CHIYODA_POINT)
    assert result.warnings == []


async def test_get_warnings_returns_empty_when_area_resolution_fails(monkeypatch):
    _patch(monkeypatch, muni_cd="99999")
    result = await WarningService(http_client=None).get_warnings(CHIYODA_POINT)
    assert result.warnings == []


async def test_get_warnings_returns_empty_when_warning_documents_fetch_fails(monkeypatch):
    _patch(monkeypatch, documents=None)
    result = await WarningService(http_client=None).get_warnings(CHIYODA_POINT)
    assert result.warnings == []


async def test_get_warnings_merges_across_documents_and_dedupes(monkeypatch):
    documents = [
        {
            "reportDatetime": "2026-08-22T18:09:00+09:00",
            "warning": {
                "class20Items": [
                    {"areaCode": "1310100", "kinds": [{"code": "43", "status": "継続"}]},
                ]
            },
        },
        {
            "reportDatetime": "2026-08-22T13:10:00+09:00",
            "warning": {
                "class20Items": [
                    {
                        "areaCode": "1310100",
                        "kinds": [{"code": "14", "status": "発表", "additions": ["竜巻"]}],
                    },
                ]
            },
        },
        {
            # 対象コードが濃霧（対象外の種別）のみの電文。結果に含まれないこと。
            "reportDatetime": "2026-08-22T20:00:00+09:00",
            "warning": {
                "class20Items": [
                    {"areaCode": "1310100", "kinds": [{"code": "20", "status": "発表"}]},
                ]
            },
        },
    ]
    _patch(monkeypatch, documents=documents)

    result = await WarningService(http_client=None).get_warnings(CHIYODA_POINT)

    assert result.area_name == "東京地方"
    # 最新（20時発表の電文は対象コードを含まないため寄与しない）はcode43の電文の18:09。
    assert result.report_datetime == "2026-08-22T18:09:00+09:00"
    codes = sorted(w.code for w in result.warnings)
    assert codes == ["14", "43"]


async def test_get_warnings_falls_back_to_class10_when_class20_items_absent(monkeypatch):
    documents = [
        {
            "reportDatetime": "2026-08-22T15:29:00+09:00",
            "warning": {
                "class10Items": [
                    {"areaCode": "130010", "kinds": [{"code": "16", "status": "発表", "additions": ["うねり"]}]},
                ],
                # class20Itemsキー自体が無い電文（高潮等で実機観測済みの形）。
            },
        }
    ]
    _patch(monkeypatch, documents=documents)

    result = await WarningService(http_client=None).get_warnings(CHIYODA_POINT)

    assert [w.code for w in result.warnings] == ["16"]
    assert result.area_name == "東京地方"


async def test_get_warnings_returns_empty_when_no_active_cycling_relevant_codes(monkeypatch):
    documents = [
        {
            "reportDatetime": "2026-08-22T15:29:00+09:00",
            "warning": {"class20Items": [{"areaCode": "1310100", "kinds": [{"status": "発表警報・注意報はなし"}]}]},
        }
    ]
    _patch(monkeypatch, documents=documents)

    result = await WarningService(http_client=None).get_warnings(CHIYODA_POINT)

    assert result.warnings == []
    assert result.area_name is None
    assert result.report_datetime is None
