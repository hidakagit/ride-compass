from datetime import datetime

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.routers import health as health_router
from app.config import settings
from app.main import app
from tests.conftest import TEST_DATABASE_URL

# road_graph_session/road_graph_repositoryフィクスチャ（conftest.py）を素通りで使うためだけの
# import。designation_models/accident_modelsをBase.metadataへ登録する（このファイル単体実行時も
# route_designations/designation_attributes/accident_pointsテーブルがcreate_allで作られるよう、
# test_road_graph_repository.pyと同じ「テストファイルごとに自己完結させる」idiom）。
from app.infrastructure import accident_models, designation_models  # noqa: F401

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


# --- /api/debug/db-status（改善計画T74「本番DBが置き去りになる」対策A） ---


def test_db_status_reports_not_configured_when_repository_disabled(monkeypatch):
    # DBなし構成では接続を試みず、その旨だけ返す（road_graph_use_repository無効時の
    # 他のDI（get_region_service等）と同じ既定安全側の分岐）。
    monkeypatch.setattr(settings, "road_graph_use_repository", False)

    response = client.get("/api/debug/db-status")

    assert response.status_code == 200
    assert response.json() == {"commit": None, "database_configured": False}


def test_db_status_returns_reachable_false_on_db_error(monkeypatch):
    # DB障害時もHTTP 500にせず、WARNINGログと共にreachable=falseを返す
    # （docs/logging.mdの「エラーは常時WARNING以上」方針、region_service.pyの
    # 既存のtry/exceptパターンと同じ）。
    monkeypatch.setattr(settings, "road_graph_use_repository", True)

    class _BrokenEngine:
        def connect(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(health_router, "get_engine", lambda: _BrokenEngine())

    response = client.get("/api/debug/db-status")

    assert response.status_code == 200
    body = response.json()
    assert body["database_configured"] is True
    assert body["reachable"] is False
    assert "boom" in body["error"]


@pytest_asyncio.fixture(loop_scope="module")
async def db_status_test_engine(road_graph_session):
    # road_graph_session（conftest.py）へテーブル作成・接続不可時のskipを委譲しつつ、
    # db_status()が使うget_engine()だけ別途ridecompass_test向けに差し替える
    # （health.pyのget_engineはアプリ全体のシングルトンでsettings.database_url固定のため）。
    engine = create_async_engine(TEST_DATABASE_URL)
    yield engine
    await engine.dispose()


@pytest.mark.asyncio(loop_scope="module")
async def test_db_status_returns_table_row_counts_and_import_run_status_for_empty_test_db(
    db_status_test_engine, monkeypatch
):
    monkeypatch.setattr(settings, "road_graph_use_repository", True)
    monkeypatch.setattr(health_router, "get_engine", lambda: db_status_test_engine)

    result = await health_router.db_status()

    assert result["database_configured"] is True
    assert result["reachable"] is True
    # ridecompass_test DBはcreate_allのみでapply_pending_migrationsを経由しないため、
    # schema_migrationsテーブル自体が無く「全マイグレーション未適用」扱いになる
    # （list_pending_migrationsの仕様どおり）。
    assert isinstance(result["pending_migrations"], list)
    assert len(result["pending_migrations"]) > 0
    # create_allで作成済みだが空のテーブルは0件（Noneではない）で返る。
    assert result["table_row_counts"] == {
        "osm_raw_ways": 0,
        "osm_raw_pois": 0,
        "road_edges": 0,
        "route_designations": 0,
        "designation_attributes": 0,
        "accident_points": 0,
    }
    # import_runsテーブルも作成済みだが0行のため、status等はNone（テーブル欠落時のNoneと区別）。
    assert result["import_runs"] == {
        "osm": {"status": None, "started_at": None, "finished_at": None},
        "accident": {"status": None, "started_at": None, "finished_at": None},
        "designation": {"status": None, "started_at": None, "finished_at": None},
    }
