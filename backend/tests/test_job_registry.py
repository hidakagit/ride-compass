"""`infrastructure/job_registry.py`——プロセス内のジョブ台帳（作る・状態を進める・引く・終わったものを掃除する）。

台帳はプロセス大域にあり、前のテストのジョブが残っていてもよい（どのテストも自分の作ったジョブだけを引く）。
時計は`clock`で進める。

ここで見ないもの:
- ジョブの状態がポーリングの応答（待ち・結果・失敗・404）へどう出るか → `test_routes_generate.py`
"""

import pytest

from app.infrastructure import job_registry
from app.infrastructure.job_registry import JOB_TTL_SECONDS


def test_a_new_job_is_queued_with_neither_result_nor_error():
    record = job_registry.get_job(job_registry.create_job())

    assert record is not None
    assert (record.status, record.result, record.error) == ("queued", None, None)


def test_every_new_job_gets_its_own_id():
    assert job_registry.create_job() != job_registry.create_job()


def test_an_id_that_was_never_handed_out_finds_nothing():
    assert job_registry.get_job("no-such-job") is None


def test_a_job_that_runs_and_finishes_carries_its_result():
    job_id = job_registry.create_job()

    job_registry.set_running(job_id)
    assert job_registry.get_job(job_id).status == "running"

    job_registry.set_done(job_id, {"routes": []})
    record = job_registry.get_job(job_id)
    assert (record.status, record.result) == ("done", {"routes": []})


def test_a_job_that_fails_carries_the_reason():
    job_id = job_registry.create_job()
    job_registry.set_running(job_id)

    job_registry.set_failed(job_id, "ルート生成に失敗しました")

    record = job_registry.get_job(job_id)
    assert (record.status, record.error) == ("failed", "ルート生成に失敗しました")


@pytest.mark.parametrize(
    "finish",
    [
        lambda job_id: job_registry.set_done(job_id, "result"),
        lambda job_id: job_registry.set_failed(job_id, "reason"),
    ],
    ids=["done", "failed"],
)
def test_a_finished_job_can_be_polled_for_the_whole_ttl_and_is_dropped_after_it(clock, finish):
    """保持時間は画面のポーリングの打ち切りと同じで、待っている画面が掃除済みのジョブを引かない。"""
    job_id = job_registry.create_job()
    finish(job_id)

    clock.tick(JOB_TTL_SECONDS)
    job_registry.create_job()
    assert job_registry.get_job(job_id) is not None

    clock.tick(1)
    job_registry.create_job()
    assert job_registry.get_job(job_id) is None


def test_a_job_still_running_is_never_dropped(clock):
    """ルート生成は数十秒かかり、走っている間に別の利用者がジョブを作っても消えない。"""
    queued = job_registry.create_job()
    running = job_registry.create_job()
    job_registry.set_running(running)

    clock.tick(JOB_TTL_SECONDS * 10)
    job_registry.create_job()

    assert job_registry.get_job(queued) is not None
    assert job_registry.get_job(running) is not None
