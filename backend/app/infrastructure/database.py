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
        # RenderはSupabaseのDirect Connection（IPv6専用）へ発信できない
        # （実機でOSError(101, 'Network is unreachable')を確認）ため、本番はSupabaseの
        # Transaction pooler（Supavisor、IPv4対応）経由に接続する運用に変更した。
        # Transaction poolerは呼び出しごとに物理コネクションが変わりうるため、asyncpgの
        # デフォルト動作（サーバー側prepared statementをコネクション単位でキャッシュする）
        # と噛み合わず、別の物理コネクションに使い回されたキャッシュ済みstatement名を
        # 参照してエラーになりうる。statement_cache_size=0でこのキャッシュ自体を無効化する
        # （Direct Connection/ローカルPG18に対しても安全に使える設定のため常時適用する）。
        _engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            connect_args={"statement_cache_size": 0},
        )
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
