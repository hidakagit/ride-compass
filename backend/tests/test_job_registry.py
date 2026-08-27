import time

from app.infrastructure import job_registry


def test_create_job_starts_as_queued():
    job_id = job_registry.create_job()

    record = job_registry.get_job(job_id)

    assert record is not None
    assert record.status == "queued"
    assert record.result is None
    assert record.error is None


def test_get_job_returns_none_for_unknown_job_id():
    assert job_registry.get_job("does-not-exist") is None


def test_set_running_transitions_status():
    job_id = job_registry.create_job()

    job_registry.set_running(job_id)

    assert job_registry.get_job(job_id).status == "running"


def test_set_done_stores_result_and_finished_at():
    job_id = job_registry.create_job()

    job_registry.set_done(job_id, {"routes": []})

    record = job_registry.get_job(job_id)
    assert record.status == "done"
    assert record.result == {"routes": []}
    assert record.finished_at is not None


def test_set_failed_stores_error_and_finished_at():
    job_id = job_registry.create_job()

    job_registry.set_failed(job_id, "boom")

    record = job_registry.get_job(job_id)
    assert record.status == "failed"
    assert record.error == "boom"
    assert record.finished_at is not None


def test_set_running_done_failed_are_noop_for_unknown_job_id():
    # 未知のjob_id（TTL経過で既に掃除された、typo等）に対する状態更新はKeyError等では
    # 落ちず、単に無視される（バックグラウンドジョブ側の防御的な呼び出しを安全にする）。
    job_registry.set_running("does-not-exist")
    job_registry.set_done("does-not-exist", "result")
    job_registry.set_failed("does-not-exist", "error")


def test_purge_expired_removes_old_finished_jobs_on_create(monkeypatch):
    job_id = job_registry.create_job()
    job_registry.set_done(job_id, "result")
    # TTLを経過させるため、finished_atを実際に古い時刻へ書き換える
    # （_JOB_TTL_SECONDS分待つ実時間テストは避ける）。
    record = job_registry.get_job(job_id)
    record.finished_at = time.monotonic() - job_registry._JOB_TTL_SECONDS - 1

    job_registry.create_job()  # create_job()内のパージをトリガーする

    assert job_registry.get_job(job_id) is None


def test_purge_expired_keeps_recently_finished_jobs():
    job_id = job_registry.create_job()
    job_registry.set_done(job_id, "result")

    job_registry.create_job()

    assert job_registry.get_job(job_id) is not None


def test_purge_expired_keeps_unfinished_jobs_regardless_of_age(monkeypatch):
    # queued/running（finished_at is None）はTTL経過の判定対象外
    # （ジョブが実際に終わるまでは掃除しない）。
    job_id = job_registry.create_job()
    record = job_registry.get_job(job_id)
    record.created_at = time.monotonic() - job_registry._JOB_TTL_SECONDS - 1

    job_registry.create_job()

    assert job_registry.get_job(job_id) is not None
