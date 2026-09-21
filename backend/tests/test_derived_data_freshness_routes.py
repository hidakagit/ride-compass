"""鮮度台帳のHTTPの口が、サービスの返した項目を落とさずに返すこと。

`test_derived_data_freshness.py`はサービスと集計SQLを見る。**router側の組み立ては
別の層**で、そこで項目が1つ欠けるとレスポンスの検証が落ちて500になる——本番で実際に
起きた（被覆の3項目を渡していなかった）。層をまたぐ受け渡しをここで押さえる。
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_derived_data_freshness_service
from app.main import app
from app.services.derived_data_freshness_service import (
    ColumnEntry,
    DerivedDataFreshnessReport,
    TableEntry,
)
from tests.admin_auth import ADMIN_PASSWORD, ADMIN_USERNAME, basic_auth_header

client = TestClient(app)
AUTH_HEADERS = {"Authorization": basic_auth_header(ADMIN_USERNAME, ADMIN_PASSWORD)}

#: 覆いを宣言した表と、していない表の両方を入れる（後者はNoneのまま通ること）。
REPORT = DerivedDataFreshnessReport(
    computed_at=datetime(2026, 9, 21, 9, 0, tzinfo=timezone.utc),
    tables=[
        TableEntry(
            table_name="node_materials", row_count=10, source="osm_node",
            oldest_run_id=1, latest_run_id=2, is_stale=True,
            coverage_parent="osm_node", coverage_parent_row_count=12, missing_rows=2,
            columns=[ColumnEntry(column="branch_count", null_count=3, is_incomplete=True)],
        ),
        TableEntry(
            table_name="way_materials", row_count=5, source="osm_way",
            oldest_run_id=3, latest_run_id=3, is_stale=False,
            coverage_parent=None, coverage_parent_row_count=None, missing_rows=None,
            columns=[ColumnEntry(column="lc_water", null_count=0, is_incomplete=False)],
        ),
    ],
)


class _FakeService:
    async def get_freshness_report(self) -> DerivedDataFreshnessReport:
        return REPORT


@pytest.fixture
def override_service(admin_credentials):
    app.dependency_overrides[get_derived_data_freshness_service] = _FakeService
    try:
        yield
    finally:
        app.dependency_overrides.clear()


def test_被覆の項目がレスポンスへそのまま出る(override_service):
    response = client.get("/api/admin/derived-data/freshness", headers=AUTH_HEADERS)

    assert response.status_code == 200
    tables = {table["table_name"]: table for table in response.json()["tables"]}
    assert tables["node_materials"]["coverage_parent"] == "osm_node"
    assert tables["node_materials"]["coverage_parent_row_count"] == 12
    assert tables["node_materials"]["missing_rows"] == 2


def test_覆いを宣言しない表はNoneのまま出る(override_service):
    response = client.get("/api/admin/derived-data/freshness", headers=AUTH_HEADERS)

    tables = {table["table_name"]: table for table in response.json()["tables"]}
    assert tables["way_materials"]["coverage_parent"] is None
    assert tables["way_materials"]["missing_rows"] is None
