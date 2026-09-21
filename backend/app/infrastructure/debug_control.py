"""debug_modeのランタイム切替・直近ログの保持。

切替は`.env`を書き換えない。プロセス再起動・再デプロイのたびに安全側
（`settings.debug_mode`の環境変数値、既定false）へ戻り、「戻し忘れ」が起きない。
"""

import logging
from collections import deque

from app.config import settings
from app.infrastructure.request_log import LOG_FORMAT, JstLogFormatter, RequestIdLogFilter

# 直近何件のログレコードをメモリに保持するか。1レコード=数百バイト程度のため、
# 1000件でも数百KB規模に収まる（プロセス再起動でリセットされる、既存の
# /api/debug/statsの集計と同じ「プロセス内スナップショット」という性質）。
_RING_BUFFER_MAX_SIZE = 1000

class _LogRingBufferHandler(logging.Handler):
    """直近`_RING_BUFFER_MAX_SIZE`件の整形済みログ行を、レベル（`record.levelno`）と
    セットでメモリ上に保持するハンドラ。`get_recent_logs`の`min_level`フィルタが
    整形済み文字列を`[WARNING]`のような部分文字列でパースせずに済むよう、
    数値のログレベルを別途保持する。"""

    def __init__(self, maxlen: int) -> None:
        super().__init__()
        self._buffer: deque[tuple[int, str]] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        self._buffer.append((record.levelno, self.format(record)))

    def snapshot(self) -> list[tuple[int, str]]:
        return list(self._buffer)


_ring_buffer_handler = _LogRingBufferHandler(_RING_BUFFER_MAX_SIZE)
_ring_buffer_handler.setFormatter(JstLogFormatter(LOG_FORMAT))
_ring_buffer_handler.addFilter(RequestIdLogFilter())


def install_ring_buffer_handler() -> None:
    """ルートロガーへリングバッファハンドラを追加する（main.py起動時に1回呼ぶ）。"""
    root_logger = logging.getLogger()
    if _ring_buffer_handler not in root_logger.handlers:
        root_logger.addHandler(_ring_buffer_handler)


def set_debug_mode(enabled: bool) -> bool:
    """debug_modeをランタイムで切り替え、切り替え後の状態を返す。"""
    settings.debug_mode = enabled
    logging.getLogger().setLevel(logging.DEBUG if enabled else logging.INFO)
    return settings.debug_mode


def get_recent_logs(limit: int | None = None, contains: str | None = None, min_level: int | None = None) -> list[str]:
    """リングバッファから直近ログを取得する（古い順のまま、末尾が最新）。

    `min_level`はPython標準の`logging`と同じ「このレベル以上」、`contains`は部分一致。
    併用するとAND条件になり、`limit`は絞り込んだ後の末尾N件を指す。
    """
    entries = _ring_buffer_handler.snapshot()
    if min_level is not None:
        entries = [(levelno, line) for levelno, line in entries if levelno >= min_level]
    lines = [line for _levelno, line in entries]
    if contains:
        lines = [line for line in lines if contains in line]
    if limit is not None:
        lines = lines[-limit:]
    return lines
