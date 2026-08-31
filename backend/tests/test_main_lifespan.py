"""app/main.pyのlifespan（起動・終了シーケンス）の回帰テスト（改善計画T491）。

test_main.py・test_health.py等の既存テストは`TestClient(app)`をcontext manager無しで
生成しており、この形だとASGIのlifespanイベント（startup/shutdown）自体が発火しない。
ここでは`with TestClient(app) as client:`（context manager形式）で実際にlifespanを
発火させ、docs/modules/backend/cross-cutting-infrastructure.md「アプリ起動（main.py）」
節が明記する不変条件を検証する。

`refresh_axis_definitions`は実DBへ接続するため、いずれのテストもmonkeypatchで差し替え、
実DB接続を必要としない（docs/testing.mdの一般方針どおり、DB接続を要するテストは
postgisマーカー付きの別ファイルへ隔離する）。`app.main._scheduler`はモジュールレベルの
シングルトンで、同じjob id（"refresh_amedas"）を複数回`add_job`するとAPSchedulerが
`ConflictingIdError`を送出するため、テストごとに新しい`AsyncIOScheduler`へ差し替えて
分離する。
"""

from datetime import datetime

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi.testclient import TestClient

from app import main as main_module
from app.main import app
from app.services.axis_registry_service import AxisDefinitionSyncError
from app.services.jma_amedas_service import AMEDAS_REFRESH_INTERVAL_MINUTES


async def _noop_refresh_axis_definitions(*args, **kwargs) -> None:
    return None


async def _noop_refresh_amedas_job() -> None:
    return None


@pytest.fixture(autouse=True)
def _isolated_scheduler(monkeypatch):
    """実行中の共有_schedulerへテストごとに同じjob idをadd_jobするとAPSchedulerの
    ConflictingIdErrorになるため、テストごとに新しいインスタンスへ差し替えて隔離する。
    lifespan()は`_scheduler`をモジュールグローバルとして参照するため、モジュール属性を
    差し替えるだけで呼び出し先へ反映される。

    `_refresh_amedas_job`も無害化する: `next_run_time=datetime.now()`（起動直後にも
    即時実行、改善計画T387）のため、TestClientのcontext manager内でイベントループが
    回っている間に実際にジョブが発火しうる（実測で確認済み）。本物のジョブはJMAへの
    実HTTP問い合わせを行うため、lifespanの結線自体を検証する本ファイルの目的に対しては
    不要かつ望ましくない副作用（外部依存・フレークの原因）になる。"""
    fresh_scheduler = AsyncIOScheduler()
    monkeypatch.setattr(main_module, "_scheduler", fresh_scheduler)
    monkeypatch.setattr(main_module, "_refresh_amedas_job", _noop_refresh_amedas_job)
    yield fresh_scheduler
    if fresh_scheduler.running:
        fresh_scheduler.shutdown(wait=False)


def test_lifespan_fails_fast_when_refresh_axis_definitions_raises(monkeypatch):
    """改善計画T221 Stage D / T349: refresh_axis_definitionsが送出した
    AxisDefinitionSyncErrorはlifespan内で捕捉されず、アプリ起動自体が失敗する
    （fail-fast設計。docs/modules/backend/cross-cutting-infrastructure.md参照）。"""

    async def _raise(*args, **kwargs):
        raise AxisDefinitionSyncError("boom")

    monkeypatch.setattr(main_module, "refresh_axis_definitions", _raise)

    with pytest.raises(AxisDefinitionSyncError):
        with TestClient(app):
            pass


def test_lifespan_registers_amedas_job_with_immediate_next_run_time(monkeypatch, _isolated_scheduler):
    """改善計画T387: JMAアメダス定期更新ジョブがinterval=AMEDAS_REFRESH_INTERVAL_MINUTES分・
    next_run_time=起動直後（コールドスタート対策のnext_run_time=datetime.now()）で
    登録されることを確認する。

    `add_job`呼び出し自体をspyして引数を直接検証する（イベントループ稼働中は
    next_run_time=now指定のジョブがTestClient退出前に実際に発火し得るため、
    起動後にscheduler.get_job()で状態を読み戻す方式だと「既に1回実行され次のinterval分
    先へ進んでいる」という実測済みのレースに引っかかる）。"""
    monkeypatch.setattr(main_module, "refresh_axis_definitions", _noop_refresh_axis_definitions)
    captured: dict[str, object] = {}
    original_add_job = _isolated_scheduler.add_job

    def _spy_add_job(func, trigger=None, **kwargs):
        captured["trigger"] = trigger
        captured.update(kwargs)
        return original_add_job(func, trigger=trigger, **kwargs)

    monkeypatch.setattr(_isolated_scheduler, "add_job", _spy_add_job)
    before = datetime.now()

    with TestClient(app):
        pass

    assert captured["trigger"] == "interval"
    assert captured["minutes"] == AMEDAS_REFRESH_INTERVAL_MINUTES
    assert captured["id"] == "refresh_amedas"
    assert abs((captured["next_run_time"] - before).total_seconds()) < 5


def test_lifespan_shuts_down_scheduler_before_closing_http_clients(monkeypatch, _isolated_scheduler):
    """改善計画T464: シャットダウン時「APScheduler停止（wait=False）→httpxクライアント
    明示close」の順序で実行されることを確認する（docs/modules/backend/
    cross-cutting-infrastructure.mdのlifespan図参照）。"""
    monkeypatch.setattr(main_module, "refresh_axis_definitions", _noop_refresh_axis_definitions)
    call_order: list[str] = []

    original_shutdown = _isolated_scheduler.shutdown

    def _spy_shutdown(*args, **kwargs):
        call_order.append("scheduler_shutdown")
        return original_shutdown(*args, **kwargs)

    monkeypatch.setattr(_isolated_scheduler, "shutdown", _spy_shutdown)

    async def _spy_close_all_http_clients():
        call_order.append("close_all_http_clients")

    monkeypatch.setattr(main_module, "close_all_http_clients", _spy_close_all_http_clients)

    with TestClient(app):
        pass

    assert call_order == ["scheduler_shutdown", "close_all_http_clients"]
