import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger("ridecompass.external")


@contextmanager
def log_external_call(category: str, **fields: object) -> Iterator[dict]:
    """外部API呼び出し・タイルキャッシュアクセスをカテゴリ単位でDEBUGログに残す。

    `fields`はログ用の付帯情報（座標・パス等）。呼び出し元は`yield`されたdictに
    結果情報（cache="hit"/"miss", result="ok"/"error"等）を追記してから抜けると、
    完了ログにそれも含まれる。settings.debug_modeがFalseの場合はmain.pyで
    このロガーのレベルがINFO以上に設定されるため、実質的にログは出力されない。
    """
    started = time.monotonic()
    logger.debug("[%s] start %s", category, fields)
    try:
        yield fields
    except Exception as exc:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        logger.debug("[%s] error after %dms %s error=%r", category, elapsed_ms, fields, exc)
        raise
    else:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        logger.debug("[%s] done in %dms %s", category, elapsed_ms, fields)
