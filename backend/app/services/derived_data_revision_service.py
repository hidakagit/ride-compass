"""DBの派生データと生データの世代を、配信するタイルの世代のために読み直す。

バッチ（`app/batch/`）は本番VM上の別コンテナで走り、backendは再起動しない。バッチが
派生データや生データを書き直したことにbackendが気づく瞬間が他に無いため、**タイルの世代を決める
経路からTTL付きで2つの世代（`derived_data_meta.py: get_revisions`）を読み直す**（pull）。

pullにした理由: バッチからbackendを呼ぶ（push）と、バッチがURLと認証を知る必要があり、
その呼び出しが失敗したときに「古いまま気づかない」という元の問題へ静かに戻る。専用の
定期ジョブを足さないのは、起動時ジョブを増やすと一過性の起動失敗を招くため。

古いままになりうる窓はTTL分だけ残る。バッチ自体が数十分かかるため、数分の遅れは運用上の
差にならない（docs/conventions/caching.mdの「判断をキャッシュしてよい条件」——入力が全て鍵にあり、
遅れる方向が安全側で、TTLが許容窓から導かれている）。
"""

import logging
import time

from app.config import settings
from app.infrastructure.database import DB_UNAVAILABLE_ERRORS
from app.infrastructure.derived_data_meta import DataRevisions

logger = logging.getLogger("ridecompass.derived_data_revision")

#: 次にDBを読み直してよくなる時刻（`time.monotonic()`）。プロセス内のみ。
_next_check_at: float = 0.0

#: 最後に読んだ世代。配信するタイルの世代（`tile_version_service`）が読む。
#: Noneは「まだ読めていない」で、読めるまで配信側は世代なしの印を使う。
_last_read_revisions: DataRevisions | None = None


def current_revisions() -> DataRevisions | None:
    """最後に読んだ世代。読めていなければNone。"""
    return _last_read_revisions


async def refresh_current_revisions(repository) -> None:
    """TTLが切れていればDBの世代を読み直す。"""
    global _next_check_at, _last_read_revisions
    now = time.monotonic()
    if now < _next_check_at:
        return
    _next_check_at = now + settings.derived_data_revision_check_interval_seconds

    try:
        revisions = await repository.get_data_revisions()
    except DB_UNAVAILABLE_ERRORS:
        # 世代を読めないだけで配信を止めない。TTLは先に進めてあるためログが溢れることもない。
        logger.warning("データの世代を読めませんでした（前回の値のまま配信します）", exc_info=True)
        return
    if revisions != _last_read_revisions:
        logger.info("データの世代を読みました derived=%s imported=%s", revisions.derived, revisions.imported)
    _last_read_revisions = revisions
