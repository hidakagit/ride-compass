"""取り直せない管理データのバックアップ（`backend/ops/admin_data_backup.sh`）が、最後に置けてから何時間たったか。

退避のスクリプトは本番VMのホストで動き、置けた時刻（UTC、ISO 8601）を1行だけ`MARKER_PATH`へ書く。ホストの
`/home/ubuntu/ridecompass-cache-data`がコンテナの`data/`（`deploy-backend.yml`の`-v`）なので、スクリプトの書き先と
この名前は揃える。止まっても知らせが来ないため、`/health`が経過時間を返し、見回りが読んで気づく。
"""

from datetime import datetime

from app.infrastructure.debug_log import log_throttled_warning
from app.infrastructure.tile_cache import DATA_DIR

#: 本番の読み手はこのファイルだけだが、テストがディスク（プロセス境界）の置き場を一時ディレクトリへ差し替えるために公開する
#: （testing.md「確かめる高さ」の例外）。置き場を引数で受けると、本番がいつも同じ置き場を渡すだけの、テストのための口になる。
MARKER_PATH = DATA_DIR / "admin_data_backup_at"


def backup_age_hours(now: datetime) -> float | None:
    """最後に置けてからの時間。記録が無い（手元の開発環境・まだ1回も置けていない本番）か、読めなければNone。"""
    try:
        placed_at = datetime.fromisoformat(MARKER_PATH.read_text().strip())
        if placed_at.tzinfo is None:
            raise ValueError(f"時差の無い時刻 {placed_at.isoformat()}")
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        # `/health`が毎回読むので、ここで落とすとそれを待つデプロイと見回りまで止まる。読めない理由はここでしか分からない。
        log_throttled_warning(
            "admin-data-backup", "管理データのバックアップの印のファイルが読めない path=%s error=%r", MARKER_PATH, exc
        )
        return None
    return (now - placed_at).total_seconds() / 3600
