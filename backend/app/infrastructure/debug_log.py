"""外部I/O(外部API・タイル/標高キャッシュ)イベントのログと集計。

ログレベルの方針(詳細は docs/logging.md):
- 成功イベントはDEBUG。settings.debug_modeがFalseの場合はmain.pyのlogging設定により
  実質出力されない(タイル系は毎分数百イベントになりうるため常時出力しない)。
- 失敗イベントはWARNINGで**常時**出力する。実運用(debug_mode=False)での障害調査が
  目的のため、debug_modeに関わらず出す。外部サービス障害時に同種の警告でログが
  埋まらないよう、カテゴリごとに固定窓(60秒)あたりWARN_BURST_PER_WINDOW件で抑制し、
  超過分は窓の切り替わり時に件数だけ報告する。
- 全イベントはカテゴリ単位でプロセス内カウンタに集計し、/api/debug/stats
  (api/routes.py)が呼び出し回数・エラー数・キャッシュヒット率・平均/最大所要時間を返す。
"""

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

logger = logging.getLogger("ridecompass.external")

WARN_WINDOW_SECONDS = 60.0
WARN_BURST_PER_WINDOW = 5

# 常時出力されるWARNINGにはユーザーの現在地由来の座標が含まれうるため、float値は
# 小数2桁(≈1km)へ丸めて出す。DEBUG(debug_mode時のみ)は調査精度を優先しそのまま出す。
ALWAYS_ON_FLOAT_PRECISION = 2

_lock = threading.Lock()
# category -> {"calls", "errors", "cache_hits", "cache_misses", "total_ms", "max_ms"}
_stats: dict[str, dict[str, int]] = {}
# category -> 429拒否数(record_rate_limit_rejection)
_rejections: dict[str, int] = {}
# category -> [window_start(monotonic), emitted_count, suppressed_count]
_warn_windows: dict[str, list[float]] = {}


def error_type_label(exc: BaseException) -> str:
    """例外を`/api/debug/stats`へ出しても安全な粗いラベルへ変換する。

    例外メッセージ・URL（クエリパラメータに座標が乗りうる）は含めず、クラス名と
    （httpxのHTTPStatusErrorなら）HTTPステータスコードのみを使う。呼び出し元は
    `fields["error"] = repr(exc)`（WARNINGログ用の詳細）と併せて
    `fields["error_type"] = error_type_label(exc)`（集計用の粗いラベル）を設定する。
    """
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if status_code is not None:
        return f"http_{status_code}"
    return type(exc).__name__


def _round_floats(value: object) -> object:
    """WARNINGログ用にfloat(座標等)を丸める。tuple/list/dictは再帰的に処理する。"""
    if isinstance(value, float):
        return round(value, ALWAYS_ON_FLOAT_PRECISION)
    if isinstance(value, (list, tuple)):
        return type(value)(_round_floats(v) for v in value)
    if isinstance(value, dict):
        return {k: _round_floats(v) for k, v in value.items()}
    return value


def _throttled_warning(category: str, message: str, *args: object) -> None:
    """カテゴリごとの固定窓レートで抑制しつつWARNINGを出す。"""
    emit = False
    suppression_notice: int | None = None
    with _lock:
        now = time.monotonic()
        window = _warn_windows.get(category)
        if window is None or now - window[0] >= WARN_WINDOW_SECONDS:
            if window is not None and window[2]:
                suppression_notice = int(window[2])
            window = [now, 0, 0]
            _warn_windows[category] = window
        if window[1] < WARN_BURST_PER_WINDOW:
            window[1] += 1
            emit = True
        else:
            window[2] += 1
    if suppression_notice is not None:
        logger.warning(
            "[%s] suppressed %d similar warnings in last %ds", category, suppression_notice, int(WARN_WINDOW_SECONDS)
        )
    if emit:
        logger.warning(message, *args)


def _record(category: str, elapsed_ms: int, fields: dict, error: bool) -> None:
    with _lock:
        stats = _stats.setdefault(
            category,
            {
                "calls": 0,
                "errors": 0,
                "cache_hits": 0,
                "cache_misses": 0,
                "total_ms": 0,
                "max_ms": 0,
                # 以下は「失敗の主な理由を推測する」ための追加集計。
                "error_types": {},
                "last_error_type": None,
                "last_error_at": None,
                "last_success_at": None,
                "retried_calls": 0,
                "retry_attempts_total": 0,
                "stale_fallback_used": 0,
            },
        )
        stats["calls"] += 1
        now_iso = datetime.now(UTC).isoformat()
        if error:
            stats["errors"] += 1
            error_type = fields.get("error_type") or "unknown"
            stats["error_types"][error_type] = stats["error_types"].get(error_type, 0) + 1
            stats["last_error_type"] = error_type
            stats["last_error_at"] = now_iso
        else:
            stats["last_success_at"] = now_iso
        cache = fields.get("cache")
        if cache == "hit":
            stats["cache_hits"] += 1
        elif cache == "miss":
            stats["cache_misses"] += 1
        # 429/ConnectTimeout等で再試行が発生した回数（最終的に成功した呼び出しも含む）。
        # 「まだ成功はしているが上流が混み始めている」兆候を502化する前に把握できる。
        retries = fields.get("retries")
        if retries:
            stats["retried_calls"] += 1
            stats["retry_attempts_total"] += retries
        # weather_client.pyのSTALE_FALLBACK的な「取得失敗時に古いキャッシュで代用した」回数。
        fallback = fields.get("fallback")
        if isinstance(fallback, str) and fallback.startswith("stale_cache"):
            stats["stale_fallback_used"] += 1
        stats["total_ms"] += elapsed_ms
        stats["max_ms"] = max(stats["max_ms"], elapsed_ms)


def log_throttled_warning(category: str, message: str, *args: object) -> None:
    """カテゴリ単位の抑制付きWARNING(公開版)。

    `log_external_call`で囲む形にできない失敗(キャッシュDBのクエリ失敗等、
    本処理へフォールバックして呼び出し自体は成功扱いになるもの)を、
    docs/logging.mdの「エラーは常時出す・ただし同種はカテゴリごとに毎分5件で抑制」
    の方針どおりに記録するための入口。
    """
    _throttled_warning(category, message, *args)


def record_rate_limit_rejection(category: str, client_id: str, limit: str) -> None:
    """429拒否を集計しつつ、抑制付きWARNINGで常時記録する。

    「ユーザーが429を食らい続けている」状況に運用側が気づけるようにするのが目的。
    limitは"120/min"・"concurrent=2"のような人間可読の上限表記。
    """
    with _lock:
        _rejections[category] = _rejections.get(category, 0) + 1
    _throttled_warning(f"ratelimit:{category}", "[ratelimit:%s] rejected client=%s limit=%s", category, client_id, limit)


def get_stats() -> dict:
    """/api/debug/stats用のプロセス内集計スナップショット。派生値(平均・ヒット率)もここで計算する。"""
    with _lock:
        external = {}
        for category, stats in sorted(_stats.items()):
            entry: dict[str, object] = dict(stats)
            entry["error_types"] = dict(stats["error_types"])
            entry["avg_ms"] = round(stats["total_ms"] / stats["calls"]) if stats["calls"] else 0
            lookups = stats["cache_hits"] + stats["cache_misses"]
            entry["cache_hit_rate"] = round(stats["cache_hits"] / lookups, 3) if lookups else None
            external[category] = entry
        return {"external": external, "rate_limit_rejections": dict(_rejections)}


def reset_stats() -> None:
    """集計とWARNING抑制窓をクリアする(テスト用)。"""
    with _lock:
        _stats.clear()
        _rejections.clear()
        _warn_windows.clear()


@contextmanager
def log_external_call(category: str, **fields: object) -> Iterator[dict]:
    """外部API呼び出し・キャッシュアクセスをカテゴリ単位でログ・集計する。

    `fields`はログ用の付帯情報(座標・パス等)。呼び出し元は`yield`されたdictに
    結果情報(cache="hit"/"miss", result="ok"/"error", status等)を追記してから抜けると、
    完了ログと統計にそれも反映される。失敗(例外、またはresult=="error")はWARNINGで
    常時出力し、成功はDEBUG(debug_mode時のみ実質出力)に留める。

    呼び出し元が例外を自前でcatchし、より詳細な文脈（対象ID等）付きの独自WARNINGを
    既に出している場合は、result="error"に加えてfields["warned"]=Trueを設定すると、
    ここでの二重WARNING出力だけ抑制しつつ/api/debug/statsのerror集計には正しく計上される
    （`_tile_from_repository`のように専用フィールド名でresultを避けて集計自体を
    諦める必要はない）。
    """
    started = time.monotonic()
    logger.debug("[%s] start %s", category, fields)
    try:
        yield fields
    except Exception as exc:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        # 呼び出し元が自前でfields["error_type"]を設定済み（例外を握りつぶしてNoneを返す
        # 系のクライアント）ならそれを優先する。ここまで伝播してきた例外（RoutingError等）は
        # ここで初めて分類する。
        fields.setdefault("error_type", error_type_label(exc))
        _record(category, elapsed_ms, fields, error=True)
        _throttled_warning(
            category, "[%s] error after %dms %s error=%r", category, elapsed_ms, _round_floats(fields), exc
        )
        raise
    else:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        error = fields.get("result") == "error"
        _record(category, elapsed_ms, fields, error=error)
        if error:
            if not fields.get("warned"):
                _throttled_warning(
                    category, "[%s] failed after %dms %s", category, elapsed_ms, _round_floats(fields)
                )
        else:
            logger.debug("[%s] done in %dms %s", category, elapsed_ms, fields)
