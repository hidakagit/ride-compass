"""汎用の非同期ジョブレジストリ（プロセス内メモリのみ、改善計画T265）。

`POST /api/routes/generate`の冷パス（未splitな新規エリアへの初回アクセス、数十秒〜
最大316秒[T248実測]）をバックグラウンドジョブ化し、フロントがポーリングで完了を
待てるようにするために新設した。単一プロセスデプロイ前提（`services/
axis_registry_service.py`のpush型更新と同じ前提）で、複数ワーカー構成では他プロセスの
ジョブが見えない制約が残るが、現状の単一プロセスデプロイでは問題にならない。

ルート生成に特化させず、状態遷移とTTLベースの掃除だけを持つ汎用モジュールにしてある
（`api/routers/routes.py`がこのモジュールの型を知る一方、本モジュールはルート生成の
型を一切知らない——`result`は`Any`型で呼び出し側が中身を決める。これにより
`routes.py`との循環importを避ける）。
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

JobStatus = Literal["queued", "running", "done", "failed"]

# 完了（done/failed）から10分経過したジョブは次のcreate_job()呼び出し時に掃除する
# （定期タスクを新設せず、`infrastructure/rate_limiter.py`の
# `dict + time.monotonic() + 呼び出し時_sweep`と同じ「呼ばれたついでに掃除」方式。
# 改善計画T386、T265コードレビュー指摘9件目: 以前は`debug_control.py`のリングバッファと
# 同じ方式と書いていたが、そちらは`deque(maxlen=...)`による件数ベースの暗黙FIFO破棄で
# TTL・時刻判定を持たず、構造が異なる参照ミスだった）。ジョブ生成頻度に対して十分長く、
# ポーリング側の最大待機時間[frontend routeApi.tsのMAX_POLL_DURATION_MS=360秒]より
# 十分長い値。
_JOB_TTL_SECONDS = 600.0


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
        if record.finished_at is not None and now - record.finished_at > _JOB_TTL_SECONDS
    ]
    for job_id in expired:
        del _JOBS[job_id]
