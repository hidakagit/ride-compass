"""`/health`のうち、管理データのバックアップからの経過時間を見る（見回りがこれを読んで止まりに気づく）。

ここで見ないもの: `commit`・`started_at`（値を詰めて返すだけ）。
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.infrastructure import admin_data_backup
from app.main import app

client = TestClient(app)


@pytest.mark.parametrize(("placed_hours_ago", "expected"), [(50, 50.0), (None, None)])
def test_health_returns_hours_since_the_last_backup(tmp_path, monkeypatch, placed_hours_ago, expected):
    """経過時間が狂うと止まっていても気づかず、記録が無いときに落ちると/healthを待つデプロイが失敗する。"""
    marker = tmp_path / "admin_data_backup_at"
    monkeypatch.setattr(admin_data_backup, "MARKER_PATH", marker)
    if placed_hours_ago is not None:
        marker.write_text((datetime.now(UTC) - timedelta(hours=placed_hours_ago)).strftime("%Y-%m-%dT%H:%M:%S+00:00") + "\n")

    assert client.get("/health").json()["admin_data_backup_age_hours"] == expected
