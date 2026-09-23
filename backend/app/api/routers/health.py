from fastapi import APIRouter

from app.config import settings
from app.infrastructure.msm_client import freshness as msm_freshness
from app.infrastructure.debug_log import get_stats
from app.version import STARTED_AT
from app.domain.strict_model import StrictModel

router = APIRouter()


# `infrastructure/debug_log.py: get_stats()`が組み立てるdictの実際の構造に対応する
# Pydanticモデル（OpenAPI経由でfrontendの型を生成する）。
class ExternalCallStatsResponse(StrictModel):
    calls: int
    errors: int
    cache_hits: int
    cache_misses: int
    total_ms: int
    max_ms: int
    avg_ms: int
    cache_hit_rate: float | None
    # 失敗の主な理由を推測するための追加集計。error_typesは
    # HTTPステータス（"http_429"）か例外クラス名のみの粗いラベルで、メッセージ本文・座標は含まない。
    error_types: dict[str, int]
    last_error_type: str | None
    last_error_at: str | None
    last_success_at: str | None
    retried_calls: int
    retry_attempts_total: int
    stale_fallback_used: int


class MsmFreshnessResponse(StrictModel):
    """予報（MSM）の同期がどれだけ新しいか。配信元が止まると古い予報を配り続けるため、
    ログ（WARNING）だけでなく外からも確認できるようにする。未同期のときはnull。"""

    last_run_at: str
    data_end_at: str
    run_age_hours: float
    remaining_hours: float
    healthy: bool


class DebugStatsResponse(StrictModel):
    commit: str | None
    started_at: str
    debug_mode: bool
    # カテゴリはinfrastructure/debug_log.pyのlog_external_call呼び出し元
    # （msm:read・weather:jma-tile・basemap:openfreemap・region:road-surface-tile等）に対応する。
    external: dict[str, ExternalCallStatsResponse]
    rate_limit_rejections: dict[str, int]
    msm: MsmFreshnessResponse | None


@router.get("/health")
def health() -> dict[str, str | None]:
    # commit（デプロイワークフローが注入するGIT_COMMIT）とstarted_at（プロセス起動時刻、
    # デプロイのたびに再起動されるため実質デプロイ時刻の目安）で、本番に実際に
    # デプロイされているコミットが最新かどうかを外部から確認できるようにする
    # （ローカル開発ではcommitはnullのまま。詳細はdocs/architecture/tech-stack.md参照）。
    return {
        "status": "ok",
        "commit": settings.git_commit,
        "started_at": STARTED_AT.isoformat(),
    }


@router.get("/api/debug/stats", response_model=DebugStatsResponse)
def debug_stats() -> DebugStatsResponse:
    # 外部API呼び出し・キャッシュの集計(カテゴリ別の呼び出し数/エラー数/ヒット率/所要時間)と
    # 429拒否数のプロセス内スナップショット(infrastructure/debug_log.py)。ログを目視で数えずに
    # キャッシュヒット率等を確認するための運用エンドポイント。集計値のみで秘匿情報や個別の
    # 座標を含まないため、debug_modeに関わらず/healthと同様に常時公開する。
    # プロセス再起動でリセットされる点に注意(started_atで起点を判別できる)。
    return DebugStatsResponse(
        commit=settings.git_commit,
        started_at=STARTED_AT.isoformat(),
        debug_mode=settings.debug_mode,
        msm=_msm_freshness_response(),
        **get_stats(),
    )


def _msm_freshness_response() -> MsmFreshnessResponse | None:
    current = msm_freshness()
    if current is None:
        return None
    return MsmFreshnessResponse(
        last_run_at=current.last_run_at.isoformat(),
        data_end_at=current.data_end_at.isoformat(),
        run_age_hours=round(current.run_age_hours, 1),
        remaining_hours=round(current.remaining_hours, 1),
        healthy=current.is_healthy,
    )
