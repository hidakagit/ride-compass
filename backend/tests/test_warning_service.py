from app.services import warning_service
from app.services.warning_service import WarningService
from tests.jma_area_fixtures import (
    CHIYODA_POINT,
    CLASS10_CODE,
    CLASS10_NAME,
    CLASS20_CODE,
    OFFSHORE_POINT,
    patch_area_lookup,
)


def _patch(monkeypatch, tmp_path, **kwargs):
    patch_area_lookup(monkeypatch, tmp_path, warning_service, "fetch_warning_documents", **kwargs)


async def test_get_warnings_returns_empty_when_the_point_is_in_no_area(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    result = await WarningService(http_client=None).get_warnings(OFFSHORE_POINT)
    assert result.warnings == []
    assert result.area_name is None


async def test_get_warnings_returns_empty_when_area_data_fetch_fails(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, area_data=None)
    result = await WarningService(http_client=None).get_warnings(CHIYODA_POINT)
    assert result.warnings == []


async def test_get_warnings_returns_empty_when_area_resolution_fails(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, class20_code="9999900")
    result = await WarningService(http_client=None).get_warnings(CHIYODA_POINT)
    assert result.warnings == []


async def test_get_warnings_returns_empty_when_warning_documents_fetch_fails(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path, documents=None)
    result = await WarningService(http_client=None).get_warnings(CHIYODA_POINT)
    assert result.warnings == []


async def test_get_warnings_merges_across_documents_and_dedupes(monkeypatch, tmp_path):
    documents = [
        {
            "reportDatetime": "2026-08-22T18:09:00+09:00",
            "warning": {
                "class20Items": [
                    {"areaCode": CLASS20_CODE, "kinds": [{"code": "43", "status": "継続"}]},
                ]
            },
        },
        {
            "reportDatetime": "2026-08-22T13:10:00+09:00",
            "warning": {
                "class20Items": [
                    {
                        "areaCode": CLASS20_CODE,
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
                    {"areaCode": CLASS20_CODE, "kinds": [{"code": "20", "status": "発表"}]},
                ]
            },
        },
    ]
    _patch(monkeypatch, tmp_path, documents=documents)

    result = await WarningService(http_client=None).get_warnings(CHIYODA_POINT)

    assert result.area_name == CLASS10_NAME
    # 最新（20時発表の電文は対象コードを含まないため寄与しない）はcode43の電文の18:09。
    assert result.report_datetime == "2026-08-22T18:09:00+09:00"
    codes = sorted(w.code for w in result.warnings)
    assert codes == ["14", "43"]


async def test_get_warnings_falls_back_to_class10_when_class20_items_absent(monkeypatch, tmp_path):
    documents = [
        {
            "reportDatetime": "2026-08-22T15:29:00+09:00",
            "warning": {
                "class10Items": [
                    {"areaCode": CLASS10_CODE, "kinds": [{"code": "16", "status": "発表", "additions": ["うねり"]}]},
                ],
                # class20Itemsキー自体が無い電文（高潮等で実機観測済みの形）。
            },
        }
    ]
    _patch(monkeypatch, tmp_path, documents=documents)

    result = await WarningService(http_client=None).get_warnings(CHIYODA_POINT)

    assert [w.code for w in result.warnings] == ["16"]
    assert result.area_name == CLASS10_NAME


async def test_get_warnings_returns_empty_when_no_active_cycling_relevant_codes(monkeypatch, tmp_path):
    documents = [
        {
            "reportDatetime": "2026-08-22T15:29:00+09:00",
            "warning": {"class20Items": [{"areaCode": CLASS20_CODE, "kinds": [{"status": "発表警報・注意報はなし"}]}]},
        }
    ]
    _patch(monkeypatch, tmp_path, documents=documents)

    result = await WarningService(http_client=None).get_warnings(CHIYODA_POINT)

    assert result.warnings == []
    assert result.area_name is None
    assert result.report_datetime is None
