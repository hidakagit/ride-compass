from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.api.dependencies import get_material_coverage_service, get_region_service
from app.domain.material_catalog import MATERIAL_CATALOG
from app.infrastructure.material_coverage import MATERIAL_COVERAGE_SPECS, MaterialCoverageCounts
from app.main import app
from app.services.material_coverage_service import build_material_coverage_report
from tests.admin_auth import AUTH_HEADERS

client = TestClient(app)


# --- 材料の実データ値一覧（改善計画T340） ---


class FakeRegionServiceForMaterialValues:
    def __init__(self, values: list[str] | None):
        self._values = values
        self.last_material_id: str | None = None

    async def get_material_values(self, material_id: str) -> list[str] | None:
        self.last_material_id = material_id
        return self._values


def values_url(material_id: str) -> str:
    return f"/api/admin/material-catalog/{material_id}/values"


def test_get_material_values_returns_sorted_distinct_values_from_service(admin_credentials):
    fake = FakeRegionServiceForMaterialValues(values=["cycleway", "primary", "residential"])
    app.dependency_overrides[get_region_service] = lambda: fake

    try:
        response = client.get(values_url("highway"), headers=AUTH_HEADERS)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    # 改善計画T345フォローアップ: 値ごとに日本語ラベルも返す
    # （MaterialSpec.value_labels、地図の絞り込みUIのグルーピングとは独立の1値1ラベル）。
    # さらなるフォローアップ2: 「論理名 - 物理名」形式。
    assert response.json() == {
        "available": True,
        "values": [
            {"value": "cycleway", "label": "自転車専用道 - cycleway"},
            {"value": "primary", "label": "主要幹線道路 - primary"},
            {"value": "residential", "label": "住宅街の道路 - residential"},
        ]
    }
    assert fake.last_material_id == "highway"


def test_get_material_values_unknown_material_id_is_404(admin_credentials):
    response = client.get(values_url("not_a_real_material"), headers=AUTH_HEADERS)

    assert response.status_code == 404


def test_get_material_values_known_material_without_dynamic_support_returns_empty_list(admin_credentials):
    # 改善計画T340: tracktypeのように事前に閉じた値集合を持つ既知の材料は404にせず、
    # available=trueの空リストを返す（フロント側は自由テキスト入力へフォールバックする）。
    fake = FakeRegionServiceForMaterialValues(values=[])
    app.dependency_overrides[get_region_service] = lambda: fake

    try:
        response = client.get(values_url("tracktype"), headers=AUTH_HEADERS)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"available": True, "values": []}
    assert fake.last_material_id == "tracktype"


def test_get_material_values_the_service_could_not_read_is_unavailable(admin_credentials):
    app.dependency_overrides[get_region_service] = lambda: FakeRegionServiceForMaterialValues(values=None)

    try:
        response = client.get(values_url("smoothness"), headers=AUTH_HEADERS)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    # 出せなかったのは「候補を出せなかった」——「値が無い」と同じ形にしない。
    assert response.json() == {"available": False, "values": []}


# --- 材料ごとの欠損割合（GET /api/admin/material-catalog/coverage、Basic認証必須） ---


COVERAGE_URL = "/api/admin/material-catalog/coverage"


class FakeMaterialCoverageService:
    def __init__(self, counts: MaterialCoverageCounts | None = None, error: Exception | None = None):
        self._counts = counts
        self._error = error

    async def get_material_coverage(self):
        if self._error is not None:
            raise self._error
        assert self._counts is not None
        return build_material_coverage_report(self._counts, datetime(2026, 9, 4, tzinfo=timezone.utc))


def _counts(**missing_overrides: int) -> MaterialCoverageCounts:
    missing = {material_id: 0 for material_id in MATERIAL_COVERAGE_SPECS}
    missing.update(missing_overrides)
    return MaterialCoverageCounts(way_total=200, edge_total=40, missing_by_material=missing)


def test_get_material_coverage_returns_all_catalog_materials(admin_credentials):
    app.dependency_overrides[get_material_coverage_service] = lambda: FakeMaterialCoverageService(
        counts=_counts(surface=170, gradient_percent=30)
    )
    try:
        response = client.get(COVERAGE_URL, headers=AUTH_HEADERS)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["way_total"] == 200
    assert body["edge_total"] == 40
    assert body["computed_at"].startswith("2026-09-04")
    assert [entry["material_id"] for entry in body["materials"]] == list(MATERIAL_CATALOG)

    by_id = {entry["material_id"]: entry for entry in body["materials"]}
    assert by_id["surface"] == {
        "material_id": "surface",
        "label": MATERIAL_CATALOG["surface"].full_label(),
        "dtype": "categorical",
        "population": "way",
        "total": 200,
        "missing": 170,
        "missing_ratio": pytest.approx(0.85),
        "source": MATERIAL_COVERAGE_SPECS["surface"].source,
        "missing_semantics": "unknown",
        "excluded_reason": None,
    }
    assert by_id["gradient_percent"]["population"] == "edge"
    assert by_id["gradient_percent"]["missing_ratio"] == pytest.approx(0.75)
    assert by_id["lit"]["missing_semantics"] == "definite"
    assert by_id["wind_drag_ratio"]["population"] is None
    assert by_id["wind_drag_ratio"]["excluded_reason"]


def test_get_material_coverage_translates_db_errors_to_503(admin_credentials):
    db_error = DBAPIError("SELECT 1", {}, Exception("connection refused"))
    app.dependency_overrides[get_material_coverage_service] = lambda: FakeMaterialCoverageService(error=db_error)
    try:
        response = client.get(COVERAGE_URL, headers=AUTH_HEADERS)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert "欠損割合" in response.json()["detail"]
