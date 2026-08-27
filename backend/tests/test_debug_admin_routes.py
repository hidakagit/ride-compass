import base64
import logging
import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.infrastructure.debug_control import get_recent_logs
from app.main import app

client = TestClient(app)


def _basic_auth_header(username: str, password: str) -> str:
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {encoded}"


AUTH_HEADERS = {"Authorization": _basic_auth_header("admin-user", "secret-password")}


@pytest.fixture(autouse=True)
def admin_credentials(monkeypatch):
    monkeypatch.setattr(settings, "admin_basic_auth_username", "admin-user")
    monkeypatch.setattr(settings, "admin_basic_auth_password", "secret-password")


@pytest.fixture(autouse=True)
def _restore_debug_mode():
    # settings.debug_mode・ルートロガーのレベルはプロセス全体で共有される可変状態のため、
    # このテストファイルでの切替が他のテストへ漏れないよう毎回元に戻す
    # （test_axis_admin_routes.pyのadmin_credentialsパターンと同じ発想）。
    original_debug_mode = settings.debug_mode
    original_level = logging.getLogger().level
    yield
    settings.debug_mode = original_debug_mode
    logging.getLogger().setLevel(original_level)


# --- 認可（require_admin_basic_auth、axis_admin.pyと共有） ---


def test_update_mode_rejects_missing_credentials():
    response = client.post("/api/admin/debug/mode", json={"enabled": True})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="RideCompass admin"'


def test_update_mode_rejects_wrong_credentials():
    response = client.post(
        "/api/admin/debug/mode",
        json={"enabled": True},
        headers={"Authorization": _basic_auth_header("admin-user", "wrong")},
    )

    assert response.status_code == 401


def test_update_mode_rejects_any_credentials_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "admin_basic_auth_username", "")
    monkeypatch.setattr(settings, "admin_basic_auth_password", "")

    response = client.post("/api/admin/debug/mode", json={"enabled": True}, headers=AUTH_HEADERS)

    assert response.status_code == 401


def test_read_logs_requires_auth():
    response = client.get("/api/admin/debug/logs")

    assert response.status_code == 401


# --- debug_modeのランタイム切替（再起動不要） ---


def test_update_mode_enables_and_disables_without_restart():
    enable_response = client.post("/api/admin/debug/mode", json={"enabled": True}, headers=AUTH_HEADERS)
    assert enable_response.status_code == 200
    assert enable_response.json() == {"debug_mode": True}
    assert settings.debug_mode is True
    assert logging.getLogger().level == logging.DEBUG

    disable_response = client.post("/api/admin/debug/mode", json={"enabled": False}, headers=AUTH_HEADERS)
    assert disable_response.status_code == 200
    assert disable_response.json() == {"debug_mode": False}
    assert settings.debug_mode is False
    assert logging.getLogger().level == logging.INFO


def test_read_mode_reflects_current_state():
    client.post("/api/admin/debug/mode", json={"enabled": True}, headers=AUTH_HEADERS)

    response = client.get("/api/admin/debug/mode", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json() == {"debug_mode": True}


# --- ログ取得（リングバッファ、T318のユースケース: containsで絞り込み） ---


def test_read_logs_filters_by_contains_and_limit():
    client.post("/api/admin/debug/mode", json={"enabled": True}, headers=AUTH_HEADERS)
    marker = uuid.uuid4().hex
    logger = logging.getLogger("test.t377")
    logger.debug("distance filter rejected bearing=0 marker=%s", marker)
    logger.debug("distance filter rejected bearing=1 marker=%s", marker)
    logger.debug("unrelated debug line marker=%s", marker)

    response = client.get("/api/admin/debug/logs", params={"contains": f"distance filter rejected bearing=1 marker={marker}"}, headers=AUTH_HEADERS)

    assert response.status_code == 200
    lines = response.json()
    assert len(lines) == 1
    assert f"bearing=1 marker={marker}" in lines[0]


def test_read_logs_returns_nothing_while_debug_mode_disabled():
    client.post("/api/admin/debug/mode", json={"enabled": False}, headers=AUTH_HEADERS)
    marker = uuid.uuid4().hex
    logging.getLogger("test.t377").debug("should not be recorded marker=%s", marker)

    response = client.get("/api/admin/debug/logs", params={"contains": marker}, headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json() == []


# --- リングバッファの上限件数（debug_control.py単体） ---


def test_ring_buffer_keeps_only_most_recent_entries(monkeypatch):
    import app.infrastructure.debug_control as debug_control_module

    small_handler = debug_control_module._LogRingBufferHandler(maxlen=3)
    monkeypatch.setattr(debug_control_module, "_ring_buffer_handler", small_handler)
    logger = logging.getLogger("test.t377.ringbuffer")
    logger.addHandler(small_handler)
    logger.setLevel(logging.DEBUG)
    try:
        for i in range(5):
            logger.debug("entry %d", i)
    finally:
        logger.removeHandler(small_handler)

    lines = get_recent_logs()

    assert len(lines) == 3
    assert "entry 2" in lines[0]
    assert "entry 4" in lines[2]
