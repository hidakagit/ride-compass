from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

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
        # ここで出るTimeoutErrorはExceptionのサブクラスのため、region_service.pyの
        # try/exceptが捕捉して空タイルへ安全に劣化する。
        _engine = create_async_engine(
            settings.database_url, pool_pre_ping=True, connect_args={"command_timeout": 20}
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


# ルート生成専用（GraphService/ElevationAttributeService）。未splitエリアへの初回タッチは
# 生データからの再構築を伴い、タイル配信用の20秒では途中でキャンセルされる。タイル配信側の
# ハング検知を損なわないよう、上限を緩めるのではなく別エンジン・別プールへ分ける。
# 180秒は観測された最悪値（密集都心部の20km初回split、175.8秒）に余裕を持たせた値で、
# 正常系は数秒〜数十秒のため、ここに達すること自体が異常のシグナルになる。
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
