from app.domain.route import Coordinates
from app.services import warning_service
from app.services.warning_service import WarningService

CHIYODA_AREA_DATA = {
    "class20s": {"1310100": {"name": "千代田区", "parent": "130011"}},
    "class15s": {"130011": {"name": "２３区西部", "parent": "130010"}},
    "class10s": {"130010": {"name": "東京地方", "parent": "130000"}},
}

POINT = Coordinates(latitude=35.6812, longitude=139.7671)


def _patch(monkeypatch, *, muni_cd="13101", area_data=CHIYODA_AREA_DATA, documents=None):
    async def fake_muni_cd(client, lat, lon):
        return muni_cd

    async def fake_area_data(client):
        return area_data

    async def fake_documents(client, office_code):
        return documents

    monkeypatch.setattr(warning_service, "fetch_municipality_code", fake_muni_cd)
    monkeypatch.setattr(warning_service, "fetch_area_data", fake_area_data)
    monkeypatch.setattr(warning_service, "fetch_warning_documents", fake_documents)


async def test_get_warnings_returns_empty_when_municipality_code_lookup_fails(monkeypatch):
    _patch(monkeypatch, muni_cd=None)
    result = await WarningService(http_client=None).get_warnings(POINT)
    assert result.warnings == []
    assert result.area_name is None


async def test_get_warnings_returns_empty_when_area_data_fetch_fails(monkeypatch):
    _patch(monkeypatch, area_data=None)
    result = await WarningService(http_client=None).get_warnings(POINT)
    assert result.warnings == []


async def test_get_warnings_returns_empty_when_area_resolution_fails(monkeypatch):
    _patch(monkeypatch, muni_cd="99999")
    result = await WarningService(http_client=None).get_warnings(POINT)
    assert result.warnings == []


async def test_get_warnings_returns_empty_when_warning_documents_fetch_fails(monkeypatch):
    _patch(monkeypatch, documents=None)
    result = await WarningService(http_client=None).get_warnings(POINT)
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

    result = await WarningService(http_client=None).get_warnings(POINT)

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

    result = await WarningService(http_client=None).get_warnings(POINT)

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

    result = await WarningService(http_client=None).get_warnings(POINT)

    assert result.warnings == []
    assert result.area_name is None
    assert result.report_datetime is None
