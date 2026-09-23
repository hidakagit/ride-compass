"""汎用の非同期ジョブレジストリ（プロセス内メモリのみ）。

数十秒かかりうる処理をバックグラウンドジョブ化し、フロントがポーリングで完了を待てる
ようにする。**単一プロセスデプロイ前提**で、ワーカーを複数にすると他プロセスの
ジョブが見えない。

`result`が`Any`なのは、呼び出し元（`api/routers/routes.py`）の型をこのモジュールが
知らずに済ませるため（循環importの回避）。
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

JobStatus = Literal["queued", "running", "done", "failed"]

# 完了したジョブを保持する時間。掃除は次の`create_job()`のついでに行う（`rate_limiter.py`と
# 同じ方式で、定期タスクを持たない）。フロントはこれを生成物`route-generate-config.json`から
# 受け取り、ポーリングの打ち切りに使う——短くすると待機上限も一緒に縮む。
# **動かす前に docs/modules/frontend/route-settings-and-results.md「生成を待つ時間・投げる
# 回数の根拠」を読む**。
JOB_TTL_SECONDS = 600.0


@dataclass
class JobRecord:
    job_id: str
    status: JobStatus = "queued"
    created_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    result: Any = None
    error: str | None = None


_JOBS: dict[str, JobRecord] = {}


def create_job() -> str:
    """新規ジョブを"queued"状態で登録し、job_idを返す。"""
    _purge_expired()
    job_id = uuid.uuid4().hex
    _JOBS[job_id] = JobRecord(job_id=job_id)
    return job_id


def get_job(job_id: str) -> JobRecord | None:
    return _JOBS.get(job_id)


def set_running(job_id: str) -> None:
    record = _JOBS.get(job_id)
    if record is not None:
        record.status = "running"


def set_done(job_id: str, result: Any) -> None:
    record = _JOBS.get(job_id)
    if record is not None:
        record.status = "done"
        record.result = result
        record.finished_at = time.monotonic()


def set_failed(job_id: str, error: str) -> None:
    record = _JOBS.get(job_id)
    if record is not None:
        record.status = "failed"
        record.error = error
        record.finished_at = time.monotonic()


def _purge_expired() -> None:
    now = time.monotonic()
    expired = [
        job_id
        for job_id, record in _JOBS.items()
        if record.finished_at is not None and now - record.finished_at > JOB_TTL_SECONDS
    ]
    for job_id in expired:
        del _JOBS[job_id]
