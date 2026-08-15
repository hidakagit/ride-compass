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
        # （実機でOSError(101, 'Network is unreachable')を確認）ため、本番は
        # SupabaseのSession pooler（IPv4対応、ポート5432）経由に接続する。
        #
        # Transaction pooler（ポート6543）は当初検討したが、asyncpgがサーバー側
        # prepared statementを`__asyncpg_stmt_N__`という連番名で明示的に発行する実装のため、
        # 呼び出しごとに物理コネクションが変わりうるTransaction poolerでは「別クライアントが
        # 同じ物理コネクションに残した同名のprepared statement」と衝突しうる
        # （DuplicatePreparedStatementError、実機で確認）。SQLAlchemyの公式ドキュメントは
        # prepared_statement_name_func（UUID採番）での回避を案内しているが、手元の
        # SQLAlchemy 2.0.36ではconnect_args経由で渡してもこの関数が一切呼ばれず
        # （実機で検証済み）効果がなかった。Session poolerはクライアントごとに専有の
        # 物理コネクションを保持するため、この種の衝突が構造的に起きず、追加設定なしで
        # 動作する（実機で同時10接続を検証済み）。
        # command_timeout: Supabaseが遠隔リージョン（ムンバイ）にあり密集タイルのクエリは
        # 実測7〜8秒かかるが、路面タイルのバースト（短時間の連続パン/ズーム）でDB/pooler側が
        # 混雑すると数分単位でクエリが返らなくなることを実機で確認した（最悪194秒）。
        # タイムアウト無しだとリクエストが無期限にハングし続けるため、正常系（〜8秒）に
        # 余裕を持たせつつ上限を設ける。ここで発生するTimeoutErrorはExceptionのサブクラス
        # のため、region_service.pyの既存のtry/exceptで捕捉され空タイルへ安全に劣化する。
        _engine = create_async_engine(
            settings.database_url, pool_pre_ping=True, connect_args={"command_timeout": 20}
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory
