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


@pytest.mark.parametrize(
    "write_marker",
    [
        pytest.param(lambda marker: marker.write_text("壊れた\n"), id="日時でない"),
        pytest.param(lambda marker: marker.write_text("2026-10-05T03:17:00\n"), id="時差が無い"),
        pytest.param(lambda marker: marker.mkdir(), id="ファイルとして読めない"),
    ],
)
def test_health_stays_ok_when_the_backup_marker_is_unreadable(tmp_path, monkeypatch, caplog, write_marker):
    """印のファイルが壊れて/healthが落ちると、それを待つデプロイと見回りまで止まる。読めないときは記録が無いときと同じく
    nullで返し（見回りが知らせに出す）、読めない理由はログにだけ出る。"""
    marker = tmp_path / "admin_data_backup_at"
    monkeypatch.setattr(admin_data_backup, "MARKER_PATH", marker)
    write_marker(marker)

    response = client.get("/health")

    assert (response.status_code, response.json()["status"], response.json()["admin_data_backup_age_hours"]) == (200, "ok", None)
    assert "管理データのバックアップの印のファイルが読めない" in caplog.text
