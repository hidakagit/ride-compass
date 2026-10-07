"""`GET /api/admin/db-status`のルートテスト: レポートを応答へ受け渡す。

ここで見ないもの: 認可 → `test_admin_route_authorization.py`、DB障害の503 → `test_admin_db_unavailable.py`、
注意が要るかの判断（しきい値） → `test_db_status_service.py`（ここではレポートを作る関数の結果がそのまま応答になることだけを見る）
"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.api.dependencies import get_db_status_service
from app.infrastructure.db_status import (
    ConnectionCounts,
    DbStatusCounts,
    ImportRunCounts,
    LatestRunCounts,
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
    def __init__(self, counts: DbStatusCounts):
        self._counts = counts

    async def get_status_report(self):
        return build_db_status_report(self._counts, COMPUTED_AT)


def _counts() -> DbStatusCounts:
    return DbStatusCounts(
        imports=(
            ImportRunCounts(
                label="OSM取込",
                latest=LatestRunCounts(
                    id=4, status="succeeded", finished_at=COMPUTED_AT,
                    identity={"pbf_name": "kanto-latest.osm.pbf"}, item_count=1_329_632,
                ),
                latest_succeeded=SucceededRunCounts(id=4, finished_at=COMPUTED_AT),
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
