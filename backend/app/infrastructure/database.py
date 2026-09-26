import asyncpg
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

# DBへ届かない・DBが答えないときに出る例外。読み取りを空へ倒す箇所はこれだけを捕まえ、
# 実装の誤り（TypeError・AttributeError等）は捕まえずに500で表へ出す。
# - SQLAlchemyError: 実行中の失敗（asyncpgの例外はDBAPIErrorへ訳される）とプールの待ち切れ
# - OSError: 接続の拒否・切断と、command_timeoutのTimeoutError（実行中のasyncpgのタイムアウトは訳されない）
# - asyncpg.PostgresError・InterfaceError: 接続を張る段階の失敗（接続数の上限・認証等）。
#   SQLAlchemyは接続時にasyncpgを直接呼ぶため、DBAPIErrorへ訳されずに届く
DB_UNAVAILABLE_ERRORS: tuple[type[Exception], ...] = (
    SQLAlchemyError, OSError, asyncpg.PostgresError, asyncpg.InterfaceError,
)

# エンジンはアプリ全体で1つだけ生成する（SQLAlchemyの標準的な使い方。内部でコネクション
# プールを管理するため、リクエストごとに新規接続を作る必要はない）。
# create_async_engineは遅延接続のため、DBが実際に起動していなくてもこの時点では失敗しない。
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        # command_timeout: 路面タイルのバースト（短時間の連続パン/ズーム）でDB側が混雑すると
        # クエリが数分返らないことがあり、上限が無いとリクエストが無期限にハングする。
        # ここで出るTimeoutErrorはDB_UNAVAILABLE_ERRORSに入るため、タイル配信は空タイルへ劣化する。
        _engine = create_async_engine(
            settings.database_url, pool_pre_ping=True, connect_args={"command_timeout": 20}
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


# ルート生成と、全表走査を伴う管理APIの集計が使う。生成は1件の間ずっと1本の接続を持つため、
# タイル配信とはプールを分ける。上限が長いのは集計がタイル配信用の20秒では最後まで走らない
# ためで、生成のクエリ（取込範囲の判定・確定した経路の形の取り直し）はこの上限に近づかない。
ROUTE_GENERATION_COMMAND_TIMEOUT_SECONDS = 180

_route_generation_engine: AsyncEngine | None = None
_route_generation_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_route_generation_engine() -> AsyncEngine:
    global _route_generation_engine
    if _route_generation_engine is None:
        _route_generation_engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            connect_args={"command_timeout": ROUTE_GENERATION_COMMAND_TIMEOUT_SECONDS},
        )
    return _route_generation_engine


def get_route_generation_session_factory() -> async_sessionmaker[AsyncSession]:
    global _route_generation_session_factory
    if _route_generation_session_factory is None:
        _route_generation_session_factory = async_sessionmaker(
            get_route_generation_engine(), expire_on_commit=False
        )
    return _route_generation_session_factory
