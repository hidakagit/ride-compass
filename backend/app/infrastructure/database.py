from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

# エンジンはアプリ全体で1つだけ生成する（SQLAlchemyの標準的な使い方。内部でコネクション
# プールを管理するため、cache_db.pyのようにリクエストごとに新規接続を作る必要はない）。
# create_async_engineは遅延接続のため、DBが実際に起動していなくてもこの時点では失敗しない。
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPIのDepends用。現時点ではどのAPIエンドポイントもこれを使っていない
    （Road Graph関連機能はapi/routes.pyへ未接続、Phase1-5からの方針を踏襲）。
    将来接続する際の配線ポイントとして用意している。
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session
