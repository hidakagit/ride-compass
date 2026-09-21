"""app/main.pyのlifespan（起動・終了シーケンス）の回帰テスト（改善計画T491）。

test_main.py・test_health.py等の既存テストは`TestClient(app)`をcontext manager無しで
生成しており、この形だとASGIのlifespanイベント（startup/shutdown）自体が発火しない。
ここでは`with TestClient(app) as client:`（context manager形式）で実際にlifespanを
発火させ、docs/modules/backend/cross-cutting-infrastructure.md「アプリ起動（main.py）」
節が明記する不変条件を検証する。

`refresh_axis_definitions`は実DBへ接続するため、いずれのテストもmonkeypatchで差し替え、
実DB接続を必要としない（docs/conventions/testing.mdの一般方針どおり、DB接続を要するテストは
postgisマーカー付きの別ファイルへ隔離する）。`app.main._scheduler`はモジュールレベルの
シングルトンで、同じjob id（"refresh_amedas"・"prewarm_jma_tile"）を複数回`add_job`すると
APSchedulerが`ConflictingIdError`を送出するため、テストごとに新しい`AsyncIOScheduler`へ
差し替えて分離する。
"""

import inspect
from datetime import datetime

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi.testclient import TestClient

from app import main as main_module
from app.config import settings
from app.main import app
from app.services.axis_registry_service import AxisDefinitionSyncError
from app.services.jma_amedas_service import AMEDAS_REFRESH_INTERVAL_MINUTES


async def _noop_refresh_axis_definitions(*args, **kwargs) -> None:
    return None


async def _noop_refresh_tuning_values(*args, **kwargs) -> None:
    """較正値の読み込みも止める。

    このファイルのテストは**DBを触らない**契約で、lifespanが開くセッションはどれも
    スタブへ差し替える。実接続を残すと、テストのイベントループが閉じた後に接続の後始末が
    走り「Event loop is closed」になる。
    """
    return None


async def _noop_job(*args, **kwargs) -> None:
    """スケジューラへ載せる代わりの何もしない仕事。`__module__`がこのテストファイルに
    なることを、下の「本物が1本も載っていない」テストが手掛かりに使う。"""
    return None


def _startup_job_attribute_names() -> list[str]:
    """`lifespan`がスケジューラへ載せるジョブの属性名。

    **名前を並べない。** 並べると、ジョブを1本足したときに無害化から漏れて本物が走る
    ——実際に`_prune_stale_disk_generations_job`が漏れており、このファイルを実行すると
    開発機の`backend/data/tile_cache`に対して実際の削除が走りうる状態だった（T951）。
    """
    return [
        name
        for name, obj in vars(main_module).items()
        if name.endswith("_job") and inspect.iscoroutinefunction(obj)
    ]


@pytest.fixture(autouse=True)
def _isolated_scheduler(monkeypatch):
    """実行中の共有_schedulerへテストごとに同じjob idをadd_jobするとAPSchedulerの
    ConflictingIdErrorになるため、テストごとに新しいインスタンスへ差し替えて隔離する。
    lifespan()は`_scheduler`をモジュールグローバルとして参照するため、モジュール属性を
    差し替えるだけで呼び出し先へ反映される。

**起動時ジョブはすべて無害化する**（改善計画T510・T951）: いずれも起動直後にも
    即時実行される登録のため、TestClientのcontext manager内でイベントループが回っている
    間に実際に発火しうる（実測で確認済み）。本物は外部への実HTTP問い合わせや**実ディスクの
    削除**を行い、lifespanの結線自体を検証する本ファイルの目的に対しては不要かつ望ましく
    ない副作用（外部依存・フレークの原因、無効化を忘れて後続テストへ実HTTP呼び出しが
    漏れ込んだ実績あり）になる。対象は`main.py`の宣言から導く。

    `get_http_client`も軽量なダミーへ差し替える: `httpx.AsyncClient`の生成はSSL
    コンテキスト構築を伴い、`infrastructure/http_client.py`のモジュールdocstringが
    明記するとおり環境によっては1回あたり約1秒かかる。lifespan()は起動時に2回
    （timeout=10.0/15.0）呼ぶ上、`with TestClient(app):`のexit時に`close_all_http_clients()`が
    毎回`_clients`キャッシュを空にするため、本ファイルの4テストはそれぞれ起動のたびに
    実SSLコンテキスト構築を払い直す形になっていた。本ファイルのどのテストも
    `_refresh_amedas_job`/`_prewarm_jma_tile_job`を無害化済みでクライアントの返り値を
    実際には使わないため、ダミーへ差し替えて安全にこのコストを避けられる。"""
    fresh_scheduler = AsyncIOScheduler()
    monkeypatch.setattr(main_module, "_scheduler", fresh_scheduler)
    for name in _startup_job_attribute_names():
        monkeypatch.setattr(main_module, name, _noop_job)
    monkeypatch.setattr(main_module, "get_http_client", lambda timeout: None)
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


def test_no_real_startup_job_is_scheduled_in_this_file(monkeypatch, _isolated_scheduler):
    """このファイルの実行で、本物の起動時ジョブが1本も載らないこと。

    載ると、テストを流しただけで外部への実HTTP問い合わせや**開発機の実ディスクの削除**が
    走る（`_prune_stale_disk_generations_job`は`backend/data/tile_cache`へ
    `prune_to_size_limit`を掛ける）。無害化は`main.py`の宣言から導くが、**導出が空振り
    しても静かに通る**ため、載った結果の側からも確かめる。
    """
    monkeypatch.setattr(main_module, "refresh_axis_definitions", _noop_refresh_axis_definitions)
    monkeypatch.setattr(main_module, "refresh_tuning_values", _noop_refresh_tuning_values)

    with TestClient(app):
        scheduled = [(job.id, job.func) for job in _isolated_scheduler.get_jobs()]

    assert scheduled, "起動時ジョブが1本も載っていない（導出が空振りしている可能性）"
    assert [job_id for job_id, func in scheduled if func.__module__ != __name__] == []


def test_lifespan_registers_amedas_job_with_immediate_next_run_time(monkeypatch, _isolated_scheduler):
    """改善計画T387: JMAアメダス定期更新ジョブがinterval=AMEDAS_REFRESH_INTERVAL_MINUTES分・
    next_run_time=起動直後（コールドスタート対策のnext_run_time=datetime.now()）で
    登録されることを確認する。

    `add_job`呼び出し自体をspyして引数を直接検証する（イベントループ稼働中は
    next_run_time=now指定のジョブがTestClient退出前に実際に発火し得るため、
    起動後にscheduler.get_job()で状態を読み戻す方式だと「既に1回実行され次のinterval分
    先へ進んでいる」という実測済みのレースに引っかかる）。改善計画T510でJMAタイル
    プリウォームジョブも登録されるようになった（`add_job`が2回呼ばれる）ため、
    呼び出しごとにkwargsを蓄積し、id="refresh_amedas"の回だけを拾う。"""
    monkeypatch.setattr(main_module, "refresh_axis_definitions", _noop_refresh_axis_definitions)
    monkeypatch.setattr(main_module, "refresh_tuning_values", _noop_refresh_tuning_values)
    captured_calls: list[dict[str, object]] = []
    original_add_job = _isolated_scheduler.add_job

    def _spy_add_job(func, trigger=None, **kwargs):
        captured_calls.append({"trigger": trigger, **kwargs})
        return original_add_job(func, trigger=trigger, **kwargs)

    monkeypatch.setattr(_isolated_scheduler, "add_job", _spy_add_job)
    before = datetime.now()

    with TestClient(app):
        pass

    captured = next(call for call in captured_calls if call["id"] == "refresh_amedas")
    assert captured["trigger"] == "interval"
    assert captured["minutes"] == AMEDAS_REFRESH_INTERVAL_MINUTES
    assert abs((captured["next_run_time"] - before).total_seconds()) < 5


def test_lifespan_registers_jma_tile_prewarm_job_with_immediate_next_run_time(monkeypatch, _isolated_scheduler):
    """改善計画T510: JMA動的タイルの定期プリウォームジョブが
    interval=settings.jma_tile_prewarm_interval_minutes分・next_run_time=起動直後で
    登録されることを確認する（アメダスジョブの回帰テストと同じ検証パターン）。"""
    monkeypatch.setattr(main_module, "refresh_axis_definitions", _noop_refresh_axis_definitions)
    monkeypatch.setattr(main_module, "refresh_tuning_values", _noop_refresh_tuning_values)
    captured_calls: list[dict[str, object]] = []
    original_add_job = _isolated_scheduler.add_job

    def _spy_add_job(func, trigger=None, **kwargs):
        captured_calls.append({"trigger": trigger, **kwargs})
        return original_add_job(func, trigger=trigger, **kwargs)

    monkeypatch.setattr(_isolated_scheduler, "add_job", _spy_add_job)
    before = datetime.now()

    with TestClient(app):
        pass

    captured = next(call for call in captured_calls if call["id"] == "prewarm_jma_tile")
    assert captured["trigger"] == "interval"
    assert captured["minutes"] == settings.jma_tile_prewarm_interval_minutes
    assert abs((captured["next_run_time"] - before).total_seconds()) < 5


def test_lifespan_shuts_down_scheduler_before_closing_http_clients(monkeypatch, _isolated_scheduler):
    """改善計画T464: シャットダウン時「APScheduler停止（wait=False）→httpxクライアント
    明示close」の順序で実行されることを確認する（docs/modules/backend/
    cross-cutting-infrastructure.mdのlifespan図参照）。"""
    monkeypatch.setattr(main_module, "refresh_axis_definitions", _noop_refresh_axis_definitions)
    monkeypatch.setattr(main_module, "refresh_tuning_values", _noop_refresh_tuning_values)
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
