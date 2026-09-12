from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.api.dependencies import get_derived_data_freshness_service
from app.infrastructure.derived_data_freshness import (
    GENERATION_FRESHNESS_SPECS,
    DerivedDataFreshnessCounts,
    GenerationFreshnessCounts,
)
from app.main import app
from app.services.derived_data_freshness_service import build_freshness_report
from tests.admin_auth import AUTH_HEADERS, basic_auth_header

client = TestClient(app)

FRESHNESS_URL = "/api/admin/derived-data/freshness"


class FakeDerivedDataFreshnessService:
    def __init__(self, counts: DerivedDataFreshnessCounts | None = None, error: Exception | None = None):
        self._counts = counts
        self._error = error

    async def get_freshness_report(self):
        if self._error is not None:
            raise self._error
        assert self._counts is not None
        return build_freshness_report(self._counts, datetime(2026, 9, 4, tzinfo=timezone.utc))


# 「鮮度が最新」を表すフェイクは、台帳の宣言そのものから組み立てる（テーブルを書き並べると
# 台帳へ1件足したときにここだけ取り残され、build_freshness_reportのzip(strict=True)が
# 落ちるまで気づけない。版数を書き写す形も同じで、上げるたび偽の失敗を出す）。
_LATEST_RUN_ID = {"accident_import_runs": 10, "osm_import_runs": 20}


def _fresh_counts() -> DerivedDataFreshnessCounts:
    def _generation(spec) -> GenerationFreshnessCounts:
        sources = {source.source_column: _LATEST_RUN_ID[source.run_table] for source in spec.sources}
        return GenerationFreshnessCounts(
            table_name=spec.table_name,
            row_count=5,
            source_min=sources,
            source_null_count=dict.fromkeys(sources, 0),
            algorithm_version_min=spec.algorithm_version_current,
            algorithm_version_null_count=0,
        )

    return DerivedDataFreshnessCounts(
        generations=tuple(_generation(spec) for spec in GENERATION_FRESHNESS_SPECS),
        latest_succeeded_run_id=dict(_LATEST_RUN_ID),
        road_edges_total=100,
        elevation_uncalculated_count=3,
    )


def test_get_derived_data_freshness_requires_basic_auth(admin_credentials):
    response = client.get(FRESHNESS_URL)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="RideCompass admin"'


def test_get_derived_data_freshness_rejects_wrong_credentials(admin_credentials):
    response = client.get(FRESHNESS_URL, headers={"Authorization": basic_auth_header("admin-user", "wrong")})

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
    # 応答は台帳の宣言をその順で返す（並びもテーブル名も台帳側から取る）。
    assert [g["table_name"] for g in body["generations"]] == [
        spec.table_name for spec in GENERATION_FRESHNESS_SPECS
    ]
    by_table = {g["table_name"]: g for g in body["generations"]}
    for spec in GENERATION_FRESHNESS_SPECS:
        entry = by_table[spec.table_name]
        assert entry["is_stale"] is False
        assert len(entry["sources"]) == len(spec.sources)
        if spec.algorithm_version_current is None:
            assert entry["algorithm_version"] is None
        else:
            assert entry["algorithm_version"]["current_version"] == spec.algorithm_version_current
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
