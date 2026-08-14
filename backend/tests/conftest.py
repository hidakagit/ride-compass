import os

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infrastructure.road_graph_models import Base
from app.infrastructure.road_graph_repository import RoadGraphRepository

# road_graph_repository.pyのPostGIS統合テスト専用の接続先。開発機で稼働中の実DB
# (ridecompass, backend/.envのDATABASE_URLが指す先)とは別のテスト専用DBを使う
# (docs/osm-pbf-import.md関連の進行中データに触れないため)。ローカルでのみ実行する
# 前提で、環境変数TEST_DATABASE_URLで上書き可能にしておく。
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ridecompass:ridecompass@localhost:5432/ridecompass_test",
)


@pytest_asyncio.fixture
async def road_graph_session():
    """ridecompass_test DBに全テーブルを作成し、テストごとに空の状態から始めて
    テスト後に後始末（truncate）するセッションを提供する。
    """
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001
        await engine.dispose()
        pytest.skip(f"ridecompass_test DBに接続できないためスキップ: {exc}")

    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
        await session.rollback()

    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())

    await engine.dispose()


@pytest_asyncio.fixture
async def road_graph_repository(road_graph_session: AsyncSession) -> RoadGraphRepository:
    return RoadGraphRepository(road_graph_session)
