"""app/main.pyのlifespan（起動・終了シーケンス）のテスト。

`TestClient(app)`をcontext manager無しで生成するとASGIのlifespanイベント自体が
発火しない。ここでは`with TestClient(app) as client:`で実際に発火させる。

DBを触る呼び出しはすべてスタブへ差し替え、実接続を残さない（残すと、テストの
イベントループが閉じた後に接続の後始末が走り「Event loop is closed」になる）。
"""

import inspect
import logging
from datetime import datetime

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi.testclient import TestClient

from app import main as main_module
from app.main import app
from app.services.axis_registry_service import AxisDefinitionSyncError
from tests.bound_fake import bound


async def _noop(*args, **kwargs) -> None:
    return None


async def _noop_job(*args, **kwargs) -> None:
    """スケジューラへ載せる代わりの何もしない仕事。`__module__`がこのテストファイルに
    なることを、下の「本物が1本も載っていない」テストが手掛かりに使う。"""
    return None


def _startup_job_attribute_names() -> list[str]:
    """`lifespan`がスケジューラへ載せるジョブの属性名。

    **名前を並べない。** 並べると、ジョブを1本足したときに無害化から漏れて本物が走る。
    """
    return [
        name
        for name, obj in vars(main_module).items()
        if name.endswith("_job") and inspect.iscoroutinefunction(obj)
    ]


@pytest.fixture(autouse=True)
def _isolated_scheduler(monkeypatch):
    """共有の`_scheduler`へテストごとに同じjob idをadd_jobするとAPSchedulerの
    ConflictingIdErrorになるため、テストごとに新しいインスタンスへ差し替えて隔離する。

    **起動時ジョブはすべて無害化する**: いずれも起動直後に即時実行される登録のため、
    TestClientのcontext manager内でイベントループが回っている間に実際に発火しうる。
    本物は外部への実HTTP問い合わせや**実ディスクの削除**を行う。対象は`main.py`の
    宣言から導く。

    `get_http_client`もダミーへ差し替える: `httpx.AsyncClient`の生成はSSLコンテキスト
    構築を伴い、環境によっては1回あたり約1秒かかる。ジョブを無害化済みで返り値を
    実際には使わないため、安全にこのコストを避けられる。
    """
    fresh_scheduler = AsyncIOScheduler()
    monkeypatch.setattr(main_module, "_scheduler", fresh_scheduler)
    monkeypatch.setattr(main_module, "refresh_axis_definitions", bound(main_module.refresh_axis_definitions, _noop))
    monkeypatch.setattr(main_module, "refresh_tuning_values", bound(main_module.refresh_tuning_values, _noop))
    for name in _startup_job_attribute_names():
        monkeypatch.setattr(main_module, name, bound(getattr(main_module, name), _noop_job))
    monkeypatch.setattr(main_module, "get_http_client", lambda timeout: None)
    yield fresh_scheduler
    if fresh_scheduler.running:
        fresh_scheduler.shutdown(wait=False)


@pytest.fixture
def captured_add_job_calls(monkeypatch, _isolated_scheduler):
    """`add_job`へ渡された引数を記録する。

    起動後に`scheduler.get_job()`で読み戻す方式だと、next_run_time=nowのジョブが
    TestClient退出前に実際に発火し、次のinterval分先へ進んだ状態を読むことがある。
    """
    calls: list[dict[str, object]] = []
    original_add_job = _isolated_scheduler.add_job

    def _spy_add_job(func, trigger=None, **kwargs):
        calls.append({"trigger": trigger, **kwargs})
        return original_add_job(func, trigger=trigger, **kwargs)

    monkeypatch.setattr(_isolated_scheduler, "add_job", _spy_add_job)
    return calls


def test_lifespan_fails_fast_when_refresh_axis_definitions_raises(monkeypatch):
    """`AxisDefinitionSyncError`はlifespan内で捕捉されず、アプリ起動自体が失敗する。"""

    async def _raise(*args, **kwargs):
        raise AxisDefinitionSyncError("boom")

    monkeypatch.setattr(main_module, "refresh_axis_definitions", _raise)

    with pytest.raises(AxisDefinitionSyncError):
        with TestClient(app):
            pass


def test_no_real_startup_job_is_scheduled_in_this_file(_isolated_scheduler):
    """このファイルの実行で、本物の起動時ジョブが1本も載らないこと。

    載ると、テストを流しただけで外部への実HTTP問い合わせや**開発機の実ディスクの削除**が
    走る。無害化は`main.py`の宣言から導くが、**導出が空振りしても静かに通る**ため、
    載った結果の側からも確かめる。
    """
    with TestClient(app):
        scheduled = [(job.id, job.func) for job in _isolated_scheduler.get_jobs()]

    assert scheduled, "起動時ジョブが1本も載っていない（導出が空振りしている可能性）"
    assert [job_id for job_id, func in scheduled if func.__module__ != __name__] == []


def test_every_interval_job_also_runs_immediately_at_startup(captured_add_job_calls):
    """起動直後に1回も走らないintervalジョブを作らない。

    走らないと、次の定期実行までキャッシュが空のままになり、その間のリクエストは
    502を返し続ける。**ジョブを名指ししない**——登録された側から導くので、ジョブを
    1本足したときにも効く。
    """
    before = datetime.now()

    with TestClient(app):
        pass

    interval_jobs = [call for call in captured_add_job_calls if call["trigger"] == "interval"]
    assert interval_jobs, "intervalジョブが1本も登録されていない"
    for call in interval_jobs:
        assert call["minutes"] > 0, call["id"]
        started_at = call.get("next_run_time")
        assert started_at is not None, f"{call['id']}にnext_run_timeが無い"
        assert abs((started_at - before).total_seconds()) < 5, call["id"]


async def test_a_failing_scheduled_job_is_logged_and_does_not_escape(caplog):
    """ジョブ本体の失敗はWARNINGとして残り、スケジューラの外へは伝わらない。"""

    @main_module._with_failure_log("ridecompass.test_job", "テスト用ジョブ")
    async def _boom() -> None:
        raise RuntimeError("boom")

    with caplog.at_level(logging.WARNING, logger="ridecompass.test_job"):
        await _boom()

    assert "テスト用ジョブに失敗しました" in caplog.text


def test_lifespan_shuts_down_scheduler_before_closing_http_clients(monkeypatch, _isolated_scheduler):
    """シャットダウンはAPScheduler停止→httpxクライアントcloseの順で走る。"""
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
