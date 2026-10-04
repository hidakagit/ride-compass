"""`infrastructure/database.py`——PostGISへの接続の口（2系統のセッションファクトリ）と、DB障害として捕まえる例外。

エンジンはプロセス大域に1つずつ作られるので、テストごとに作る前の状態から始め、作ったエンジンを閉じる。
接続先は`config.py: settings`の`database_url`を差し替えて与える（DBへは届かない宛先にする）。

ここで見ないもの:
- どのリクエストがどちらの系統を使うか → `api/dependencies.py`を通る各ルーターのテスト
- DB障害の例外を受けて空・503へ倒すこと → 倒す側のテスト（例: `test_gradient_way_service.py`・`test_region_service.py`）
- 実行中の待ちの上限（`command_timeout`）。上限は通常の系統で20秒あり、届かせるにはその時間だけ待つ
"""

import pytest
from sqlalchemy import text

from app.config import settings
from app.infrastructure import database

# 何も聞いていないポート。接続は張る段階ですぐに断られる。
UNREACHABLE_DATABASE_URL = "postgresql+asyncpg://user:password@127.0.0.1:1/unreachable"

FACTORIES = [database.get_session_factory, database.get_route_generation_session_factory]


@pytest.fixture
async def unreachable_database(monkeypatch):
    monkeypatch.setattr(settings, "database_url", UNREACHABLE_DATABASE_URL)
    for name in ("session_factory", "route_generation_session_factory"):
        monkeypatch.setattr(database, name, None)
    yield
    for factory in (database.session_factory, database.route_generation_session_factory):
        if factory is not None:
            await factory.kw["bind"].dispose()


@pytest.mark.usefixtures("unreachable_database")
def test_each_factory_is_built_once_and_the_two_do_not_share_a_pool():
    """ルート生成は1件の間ずっと接続を持つので、タイル配信と接続を取り合わない。"""
    tiles, route_generation = (factory() for factory in FACTORIES)

    assert database.get_session_factory() is tiles
    assert database.get_route_generation_session_factory() is route_generation
    assert tiles.kw["bind"] is not route_generation.kw["bind"]


@pytest.mark.usefixtures("unreachable_database")
@pytest.mark.parametrize("factory", FACTORIES)
async def test_a_database_that_cannot_be_reached_raises_an_error_counted_as_unavailable(factory):
    with pytest.raises(database.DB_UNAVAILABLE_ERRORS):
        async with factory()() as session:
            await session.execute(text("SELECT 1"))
