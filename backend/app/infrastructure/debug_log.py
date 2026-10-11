"""外部I/O(外部API・タイル/標高キャッシュ)イベントのログと集計
（ログレベルの方針は .claude/rules/logging.md）。

失敗はdebug_modeに関わらず常時WARNINGで出す。外部サービス障害時に同種の警告でログが
埋まらないよう、カテゴリごとに固定窓で抑制し、超過分は窓の切り替わり時に件数だけ報告する。
集計はプロセス内カウンタに持ち、`/api/debug/stats`が読む。

`log_external_call`で囲むと、成功はDEBUG、失敗（例外 or `fields["result"]="error"`）は抑制付きWARNINGが自動で出て、
`/api/debug/stats`の統計（呼び出し数・エラー数・キャッシュヒット率・平均/最大所要時間）にも自動集計される。

- カテゴリ名は`ドメイン:サービス名`形式（例: `msm:read`, `weather:jma-tile`, `basemap:openfreemap`）。
  `log_throttled_warning`のカテゴリも同じ形にする。
- キャッシュを挟む場合は`fields["cache"] = "hit" / "miss"`を必ず設定する。
- 失敗は`fields["result"] = "error"`で示す（例外を捕まえて倒すときは`mark_failed`）。集計が失敗として
  数えるのはこれと捕まえずに送り出した例外だけで、ほかは成功に数える。`"ok"`等の状態は、ログに
  残したいときだけ書く。HTTPステータスは`fields["status"]`、クォータ系ヘッダがあれば`fields["quota_remaining"]`等で残す。
"""

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import Field

from app.domain.strict_model import StrictModel

logger = logging.getLogger("ridecompass.external")

WARN_WINDOW_SECONDS = 60.0
WARN_BURST_PER_WINDOW = 5

# 常時出力されるWARNINGにはユーザーの現在地由来の座標が含まれうるため、float値は
# 小数2桁(≈1km)へ丸めて出す。DEBUG(debug_mode時のみ)は調査精度を優先しそのまま出す。
_ALWAYS_ON_FLOAT_PRECISION = 2


class LastError(StrictModel):
    """最後の失敗。種類と時刻は失敗のたびに一緒に書かれる。"""

    type: str
    at: str


class ExternalCallStats(StrictModel):
    """カテゴリ1つぶんの集計。プロセス内のカウンタそのものであり、`/api/debug/stats`の応答の形でもある。"""

    calls: int
    errors: int
    # ヒット率・平均の計算元。応答には載せない（画面は率と平均を読む）。
    cache_hits: int = Field(exclude=True)
    cache_misses: int = Field(exclude=True)
    total_ms: int = Field(exclude=True)
    max_ms: int
    avg_ms: int
    cache_hit_rate: float | None
    # 失敗の主な理由を推測するための追加集計。error_typesは
    # HTTPステータス（"http_429"）か例外クラス名のみの粗いラベルで、メッセージ本文・座標は含まない。
    error_types: dict[str, int]
    last_error: LastError | None


class StatsSnapshot(StrictModel):
    """`get_stats`が返すプロセス内集計の写し。"""

    # カテゴリは`log_external_call`の呼び出し元
    # （msm:read・weather:jma-tile・basemap:openfreemap・region:road-surface-tile等）に対応する。
    external: dict[str, ExternalCallStats]
    # カテゴリ → 429拒否数（`record_rate_limit_rejection`）。
    rate_limit_rejections: dict[str, int]


def _empty_stats() -> ExternalCallStats:
    return ExternalCallStats(
        calls=0,
        errors=0,
        cache_hits=0,
        cache_misses=0,
        total_ms=0,
        max_ms=0,
        avg_ms=0,
        cache_hit_rate=None,
        error_types={},
        last_error=None,
    )


_lock = threading.Lock()
_external_stats: dict[str, ExternalCallStats] = {}
# category -> 429拒否数(record_rate_limit_rejection)
_rate_limit_rejections: dict[str, int] = {}


@dataclass
class _WarnWindow:
    """抑制付きWARNINGのカテゴリごとの固定窓。"""

    start: float  # 窓の始まり（monotonic）
    emitted: int = 0
    suppressed: int = 0


_warn_windows: dict[str, _WarnWindow] = {}


def error_type_label(exc: BaseException) -> str:
    """例外を`/api/debug/stats`へ出しても安全な粗いラベルへ変換する。

    例外メッセージ・URL（クエリパラメータに座標が乗りうる）は含めず、クラス名と
    （httpxのHTTPStatusErrorなら）HTTPステータスコードのみを使う。
    """
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if status_code is not None:
        return f"http_{status_code}"
    return type(exc).__name__


def _round_floats(value: object) -> object:
    """WARNINGログ用にfloat(座標等)を丸める。tuple/list/dictは再帰的に処理する。"""
    if isinstance(value, float):
        return round(value, _ALWAYS_ON_FLOAT_PRECISION)
    if isinstance(value, (list, tuple)):
        return type(value)(_round_floats(v) for v in value)
    if isinstance(value, dict):
        return {k: _round_floats(v) for k, v in value.items()}
    return value


def _record(category: str, elapsed_ms: int, fields: dict, error: bool) -> None:
    with _lock:
        stats = _external_stats.get(category)
        if stats is None:
            stats = _external_stats[category] = _empty_stats()
        stats.calls += 1
        if error:
            stats.errors += 1
            error_type = fields.get("error_type") or "unknown"
            stats.error_types[error_type] = stats.error_types.get(error_type, 0) + 1
            stats.last_error = LastError(type=error_type, at=datetime.now(UTC).isoformat())
        cache = fields.get("cache")
        if cache == "hit":
            stats.cache_hits += 1
        elif cache == "miss":
            stats.cache_misses += 1
        stats.total_ms += elapsed_ms
        stats.max_ms = max(stats.max_ms, elapsed_ms)
        stats.avg_ms = round(stats.total_ms / stats.calls)
        lookups = stats.cache_hits + stats.cache_misses
        stats.cache_hit_rate = round(stats.cache_hits / lookups, 3) if lookups else None


def mark_failed(fields: dict, exc: BaseException) -> None:
    """`log_external_call`の中で例外を捕まえて既定値へ倒すときの、失敗の記録の入口。

    `log_external_call`を抜けるとき、結果が失敗としてカテゴリの集計（`error_types`）へ入り、
    抑制付きWARNINGが`fields`（対象のタイル・ID等）と例外を添えて出る。
    """
    fields["result"] = "error"
    fields["error"] = repr(exc)
    fields["error_type"] = error_type_label(exc)


def log_throttled_warning(category: str, message: str, *args: object) -> None:
    """カテゴリ単位の抑制付きWARNING（カテゴリごとの固定窓で数を絞る）。

    `log_external_call`で囲む形にできない失敗（本処理へフォールバックして呼び出し自体は
    成功扱いになるもの）を記録するための入口。
    """
    emit = False
    suppression_notice: int | None = None
    with _lock:
        now = time.monotonic()
        window = _warn_windows.get(category)
        if window is None or now - window.start >= WARN_WINDOW_SECONDS:
            if window is not None and window.suppressed:
                suppression_notice = window.suppressed
            window = _warn_windows[category] = _WarnWindow(start=now)
        if window.emitted < WARN_BURST_PER_WINDOW:
            window.emitted += 1
            emit = True
        else:
            window.suppressed += 1
    if suppression_notice is not None:
        logger.warning(
            "[%s] suppressed %d similar warnings in last %ds", category, suppression_notice, int(WARN_WINDOW_SECONDS)
        )
    if emit:
        logger.warning(message, *args)


def record_rate_limit_rejection(category: str, client_id: str, limit: str) -> None:
    """429拒否を集計しつつ、抑制付きWARNINGで常時記録する。

    「ユーザーが429を食らい続けている」状況に運用側が気づけるようにするのが目的。
    limitは"120/min"・"concurrent=2"のような人間可読の上限表記。
    """
    with _lock:
        _rate_limit_rejections[category] = _rate_limit_rejections.get(category, 0) + 1
    log_throttled_warning(f"ratelimit:{category}", "[ratelimit:%s] rejected client=%s limit=%s", category, client_id, limit)


def get_stats() -> StatsSnapshot:
    """/api/debug/stats用のプロセス内集計の写し。応答はロックの外で組み立てるため、
    実行中のカウンタと共有しない複製を返す。"""
    with _lock:
        return StatsSnapshot(
            external={category: stats.model_copy(deep=True) for category, stats in sorted(_external_stats.items())},
            rate_limit_rejections=dict(_rate_limit_rejections),
        )


@contextmanager
def log_external_call(category: str, **fields: object) -> Iterator[dict]:
    """外部API呼び出し・キャッシュアクセスをカテゴリ単位でログ・集計する。

    `fields`はログ用の付帯情報(座標・パス等)。呼び出し元は`yield`されたdictに
    結果情報(cache="hit"/"miss", result="ok"/"error", status等)を追記してから抜けると、
    完了ログと統計にそれも反映される。失敗(例外、またはresult=="error")はWARNINGで
    常時出力し、成功はDEBUG(debug_mode時のみ実質出力)に留める。例外を捕まえて既定値へ
    倒す呼び出し元は`mark_failed`で失敗を記録する。
    """
    started = time.monotonic()
    logger.debug("[%s] start %s", category, fields)
    try:
        yield fields
    except Exception as exc:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        fields["error_type"] = error_type_label(exc)
        _record(category, elapsed_ms, fields, error=True)
        log_throttled_warning(
            category, "[%s] error after %dms %s error=%r", category, elapsed_ms, _round_floats(fields), exc
        )
        raise
    else:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        error = fields.get("result") == "error"
        _record(category, elapsed_ms, fields, error=error)
        if error:
            log_throttled_warning(category, "[%s] failed after %dms %s", category, elapsed_ms, _round_floats(fields))
        else:
            logger.debug("[%s] done in %dms %s", category, elapsed_ms, fields)
