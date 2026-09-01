import os

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infrastructure import redis_client, tile_score_matrix_cache
from app.infrastructure.road_graph_models import Base
from app.infrastructure.road_graph_repository import RoadGraphRepository
from tests.realistic_axis_fixtures import realistic_axis_definitions


@pytest.fixture(autouse=True)
def _reset_redis_circuit_breaker():
    """redis_client.pyのサーキットブレーカー状態をテスト間でリセットする（改善計画T387）。

    グローバル状態（プロセス内モジュール変数）のため、Redis疎通不能をシミュレートする
    テストが1つでも実行されると、リセットせずに残る限り無関係な後続テスト（正常系の
    フェイクRedisを使うテスト）まで「クールダウン中」と誤判定されてしまう。
    """
    redis_client.reset_circuit_breaker()
    yield
    redis_client.reset_circuit_breaker()


@pytest.fixture(autouse=True)
def _clear_tile_score_matrix_cache():
    """tile_score_matrix_cache（タイル単位の静的Edge×公開軸スコア行列、改善計画T536。
    旧axis_score_cache[T534]の後継）もプロセス内グローバル状態のため、
    _reset_redis_circuit_breakerと同じ理由でテスト間の汚染を防ぐ。

    多くのテストが"e1"・"e-ab"のような慣用的なedge_idを、テストごとに異なる材料
    （way_tags・elevation_attribute等）で使い回す。本番のタイル座標は実データ由来で
    そのタイル内のEdge材料と一意に対応するため、風以外の軸別スコアをタイル単位で
    キャッシュしてよい設計が成立するが、テストの慣用edge_id・タイル座標はその前提を
    満たさないため、クリアしないと別テストが積んだキャッシュを誤って再利用してしまう
    （旧axis_score_cache時代にtest_prepare_applies_precomputed_gradient_to_search_costで
    実際に発生・発覚した問題と同種）。
    """
    tile_score_matrix_cache.clear()
    yield
    tile_score_matrix_cache.clear()


@pytest.fixture(autouse=True, scope="session")
def _realistic_axis_definitions():
    """全テストへ本番相当の14軸（tests/realistic_axis_fixtures.py参照）を用意する
    （改善計画T350のcode-reviewで指摘: 以前は各テストファイルへ同じautouseフィクスチャを
    個別にコピペしており、①付け忘れたファイルはAXIS_DEFINITIONSが空のまま
    weights={}・軸スコアNoneという退化した軸システムでも例外なくgreenになる構造的な
    サイレント失敗リスクがあり、②同じ内容の辞書コピーを235件超のテスト関数それぞれで
    毎回clear/update していた無駄もあった。ここへ集約しsession scope
    （REALISTIC_AXIS_DEFINITIONSは不変の静的データのため、テストごとに作り直す必要がない）
    にすることで両方を解消する。

    個々のテストファイル（test_axis_registry_service.py・test_evaluation_bulk.py・
    test_axis_catalog_routes.py等）が持つ、自前でAXIS_DEFINITIONSを一時的に書き換えて
    元に戻すフィクスチャ/コンテキストマネージャはこれと独立に動作し続ける——それらは
    「テスト開始時点の中身」をスナップショットして復元するだけなので、その中身が
    このセッションフィクスチャ由来のREALISTIC_AXIS_DEFINITIONSであっても問題ない。
    """
    with realistic_axis_definitions():
        yield


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
