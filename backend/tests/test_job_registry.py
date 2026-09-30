"""`infrastructure/job_registry.py`——プロセス内の非同期ジョブ台帳。

ここで見ないもの:
- ジョブをHTTPへ出す層（202とjob_id・未知idの404・同時実行の上限） → `test_routes_generate.py`

**実時間を待たない。** 完了したジョブを何秒持つかは時計だけで決まるため、止めた時計（`clock`）を進めて見る。
"""

import time

import pytest

from app.infrastructure import job_registry


@pytest.fixture(autouse=True)
def empty_registry(monkeypatch, clock):
    """時計を止め、台帳を空から始める。台帳はモジュール大域なので、戻さないと他のテストへ漏れる。"""
    monkeypatch.setattr(job_registry, "_JOBS", {})


class TestRegisteringAJob:
    def test_a_new_job_is_queued(self):
        job_id = job_registry.create_job()

        assert job_registry.get_job(job_id).status == "queued"

    def test_a_job_id_nobody_registered_reads_as_nothing(self):
        """例外にすると、破棄済みのジョブを聞かれた側が404へ翻訳できない。"""
        assert job_registry.get_job("no-such-job") is None


class TestRecordingProgress:
    def test_a_started_job_is_running_and_not_yet_finished(self):
        job_id = job_registry.create_job()

        job_registry.set_running(job_id)

        record = job_registry.get_job(job_id)
        assert (record.status, record.finished_at) == ("running", None)

    def test_a_finished_job_carries_its_result(self, clock):
        job_id = job_registry.create_job()
        clock.tick(30)

        job_registry.set_done(job_id, {"routes": 3})

        record = job_registry.get_job(job_id)
        assert (record.status, record.result, record.finished_at) == ("done", {"routes": 3}, time.monotonic())

    def test_a_failed_job_carries_its_message(self, clock):
        job_id = job_registry.create_job()
        clock.tick(30)

        job_registry.set_failed(job_id, "ルート生成に失敗しました")

        record = job_registry.get_job(job_id)
        assert (record.status, record.error, record.finished_at) == (
            "failed",
            "ルート生成に失敗しました",
            time.monotonic(),
        )

    @pytest.mark.parametrize(
        "update",
        [
            pytest.param(job_registry.set_running, id="running"),
            pytest.param(lambda job_id: job_registry.set_done(job_id, "result"), id="done"),
            pytest.param(lambda job_id: job_registry.set_failed(job_id, "error"), id="failed"),
        ],
    )
    def test_writing_back_to_a_job_that_is_already_gone_does_nothing(self, update):
        """例外にすると、切り離されたタスクがそこで死に、掴んだ同時実行の枠が解放されない
        まま残る（プロセスを再起動するまでルート生成が細っていく）。
        """
        update("no-such-job")

        assert job_registry.get_job("no-such-job") is None


class TestForgettingFinishedJobs:
    def test_a_job_finished_longer_ago_than_the_retention_is_dropped(self, clock):
        job_id = job_registry.create_job()
        job_registry.set_done(job_id, "result")
        clock.tick(job_registry.JOB_TTL_SECONDS + 1)

        job_registry.create_job()

        assert job_registry.get_job(job_id) is None

    def test_a_job_finished_exactly_at_the_retention_is_still_there(self, clock):
        """フロントが取りに来る前に捨てると、出来上がったルートがそのまま404になる。"""
        job_id = job_registry.create_job()
        job_registry.set_done(job_id, "result")
        clock.tick(job_registry.JOB_TTL_SECONDS)

        job_registry.create_job()

        assert job_registry.get_job(job_id) is not None

    def test_a_job_that_has_not_finished_is_never_dropped(self, clock):
        """冷えたエリアの生成は数分かかる。走っている最中に捨てると、終わった頃には
        結果を書き戻す先も取りに行く先も無い。
        """
        job_id = job_registry.create_job()
        job_registry.set_running(job_id)
        clock.tick(job_registry.JOB_TTL_SECONDS * 10)

        job_registry.create_job()

        assert job_registry.get_job(job_id) is not None
