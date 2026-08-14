"""運用統計エンドポイント /api/debug/stats の回帰テスト(docs/logging.md参照)。"""

import pytest
from fastapi.testclient import TestClient

from app.infrastructure.debug_log import log_external_call, record_rate_limit_rejection, reset_stats
from app.main import app


@pytest.fixture(autouse=True)
def _clean_stats():
    reset_stats()
    yield
    reset_stats()


def test_debug_stats_returns_snapshot():
    with log_external_call("test:api") as fields:
        fields["cache"] = "miss"
        fields["result"] = "ok"
    record_rate_limit_rejection("basemap", "203.0.113.5", "300/min")

    client = TestClient(app)
    response = client.get("/api/debug/stats")
    assert response.status_code == 200
    body = response.json()

    # 構成スナップショット(どのコミット・エンジン設定での集計かを判別できる)
    assert "commit" in body
    assert "started_at" in body
    assert body["engine"] in ("openrouteservice", "road_graph")
    assert isinstance(body["debug_mode"], bool)

    stats = body["external"]["test:api"]
    assert stats["calls"] == 1
    assert stats["cache_misses"] == 1
    assert stats["cache_hit_rate"] == 0.0
    assert body["rate_limit_rejections"]["basemap"] == 1


def test_debug_stats_empty_process():
    client = TestClient(app)
    body = client.get("/api/debug/stats").json()
    assert body["external"] == {}
    assert body["rate_limit_rejections"] == {}
