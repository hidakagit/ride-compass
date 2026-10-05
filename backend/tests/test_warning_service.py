"""`services/warning_service.py`——地点から、その区域に発表中の警報・注意報を集める。

電文は気象庁の応答の形のまま上流の代役から返し、解くクライアントとdomainの取り出しは本物を通す。

ここで見ないもの:
- 電文から地点の種別を引くこと（区域の項目を先に、無ければ二次細分区域）・種別から発表中の警報を取り出すこと
  → `test_jma_warning_domain.py`
- 電文の形を解くこと → `test_jma_warning_client.py`
- 地点から区域を引くこと → `test_jma_area_boundaries.py`
"""

import pytest

from app.infrastructure import jma_area_boundaries
from app.infrastructure.jma_warning_client import new_area_data_cache, new_warning_cache
from app.services.warning_service import WarningService
from tests.jma_area_fixtures import (
    CHIYODA_POINT,
    CLASS10_CODE,
    CLASS20_CODE,
    OFFSHORE_POINT,
    area_lookup_upstream,
)


def _service(monkeypatch, tmp_path, **kwargs) -> WarningService:
    return WarningService(
        area_lookup_upstream(monkeypatch, tmp_path, **kwargs),
        area_data_cache=new_area_data_cache(),
        warning_cache=new_warning_cache(),
    )


async def test_get_warnings_returns_empty_when_the_point_is_in_no_area(monkeypatch, tmp_path):
    result = await _service(monkeypatch, tmp_path).get_warnings(OFFSHORE_POINT)
    assert result is not None
    assert result.warnings == []


@pytest.mark.parametrize("failure", [
    {"area_data": None},
    {"class20_code": "9999900"},  # 境界が返した区域を地域マスタで辿れない
    {"warning_documents": None},
])
async def test_get_warnings_is_unknown_rather_than_empty_when_a_step_fails(monkeypatch, tmp_path, failure):
    """取れなかったことを「警報なし」と同じ空で返すと、画面は警報が出ていないと見せる。"""
    assert await _service(monkeypatch, tmp_path, **failure).get_warnings(CHIYODA_POINT) is None


async def test_get_warnings_is_unknown_when_area_boundaries_are_unreadable(monkeypatch, tmp_path):
    service = _service(monkeypatch, tmp_path, warning_documents=[])
    monkeypatch.setattr(jma_area_boundaries, "BOUNDARY_PATH", tmp_path / "missing.json")
    assert await service.get_warnings(CHIYODA_POINT) is None


async def test_get_warnings_merges_across_documents_and_dedupes(monkeypatch, tmp_path):
    """区域の項目の無い電文は、二次細分区域で引く。"""
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
            "warning": {"class10Items": [{"areaCode": CLASS10_CODE, "kinds": [{"code": "14", "status": "発表"}]}]},
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

    result = await _service(monkeypatch, tmp_path, warning_documents=documents).get_warnings(CHIYODA_POINT)

    assert sorted(w.code for w in result.warnings) == ["14", "43"]


async def test_get_warnings_returns_empty_when_no_active_cycling_relevant_codes(monkeypatch, tmp_path):
    documents = [
        {
            "reportDatetime": "2026-08-22T15:29:00+09:00",
            "warning": {"class20Items": [{"areaCode": CLASS20_CODE, "kinds": [{"status": "発表警報・注意報はなし"}]}]},
        }
    ]

    result = await _service(monkeypatch, tmp_path, warning_documents=documents).get_warnings(CHIYODA_POINT)

    assert result.warnings == []
