"""`GET /api/admin/db-status`のルートテスト（レスポンス形・DB例外の扱い）。"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.api.dependencies import get_db_status_service
from app.infrastructure.db_status import (
    ConnectionCounts,
    DbStatusCounts,
    ImportRunCounts,
    TableCounts,
)
from app.main import app
from app.services.db_status_service import build_db_status_report
from tests.admin_auth import AUTH_HEADERS

client = TestClient(app)
STATUS_URL = "/api/admin/db-status"
COMPUTED_AT = datetime(2026, 9, 14, tzinfo=timezone.utc)


class _StubService:
    def __init__(self, counts: DbStatusCounts | None = None, error: Exception | None = None):
        self._counts = counts
        self._error = error

    async def get_status_report(self):
        if self._error is not None:
            raise self._error
        return build_db_status_report(self._counts, COMPUTED_AT)


def _counts() -> DbStatusCounts:
    return DbStatusCounts(
        imports=(
            ImportRunCounts(
                label="OSM取込",
                latest_id=4,
                latest_status="succeeded",
                latest_finished_at=COMPUTED_AT,
                latest_identity={"pbf_name": "kanto-latest.osm.pbf"},
                latest_item_count=1_329_632,
                latest_succeeded_id=4,
                latest_succeeded_finished_at=COMPUTED_AT,
            ),
        ),
        tables=(
            TableCounts(
                table_name="road_edges",
                row_count=5_047_354,
                total_bytes=229 * 1024 * 1024,
                dead_tuples=0,
                analyzed_at=COMPUTED_AT,
                vacuumed_at=COMPUTED_AT,
            ),
        ),
        connections=ConnectionCounts(
            total=2,
            max_connections=100,
            idle_in_transaction=0,
            longest_idle_transaction_seconds=0.0,
            longest_query_seconds=0.0,
        ),
        database_bytes=675 * 1024 * 1024,
    )


def _override(service: _StubService) -> None:
    app.dependency_overrides[get_db_status_service] = lambda: service


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_returns_imports_tables_and_connections(admin_credentials):
    _override(_StubService(_counts()))

    body = client.get(STATUS_URL, headers=AUTH_HEADERS).json()

    assert body["imports"][0]["label"] == "OSM取込"
    assert body["imports"][0]["latest_identity"] == {"pbf_name": "kanto-latest.osm.pbf"}
    assert body["imports"][0]["needs_attention"] is False
    assert body["tables"][0]["table_name"] == "road_edges"
    assert body["tables"][0]["row_count"] == 5_047_354
    assert body["connections"]["max_connections"] == 100
    assert body["database_bytes"] == 675 * 1024 * 1024


def test_db_error_becomes_503_instead_of_an_empty_report(admin_credentials):
    # 診断用APIのため、空のレポートへ倒すと「問題なし」に見えてしまう。
    _override(_StubService(error=DBAPIError("stmt", {}, Exception("boom"))))

    response = client.get(STATUS_URL, headers=AUTH_HEADERS)

    assert response.status_code == 503
