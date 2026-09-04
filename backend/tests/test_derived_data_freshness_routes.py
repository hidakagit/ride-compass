import base64
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.api.dependencies import get_derived_data_freshness_service
from app.config import settings
from app.infrastructure.derived_data_freshness import DerivedDataFreshnessCounts, GenerationFreshnessCounts
from app.main import app
from app.services.derived_data_freshness_service import build_freshness_report

client = TestClient(app)

FRESHNESS_URL = "/api/admin/derived-data/freshness"


def _basic_auth_header(username: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()


AUTH_HEADERS = {"Authorization": _basic_auth_header("admin-user", "secret-password")}


@pytest.fixture
def admin_credentials(monkeypatch):
    monkeypatch.setattr(settings, "admin_basic_auth_username", "admin-user")
    monkeypatch.setattr(settings, "admin_basic_auth_password", "secret-password")


class FakeDerivedDataFreshnessService:
    def __init__(self, counts: DerivedDataFreshnessCounts | None = None, error: Exception | None = None):
        self._counts = counts
        self._error = error

    async def get_freshness_report(self):
        if self._error is not None:
            raise self._error
        assert self._counts is not None
        return build_freshness_report(self._counts, datetime(2026, 9, 4, tzinfo=timezone.utc))


def _fresh_counts() -> DerivedDataFreshnessCounts:
    def _generation(table_name: str, sources: dict[str, int]) -> GenerationFreshnessCounts:
        return GenerationFreshnessCounts(
            table_name=table_name,
            row_count=5,
            source_min=sources,
            source_null_count=dict.fromkeys(sources, 0),
            algorithm_version_min="v1" if "source_accident_import_run_id" in sources else None,
            algorithm_version_null_count=0,
        )

    return DerivedDataFreshnessCounts(
        generations=(
            _generation(
                "edge_attribute_counts",
                {"source_accident_import_run_id": 10, "source_osm_import_run_id": 20},
            ),
            _generation(
                "way_attribute_counts",
                {"source_accident_import_run_id": 10, "source_osm_import_run_id": 20},
            ),
            _generation("designation_attributes", {"source_osm_import_run_id": 20}),
        ),
        latest_succeeded_run_id={"accident_import_runs": 10, "osm_import_runs": 20},
        road_edges_total=100,
        elevation_uncalculated_count=3,
    )


def test_get_derived_data_freshness_requires_basic_auth(admin_credentials):
    response = client.get(FRESHNESS_URL)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="RideCompass admin"'


def test_get_derived_data_freshness_rejects_wrong_credentials(admin_credentials):
    response = client.get(FRESHNESS_URL, headers={"Authorization": _basic_auth_header("admin-user", "wrong")})

    assert response.status_code == 401


def test_get_derived_data_freshness_returns_report(admin_credentials):
    app.dependency_overrides[get_derived_data_freshness_service] = lambda: FakeDerivedDataFreshnessService(
        counts=_fresh_counts()
    )
    try:
        response = client.get(FRESHNESS_URL, headers=AUTH_HEADERS)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["computed_at"].startswith("2026-09-04")
    assert [g["table_name"] for g in body["generations"]] == [
        "edge_attribute_counts",
        "way_attribute_counts",
        "designation_attributes",
    ]
    edge_entry = body["generations"][0]
    assert edge_entry["is_stale"] is False
    assert edge_entry["algorithm_version"]["current_version"] == "v1"
    designation_entry = body["generations"][2]
    assert designation_entry["algorithm_version"] is None
    assert len(designation_entry["sources"]) == 1
    assert body["elevation"] == {"road_edges_total": 100, "uncalculated_count": 3}


def test_get_derived_data_freshness_translates_db_errors_to_503(admin_credentials):
    db_error = DBAPIError("SELECT 1", {}, Exception("connection refused"))
    app.dependency_overrides[get_derived_data_freshness_service] = lambda: FakeDerivedDataFreshnessService(
        error=db_error
    )
    try:
        response = client.get(FRESHNESS_URL, headers=AUTH_HEADERS)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert "鮮度台帳" in response.json()["detail"]
