"""`api/routers/material_catalog.py`——材料の実データの値・分布・欠損割合（軸スタジオの管理API）。

ここで見るもの: 未知の材料を404で断ること、値と分布を出せなかったことを`available`で伝えること、
値に表示名を添えること、欠損割合の集計の結果をそのまま返し、DBの失敗を503にすること。

ここで見ないもの:
- 値の表示名の形（「論理名 - 物理名」・対訳の無い値） → `test_material_catalog.py`
- 分布の計算 → `test_axis_preview_service.py`
- 欠損割合の組み立て（並び・割合・集計の対象外） → `test_material_coverage.py`
- 認可 → `test_admin_route_authorization.py`
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.api.dependencies import get_material_coverage_service, get_road_graph_repository
from app.domain.material_catalog import MATERIAL_CATALOG
from app.infrastructure.material_coverage import MATERIAL_COVERAGE_SPECS, MaterialCoverageCounts
from app.main import app
from app.domain.value_distribution import EMPTY_DISTRIBUTION, ValueDistribution
from app.services.material_coverage_service import build_material_coverage_report
from tests.admin_auth import AUTH_HEADERS

client = TestClient(app)


@pytest.fixture
def repository():
    """`get_road_graph_repository`を、テストが置いた値へ差し替える。"""

    def _set(value):
        app.dependency_overrides[get_road_graph_repository] = lambda: value

    yield _set
    app.dependency_overrides.clear()


@pytest.mark.parametrize("kind", ["values", "distribution"])
def test_an_unknown_material_is_404(admin_credentials, kind):
    response = client.get(f"/api/admin/material-catalog/not_a_real_material/{kind}", headers=AUTH_HEADERS)

    assert response.status_code == 404


# --- 材料の実データ値一覧 ---


class FakeRepositoryForMaterialValues:
    """DBの代役。材料の値の一覧（`SELECT DISTINCT`）だけを答え、`error`を渡すとDB障害として送出する。"""

    def __init__(self, values: list[str] | None = None, error: Exception | None = None):
        self._values = values or []
        self._error = error

    async def get_distinct_material_values(self, material_id: str) -> list[str]:
        if self._error is not None:
            raise self._error
        return self._values


def values_url(material_id: str) -> str:
    return f"/api/admin/material-catalog/{material_id}/values"


def test_get_material_values_returns_each_value_with_its_label(admin_credentials, repository):
    repository(FakeRepositoryForMaterialValues(values=["cycleway"]))

    response = client.get(values_url("highway"), headers=AUTH_HEADERS)

    assert response.json() == {
        "available": True,
        "values": [{"value": "cycleway", "label": MATERIAL_CATALOG["highway"].value_label("cycleway")}],
    }


def test_get_material_values_the_db_could_not_read_is_unavailable(admin_credentials, repository):
    repository(FakeRepositoryForMaterialValues(error=ConnectionRefusedError("db down")))

    response = client.get(values_url("smoothness"), headers=AUTH_HEADERS)

    assert response.status_code == 200
    # 出せなかったのは「候補を出せなかった」——「値が無い」と同じ形にしない。
    assert response.json() == {"available": False, "values": []}


# --- 材料の値の分布 ---


@pytest.mark.parametrize(
    ("result", "available"),
    [
        (ValueDistribution(sample_ways=3, total_km=1.2, quantiles={"p50": 10.0}, bins=[(0.0, 1.0, 1.0)], zero_share=0.0), True),
        (None, False),
    ],
    ids=["分布がある", "数値の材料でない"],
)
def test_material_distribution_answers_the_distribution_or_that_there_is_none(
    admin_credentials, monkeypatch, repository, result, available
):
    repository(object())

    async def _distribution(repository, material_id):
        return result

    monkeypatch.setattr("app.api.routers.material_catalog.material_value_distribution", _distribution)

    response = client.get("/api/admin/material-catalog/surface/distribution", headers=AUTH_HEADERS)

    assert response.json() == {"available": available, **(result or EMPTY_DISTRIBUTION).model_dump(mode="json")}


# --- 材料ごとの欠損割合 ---


COVERAGE_URL = "/api/admin/material-catalog/coverage"


class FakeMaterialCoverageService:
    def __init__(self, error: Exception | None = None):
        self._error = error

    async def get_material_coverage(self):
        if self._error is not None:
            raise self._error
        return REPORT


REPORT = build_material_coverage_report(
    MaterialCoverageCounts(
        way_total=200, edge_total=40, missing_by_material={material_id: 0 for material_id in MATERIAL_COVERAGE_SPECS}
    ),
    datetime(2026, 9, 4, tzinfo=timezone.utc),
)


def test_get_material_coverage_returns_the_report(admin_credentials):
    app.dependency_overrides[get_material_coverage_service] = lambda: FakeMaterialCoverageService()
    try:
        response = client.get(COVERAGE_URL, headers=AUTH_HEADERS)
    finally:
        app.dependency_overrides.clear()

    assert response.json() == REPORT.model_dump(mode="json")


def test_get_material_coverage_translates_db_errors_to_503(admin_credentials):
    db_error = DBAPIError("SELECT 1", {}, Exception("connection refused"))
    app.dependency_overrides[get_material_coverage_service] = lambda: FakeMaterialCoverageService(error=db_error)
    try:
        response = client.get(COVERAGE_URL, headers=AUTH_HEADERS)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert "欠損割合" in response.json()["detail"]
