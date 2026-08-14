from datetime import datetime

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


def test_health_returns_ok_status():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_includes_started_at_as_valid_iso_timestamp():
    response = client.get("/health")

    started_at = response.json()["started_at"]
    assert isinstance(started_at, str)
    datetime.fromisoformat(started_at)  # 例外を送出しなければ有効なISO8601


def test_health_commit_is_none_when_render_git_commit_not_set():
    # ローカル開発環境ではRENDER_GIT_COMMIT環境変数が無いため未設定のまま
    assert settings.render_git_commit is None
    response = client.get("/health")

    assert response.json()["commit"] is None


def test_health_reflects_render_git_commit_when_configured(monkeypatch):
    # Renderにデプロイされたプロセスでは自動注入されるRENDER_GIT_COMMITの値をそのまま返し、
    # 手元のgit HEADと比較して最新版が反映されているか確認できるようにする
    monkeypatch.setattr(settings, "render_git_commit", "abc1234def5678")

    response = client.get("/health")

    assert response.json()["commit"] == "abc1234def5678"
