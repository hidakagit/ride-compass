import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text

from app.api.admin_auth import require_admin_basic_auth
from app.config import settings
from app.infrastructure.database import get_engine
from app.infrastructure.debug_log import get_stats
from app.infrastructure.migrate import list_pending_migrations
from app.services.road_graph_engine import RoadGraphEngine
from app.version import STARTED_AT

logger = logging.getLogger("ridecompass.health")

router = APIRouter()


# `infrastructure/debug_log.py: get_stats()`が組み立てるdictの実際の構造に対応する
# Pydanticモデル（OpenAPI経由でfrontendの型を生成する）。
class ExternalCallStatsResponse(BaseModel):
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


class DebugStatsResponse(BaseModel):
    commit: str | None
    started_at: str
    engine: str
    debug_mode: bool
    # カテゴリはinfrastructure/debug_log.pyのlog_external_call呼び出し元
    # （weather:open-meteo・basemap:openfreemap・region:road-surface-tile等）に対応する。
    external: dict[str, ExternalCallStatsResponse]
    rate_limit_rejections: dict[str, int]

# migration適用状況・データ投入バッチの最終実行状況・主要テーブル行数を1エンドポイントで
# 確認できるようにする。「デプロイの反映確認」（/healthのcommit）と同じ思想の、DB版の反映確認。
#
# *_import_runsテーブル（osm_import_runs/accident_import_runs/designation_import_runs）は
# いずれも「1回のバッチ実行につき1行以上、status(running|succeeded|failed)・started_at・
# finished_atを持つ」同型（各モデルのdocstring参照）のため、直近1行を取るクエリを共通化する。
_IMPORT_RUN_TABLES = {
    "osm": "osm_import_runs",
    "accident": "accident_import_runs",
    "designation": "designation_import_runs",
}

# import_runsが指す生データ・派生データの主要テーブル。0件やテーブル欠落自体が
# 「バッチが本番で一度も走っていない」の直接的なシグナルになる（実例:
# designation_attributesがtable無し→migration未適用、route_designations=0件→取込未実行）。
_KEY_TABLES = (
    "osm_raw_ways",
    "osm_raw_pois",
    "road_edges",
    "route_designations",
    "designation_attributes",
    "accident_points",
)


@router.get("/health")
def health() -> dict[str, str | None]:
    # commit（デプロイワークフローが注入するGIT_COMMIT）とstarted_at（プロセス起動時刻、
    # デプロイのたびに再起動されるため実質デプロイ時刻の目安）で、本番に実際に
    # デプロイされているコミットが最新かどうかを外部から確認できるようにする
    # （ローカル開発ではcommitはnullのまま。詳細はdocs/architecture.md参照）。
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
        # ルート生成エンジンは常にRoadGraphEngine（他エンジンは撤去済み）。SystemStatusPanel.tsxが
        # 表示するためキー自体は残す。RoadGraphEngine.engine_nameを正本として参照し、
        # routes.py側（RouteGenerateResponse.engine）とのリテラル重複による将来の乖離を避ける。
        engine=RoadGraphEngine.engine_name,
        debug_mode=settings.debug_mode,
        **get_stats(),
    )


async def _table_row_count(conn, table: str) -> int | None:
    # to_regclassでテーブル存在確認してから数える（無ければNone。migration未適用の
    # 直接的なシグナルになるため、存在しないテーブルを例外扱いにしない）。
    exists = await conn.scalar(text("SELECT to_regclass(:t) IS NOT NULL"), {"t": table})
    if not exists:
        return None
    return await conn.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608 tはハードコード辞書由来、外部入力なし


async def _latest_import_run(conn, table: str) -> dict | None:
    exists = await conn.scalar(text("SELECT to_regclass(:t) IS NOT NULL"), {"t": table})
    if not exists:
        return None
    row = (
        await conn.execute(
            text(f"SELECT status, started_at, finished_at FROM {table} ORDER BY started_at DESC LIMIT 1")  # noqa: S608
        )
    ).first()
    if row is None:
        return {"status": None, "started_at": None, "finished_at": None}  # テーブルはあるが0行
    status, started_at, finished_at = row
    return {
        "status": status,
        "started_at": started_at.isoformat() if started_at else None,
        "finished_at": finished_at.isoformat() if finished_at else None,
    }


@router.get("/api/debug/db-status", dependencies=[Depends(require_admin_basic_auth)])
async def db_status() -> dict:
    """本番DB(または任意環境)がコード上の期待（migration適用済み・データ投入バッチ実行済み）
    に追いついているかを1回のリクエストで確認できる診断エンドポイント。

    `road_graph_use_repository=false`（DBなし構成）のときは接続を試みず、その旨だけ返す。
    DB接続自体に失敗した場合もエラーで落とさず、WARNINGログと共にreachable=falseを返す
    （docs/logging.mdの「エラーは常時WARNING以上」方針。/healthと違い読み取り専用の
    診断用途のため、DB障害時にHTTP 500にする必要はない）。認可境界の理由は
    docs/modules/backend/cross-cutting-infrastructure.md「運用エンドポイント」節参照。
    """
    if not settings.road_graph_use_repository:
        return {"commit": settings.git_commit, "database_configured": False}

    try:
        async with get_engine().connect() as conn:
            pending_migrations = await list_pending_migrations(get_engine())
            import_runs = {
                key: await _latest_import_run(conn, table) for key, table in _IMPORT_RUN_TABLES.items()
            }
            table_row_counts = {table: await _table_row_count(conn, table) for table in _KEY_TABLES}
    except Exception as exc:  # noqa: BLE001 診断エンドポイントはDB障害でも500にせず可視化する
        logger.warning("db-status診断のPostGIS読み取りに失敗 error=%r", exc)
        return {
            "commit": settings.git_commit,
            "database_configured": True,
            "reachable": False,
            "error": repr(exc),
        }

    return {
        "commit": settings.git_commit,
        "database_configured": True,
        "reachable": True,
        "pending_migrations": pending_migrations,
        "import_runs": import_runs,
        "table_row_counts": table_row_counts,
    }
