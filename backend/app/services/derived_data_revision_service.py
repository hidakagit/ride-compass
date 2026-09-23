"""ディスクキャッシュを、DBの派生データ世代へ追随させる。

バッチ（`app/batch/`）は本番VM上の別コンテナで走り、backendは再起動しない。バッチが
派生データを書き直したことにbackendが気づく瞬間が他に無いため、**材料を使う経路から
TTL付きで`derived_data_meta.revision`を読み直す**（pull）。

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
from app.infrastructure import graph_material_cache, tile_score_matrix_cache
from app.infrastructure.database import DB_UNAVAILABLE_ERRORS

logger = logging.getLogger("ridecompass.derived_data_revision")

#: 次にDBを読み直してよくなる時刻（`time.monotonic()`）。プロセス内のみ。
_next_check_at: float = 0.0

#: 最後に読んだ派生データ世代。配信するタイルの世代（`tile_version_service`）が読む。
#: Noneは「まだ読めていない」で、読めるまで配信側は世代なしの印を使う。
_current_revision: int | None = None


def reset_for_tests() -> None:
    global _next_check_at, _current_revision
    _next_check_at = 0.0
    _current_revision = None


def current_revision() -> int | None:
    """最後に読んだ派生データ世代。読めていなければNone。"""
    return _current_revision


async def ensure_caches_match_db(repository, *, force: bool = False) -> None:
    """TTLが切れていればDBの世代を読み直し、ディスクキャッシュを追随させる。

    材料が作り直されているとスコア行列も古いため、材料を消したときは同時に消す
    （スコア行列は材料から作られる。`tile_score_matrix_cache`のdocstring参照）。
    `force`はTTLを待たず必ず確かめたい場合に使う（現在の呼び出し元はテストのみ）。
    """
    global _next_check_at
    now = time.monotonic()
    if not force and now < _next_check_at:
        return
    _next_check_at = now + settings.derived_data_revision_check_interval_seconds

    try:
        revision = await repository.get_derived_data_revision()
    except DB_UNAVAILABLE_ERRORS:
        # この確認はキャッシュの鮮度を保つためのもので、ルート生成そのものの前提ではない。
        # ここで落とすと、世代を読めないだけでルートが返せなくなる。TTLは先に進めてあるため
        # ログが溢れることもない。
        logger.warning("派生データ世代を読めませんでした（キャッシュの追随を見送ります）", exc_info=True)
        return
    global _current_revision
    _current_revision = revision
    if not graph_material_cache.sync_disk_cache_with_derived_data_revision(revision):
        return
    tile_score_matrix_cache.clear()
    # **焼き済みのタイルはここで消さない。** 世代はタイルのキャッシュパスに入っている
    # （`tile_version_service.served_tile_version`）ため、世代が変われば別の鍵になり、
    # 古い中身は誰からも引かれなくなる。`tile_cache.clear_all()`は基礎地図・標高タイルまで
    # 巻き添えにするうえ、公開GETの中でイベントループを止めて`rmtree`することになる
    # （`docs/conventions/caching.md`「全消しは運用操作としてのみ残す」）。引かれなくなったものは
    # `prune_to_size_limit`が古い順に回収する。
    logger.info("派生データ世代の変化を検知しキャッシュを破棄しました revision=%s", revision)
