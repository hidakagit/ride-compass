from fastapi import APIRouter

from app.config import settings
from app.infrastructure.debug_log import get_stats
from app.version import STARTED_AT

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str | None]:
    # commit（Renderが自動注入するRENDER_GIT_COMMIT）とstarted_at（プロセス起動時刻、
    # デプロイのたびに再起動されるため実質デプロイ時刻の目安）で、Render上に実際に
    # デプロイされているコミットが最新かどうかを外部から確認できるようにする
    # （ローカル開発ではcommitはnullのまま。詳細はdocs/architecture.md参照）。
    return {
        "status": "ok",
        "commit": settings.render_git_commit,
        "started_at": STARTED_AT.isoformat(),
    }


@router.get("/api/debug/stats")
def debug_stats() -> dict:
    # 外部API呼び出し・キャッシュの集計(カテゴリ別の呼び出し数/エラー数/ヒット率/所要時間)と
    # 429拒否数のプロセス内スナップショット(infrastructure/debug_log.py)。ログを目視で数えずに
    # キャッシュヒット率等を確認するための運用エンドポイント。集計値のみで秘匿情報や個別の
    # 座標を含まないため、debug_modeに関わらず/healthと同様に常時公開する。
    # プロセス再起動でリセットされる点に注意(started_atで起点を判別できる)。
    return {
        "commit": settings.render_git_commit,
        "started_at": STARTED_AT.isoformat(),
        "engine": settings.routing_engine,
        "debug_mode": settings.debug_mode,
        **get_stats(),
    }
