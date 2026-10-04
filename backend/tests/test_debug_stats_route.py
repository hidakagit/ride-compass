"""運用統計エンドポイント /api/debug/stats が、プロセス内の集計を応答へ受け渡す(docs/conventions/logging.md参照)。

ここで見ないもの: 集計の中身（回数・ヒット率）→ `test_debug_log.py`、構成の欄の有無 → 応答の型
"""

import pytest
from fastapi.testclient import TestClient

from app.infrastructure.debug_log import log_external_call, record_rate_limit_rejection
from app.main import app

pytestmark = pytest.mark.usefixtures("empty_debug_counters")


def test_debug_stats_returns_snapshot():
    with log_external_call("test:api"):
        pass
    record_rate_limit_rejection("basemap", "203.0.113.5", "300/min")

    response = TestClient(app).get("/api/debug/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["external"]["test:api"]["calls"] == 1
    assert body["rate_limit_rejections"] == {"basemap": 1}
