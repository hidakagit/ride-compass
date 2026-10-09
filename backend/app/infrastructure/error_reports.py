"""本番で起きたエラーの記録（backendのERRORのログと、画面から届いた報告）。外から定期に読み、あれば知らせる。

置き場はディスクの1ファイルに1件1行。プロセスの中だけに持つとデプロイの再起動で消え、次に読む前に失われる。
本番のホストの`/home/ubuntu/ridecompass-cache-data`がコンテナの`data/`（`deploy-backend.yml`の`-v`）なので、
入れ替えをまたいで残る。1件には時刻・出どころ・種類・名前・画面のパス・リクエストIDだけを持ち、例外の文・
座標・本文・ヘッダー・接続元を持たない——読む口（`/api/debug/errors`）は認証なしで公開する。例外の文とスタックは
ログにだけ残り、リクエストIDで引ける。
"""

import logging
import os
import threading
from datetime import UTC, datetime
from typing import Literal

from asgi_correlation_id import correlation_id
from pydantic import ValidationError

from app.domain.strict_model import StrictModel
from app.infrastructure.debug_log import log_throttled_warning
from app.infrastructure.tile_cache import DATA_DIR

#: テストがディスク（プロセス境界）の置き場を一時ディレクトリへ差し替えるために公開する（testing.md「確かめる高さ」の (c)）。
REPORTS_PATH = DATA_DIR / "error_reports.jsonl"

#: 切り詰めたあとに残す件数。外から読む間隔（1時間）に起きる件数より十分多く、ファイルが際限なく育たない大きさ。
KEEP_REPORTS = 1000
#: これを超えたら`KEEP_REPORTS`件へ切り詰める。1件はおよそ200バイトなので、残す件数の数倍で切る。
TRIM_BYTES = 1_000_000

_lock = threading.Lock()


class ErrorReport(StrictModel):
    at: datetime
    source: Literal["backend", "frontend"]
    #: backendはロガーの名前、画面は報告の種類（`api/routers/error_reports.py: ClientErrorReport.kind`）。
    kind: str
    #: 例外の型・失敗したAPIの分類等の粗いラベル。無ければ`-`。
    name: str
    page: str | None
    request_id: str | None


def record(report: ErrorReport) -> None:
    """1件を足す。書けなくても投げない（記録はエラーの起きた処理の付け足しで、その処理を止めない）。"""
    line = report.model_dump_json() + "\n"
    try:
        with _lock:
            REPORTS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with REPORTS_PATH.open("a", encoding="utf-8") as file:
                file.write(line)
            if REPORTS_PATH.stat().st_size > TRIM_BYTES:
                _trim()
    except OSError as exc:
        # ERRORで出すと、この記録を呼ぶハンドラへ戻ってくる。
        log_throttled_warning("error-reports:write", "エラーの記録を書けない path=%s error=%r", REPORTS_PATH, exc)


def _trim() -> None:
    kept = REPORTS_PATH.read_text(encoding="utf-8").splitlines(keepends=True)[-KEEP_REPORTS:]
    temporary = REPORTS_PATH.with_suffix(".tmp")
    temporary.write_text("".join(kept), encoding="utf-8")
    os.replace(temporary, REPORTS_PATH)


def reports_since(since: datetime) -> list[ErrorReport]:
    """`since`以後の記録を古い順に返す。読めない行は飛ばす（書きかけの行・前の形の行）。"""
    try:
        with _lock:
            lines = REPORTS_PATH.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    reports = []
    for line in lines:
        try:
            report = ErrorReport.model_validate_json(line)
        except ValidationError:
            continue
        if report.at >= since:
            reports.append(report)
    return reports


class _ErrorLogHandler(logging.Handler):
    """ERROR以上のログ1行を、backendのエラー1件として記録する。"""

    def emit(self, log: logging.LogRecord) -> None:
        exc_type = log.exc_info[0] if log.exc_info else None
        record(
            ErrorReport(
                at=datetime.fromtimestamp(log.created, UTC),
                source="backend",
                kind=log.name,
                name=exc_type.__name__ if exc_type is not None else "-",
                page=None,
                request_id=correlation_id.get(),
            )
        )


_error_log_handler = _ErrorLogHandler(logging.ERROR)


def install_error_log_handler() -> None:
    """ルートロガーへ記録のハンドラを足す（main.py起動時に1回呼ぶ）。"""
    root_logger = logging.getLogger()
    if _error_log_handler not in root_logger.handlers:
        root_logger.addHandler(_error_log_handler)
