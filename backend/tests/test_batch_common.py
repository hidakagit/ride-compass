"""`batch/common.py`——SQLAlchemy用のURLをasyncpgのDSNへ読み替えること。

ここで見ないもの:
- ssl指定の無いURL（ドライバ指定を外すだけ） → テスト用DBへ`asyncpg_dsn`で繋ぐ全部のテスト（`conftest.py`等）
"""

from app.batch.common import asyncpg_dsn


def test_asyncpg_dsn_normalizes_driver_and_ssl_param():
    assert (
        asyncpg_dsn("postgresql+asyncpg://u:p@db.example.com:5432/postgres?ssl=require")
        == "postgresql://u:p@db.example.com:5432/postgres?sslmode=require"
    )
