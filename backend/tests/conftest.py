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


# ローカル環境では新規DB接続の確立自体に1〜2秒かかる（実測、asyncpg接続確立コスト。
# localhost/127.0.0.1どちらでも同程度でDNS起因ではない）。以前はテスト関数ごとに
# エンジンを新規作成しており、規模の大きいtest_road_graph_repository.py（約80件）
# だけで2分近く溶けていた。asyncpgの接続はイベントループに束縛されテスト関数ごとの
# イベントループをまたいで使い回せないため、エンジンと（それが乗る）イベントループを
# ファイル（モジュール）単位に広げ、ファイル内の全テストで1本の接続を使い回す。
# これを使うテストファイル側は `pytestmark = pytest.mark.asyncio(loop_scope="module")`
# を付けてイベントループのスコープを合わせる必要がある。


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def road_graph_engine():
    """テストファイル単位で使い回すエンジン。PostGIS拡張の有効化とテーブル一式
    （8テーブル、GiST空間インデックス込み）の作成もこの中で1回だけ行う。
    """
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # noqa: BLE001
        await engine.dispose()
        pytest.skip(f"ridecompass_test DBに接続できないためスキップ: {exc}")

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="module")
async def road_graph_session(road_graph_engine) -> AsyncSession:
    """テストごとに空の状態から始めて後始末（truncate）するセッションを提供する。"""
    async with AsyncSession(road_graph_engine, expire_on_commit=False) as session:
        yield session
        await session.rollback()

    async with road_graph_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


@pytest_asyncio.fixture(loop_scope="module")
async def road_graph_repository(road_graph_session: AsyncSession) -> RoadGraphRepository:
    return RoadGraphRepository(road_graph_session)
