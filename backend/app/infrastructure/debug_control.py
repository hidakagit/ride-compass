"""debug_modeのランタイム切替・直近ログの保持（改善計画T379）。

`settings.debug_mode`（config.py）は元々プロセス起動時に一度だけ読まれる環境変数で、
唯一の用途は`main.py`が`logging.basicConfig`のログレベルを決めることだけだった
（grep実測、他に分岐箇所なし）。本番でこれを一時的にONにするにはSSH→env file編集→
コンテナ再作成が必要で、T318の調査で運用上のボトルネックと判明した。ここでは
(1) ルートロガーのレベルをプロセスを再起動せず書き換える関数と、(2) DEBUGログを
本番のdocker logsを見ずにHTTP経由で取得できるよう直近ログを保持するリングバッファ
ハンドラを提供する。管理API（api/routers/debug_admin.py）からのみ呼ばれる想定。

切替は`.env`を書き換えない（永続化しない）。プロセス再起動・再デプロイのたびに
自動的に安全側（settings.debug_modeの環境変数値、既定false）へ戻る——SSH手順の
「戻し忘れ」のようなリスクを構造的に避けるための意図的な設計。
"""

import logging
from collections import deque

from app.config import settings
from app.infrastructure.request_log import RequestIdLogFilter

# 直近何件のログレコードをメモリに保持するか。1レコード=数百バイト程度のため、
# 1000件でも数百KB規模に収まる（プロセス再起動でリセットされる、既存の
# /api/debug/statsの集計と同じ「プロセス内スナップショット」という性質）。
_RING_BUFFER_MAX_SIZE = 1000

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s [req:%(request_id)s]: %(message)s"


class _LogRingBufferHandler(logging.Handler):
    """直近`_RING_BUFFER_MAX_SIZE`件の整形済みログ行をメモリ上に保持するハンドラ。"""

    def __init__(self, maxlen: int) -> None:
        super().__init__()
        self._buffer: deque[str] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        self._buffer.append(self.format(record))

    def snapshot(self) -> list[str]:
        return list(self._buffer)


_ring_buffer_handler = _LogRingBufferHandler(_RING_BUFFER_MAX_SIZE)
_ring_buffer_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
_ring_buffer_handler.addFilter(RequestIdLogFilter())


def install_ring_buffer_handler() -> None:
    """ルートロガーへリングバッファハンドラを追加する（main.py起動時に1回呼ぶ）。

    既存のbasicConfig由来のハンドラ（標準出力、Dockerのjson-fileドライバへ渡る）は
    そのまま残し、追加のハンドラとして装着するだけなので既存の常時ログ出力には
    影響しない。
    """
    root_logger = logging.getLogger()
    if _ring_buffer_handler not in root_logger.handlers:
        root_logger.addHandler(_ring_buffer_handler)


def set_debug_mode(enabled: bool) -> bool:
    """debug_modeをランタイムで切り替える。`.env`は書き換えない（上記docstring参照）。

    ルートロガーのレベルとsettings.debug_mode（`/health`・`/api/debug/stats`が
    参照する現在値）の両方を更新し、戻り値として現在の状態を返す。
    """
    settings.debug_mode = enabled
    logging.getLogger().setLevel(logging.DEBUG if enabled else logging.INFO)
    return settings.debug_mode


def get_recent_logs(limit: int | None = None, contains: str | None = None) -> list[str]:
    """リングバッファから直近ログを取得する。

    `contains`を指定すると部分一致でフィルタしてから`limit`を適用する（T318の
    ユースケース: `distance filter rejected`だけを抜き出す等）。`limit`は「フィルタ後の
    末尾N件」を返す（古い順のまま、末尾が最新）。
    """
    lines = _ring_buffer_handler.snapshot()
    if contains:
        lines = [line for line in lines if contains in line]
    if limit is not None:
        lines = lines[-limit:]
    return lines
