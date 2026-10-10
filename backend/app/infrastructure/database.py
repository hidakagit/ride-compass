from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

# DBへ届かない・DBが答えないときに出る例外。読み取りを空へ倒す箇所はこれだけを捕まえ、
# 実装の誤り（TypeError・AttributeError等）は捕まえずに500で表へ出す。
# - SQLAlchemyError: 接続を張る段階と実行中の失敗（asyncpgの例外はDBAPIErrorへ訳される）とプールの待ち切れ
# - OSError: 接続の拒否・切断と、command_timeoutのTimeoutError（実行中のasyncpgのタイムアウトは訳されない）
DB_UNAVAILABLE_ERRORS: tuple[type[Exception], ...] = (SQLAlchemyError, OSError)

# エンジン（コネクションプール）は系統ごとにアプリ全体で1つだけ生成し、セッションファクトリが持つ。
# create_async_engineは遅延接続のため、DBが実際に起動していなくてもこの時点では失敗しない。
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _new_session_factory(command_timeout: float) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        settings.database_url, pool_pre_ping=True, connect_args={"command_timeout": command_timeout}
    )
    return async_sessionmaker(engine, expire_on_commit=False)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        # command_timeout: 路面タイルのバースト（短時間の連続パン/ズーム）でDB側が混雑すると
        # クエリが数分返らないことがあり、上限が無いとリクエストが無期限にハングする。
        # ここで出るTimeoutErrorはDB_UNAVAILABLE_ERRORSに入るため、タイル配信は空タイルへ劣化する。
        _session_factory = _new_session_factory(20)
    return _session_factory


# ルート生成と、全表走査を伴う管理APIの集計が使う。生成は1件の間ずっと1本の接続を持つため、
# タイル配信とはプールを分ける。上限が長いのは集計がタイル配信用の20秒では最後まで走らない
# ためで、生成のクエリ（取込範囲の判定・確定した経路の形の取り直し）はこの上限に近づかない。
ROUTE_GENERATION_COMMAND_TIMEOUT_SECONDS = 180

_route_generation_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_route_generation_session_factory() -> async_sessionmaker[AsyncSession]:
    global _route_generation_session_factory
    if _route_generation_session_factory is None:
        _route_generation_session_factory = _new_session_factory(ROUTE_GENERATION_COMMAND_TIMEOUT_SECONDS)
    return _route_generation_session_factory


async def dispose_engines() -> None:
    """プロセス終了時に`process_resources.py: close_process_resources`から呼ぶ。次の取得で作り直す。"""
    global _session_factory, _route_generation_session_factory
    for factory in (_session_factory, _route_generation_session_factory):
        if factory is not None:
            await factory.kw["bind"].dispose()
    _session_factory = _route_generation_session_factory = None
