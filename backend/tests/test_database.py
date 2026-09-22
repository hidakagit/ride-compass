"""`infrastructure/database.py`——エンジンとセッションファクトリの組み立て。

ここで見ないもの:
- セッションを1リクエストへ配る側（`app/api/dependencies.py`）
- 接続先が実在するか・DDL（PostGISを使うテストと`create_tables`が持つ）

**実接続は張らない。** `create_async_engine`は遅延接続で、ここで作るエンジンはプールを
組み立てるだけである。記憶（モジュール大域）は`monkeypatch`で空にしてから見る
——作り直す側と使い回す側の両方を1回のテストで通すため。
"""

import pytest
from sqlalchemy.engine import make_url

from app.config import settings
from app.infrastructure import database

_MEMOS = (
    "_engine",
    "_session_factory",
    "_route_generation_engine",
    "_route_generation_session_factory",
)


@pytest.fixture
def forgotten(monkeypatch):
    """記憶を空にする（テストの終わりに元の値へ戻る）。"""
    for name in _MEMOS:
        monkeypatch.setattr(database, name, None)


def test_engine_is_built_once_per_process(forgotten):
    """呼ぶたびに作るとプールが増え、DBの接続上限を食い潰す。"""
    engine = database.get_engine()
    assert database.get_engine() is engine


def test_route_generation_has_its_own_engine(forgotten):
    """ルート生成とタイル配信でプールを共有すると、片方のコマンド上限がもう片方へ移る。"""
    route_engine = database.get_route_generation_engine()
    assert database.get_route_generation_engine() is route_engine
    assert route_engine is not database.get_engine()


def test_session_factories_bind_to_their_own_engine(forgotten):
    """束ね先を取り違えると、ルート生成のクエリがタイル配信側の短い上限で切られる。"""
    factory = database.get_session_factory()
    route_factory = database.get_route_generation_session_factory()

    assert database.get_session_factory() is factory
    assert database.get_route_generation_session_factory() is route_factory
    assert factory.kw["bind"] is database.get_engine()
    assert route_factory.kw["bind"] is database.get_route_generation_engine()


def test_engines_follow_the_configured_database_url(forgotten, monkeypatch):
    """接続先は設定から取る（固定の接続先を埋め込まない）。"""
    url = "postgresql+asyncpg://user_a:pass_a@host_a:5432/db_a"
    monkeypatch.setattr(settings, "database_url", url)

    assert database.get_engine().url == make_url(url)
    assert database.get_route_generation_engine().url == make_url(url)
