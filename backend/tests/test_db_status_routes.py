"""`GET /api/admin/db-status`のルートテスト: レポートを応答へ受け渡す・DB例外だけを503にする。

ここで見ないもの: 認可 → `test_admin_route_authorization.py`、どの例外をDB障害に数えるか → `test_database.py`
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.api.dependencies import get_db_status_service
from app.infrastructure.db_status import (
    ConnectionCounts,
    DbStatusCounts,
    ImportRunCounts,
    SucceededRunCounts,
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
                latest_succeeded=SucceededRunCounts(4, COMPUTED_AT),
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


def test_returns_the_report(admin_credentials):
    _override(_StubService(_counts()))

    body = client.get(STATUS_URL, headers=AUTH_HEADERS).json()

    assert body == build_db_status_report(_counts(), COMPUTED_AT).model_dump(mode="json")


def test_db_error_becomes_503_instead_of_an_empty_report(admin_credentials):
    # 診断用APIのため、空のレポートへ倒すと「問題なし」に見えてしまう。
    _override(_StubService(error=DBAPIError("stmt", {}, Exception("boom"))))

    response = client.get(STATUS_URL, headers=AUTH_HEADERS)

    assert response.status_code == 503


def test_an_implementation_error_is_not_reported_as_the_db_being_down(admin_credentials):
    _override(_StubService(error=TypeError("wrong arguments")))

    with pytest.raises(TypeError):
        client.get(STATUS_URL, headers=AUTH_HEADERS)
