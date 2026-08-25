"""app/infrastructure/database.pyのユニットテスト。

このモジュールはSupabase Session pooler/Transaction poolerの実機障害・command_timeout値を
巡る重い経緯を持つ接続設定を扱うが、これまで専用のテストが無かった。実DB接続は行わず
（create_async_engineは遅延接続のため、呼ぶだけではDBへ実際に接続しに行かない）、
以下の範囲のみを検証する:

- get_engine()/get_session_factory()、get_route_generation_engine()/
  get_route_generation_session_factory()それぞれのシングルトン性
- get_engine()系とget_route_generation_engine()系が別エンジン・別プールであること
  （command_timeoutの用途が異なるため、taskコメントの意図どおり分離されている必要がある）
- create_async_engineへ実際に渡されるpool_pre_ping/connect_args/接続先URLが、
  実装の意図（タイル配信用20秒・経路生成用180秒）と一致すること

get_engine()等はモジュールレベルのグローバル状態でシングルトンをキャッシュするため、
他のテストファイル（conftest.pyのroad_graph_engine等）や後続テストへ影響しないよう、
各テストの前後でmonkeypatchによりモジュール内部のキャッシュ変数を元の値へ戻す
（reset_database_singletonsフィクスチャ）。
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.infrastructure import database as database_module


@pytest.fixture(autouse=True)
def reset_database_singletons(monkeypatch):
    """各テストの直前にモジュールレベルのシングルトンキャッシュをNoneへ戻し、
    このテストファイルの中だけで新規にget_engine()等が呼ばれるようにする。
    monkeypatchはテスト終了時に元の値（他のテストファイルが既に作っていた
    エンジンがあればそれ）へ自動的に復元するため、他ファイルへの影響は無い。
    """
    monkeypatch.setattr(database_module, "_engine", None)
    monkeypatch.setattr(database_module, "_session_factory", None)
    monkeypatch.setattr(database_module, "_route_generation_engine", None)
    monkeypatch.setattr(database_module, "_route_generation_session_factory", None)


def _spy_on_create_async_engine(monkeypatch):
    """create_async_engineへ実際に渡された呼び出し引数を記録しつつ、本物の
    create_async_engineへ委譲するスパイに差し替える（遅延接続のため実DBへは繋がない）。
    戻り値はcalls（呼び出しごとの(args, kwargs)のリスト）。
    """
    calls: list[tuple[tuple, dict]] = []
    real_create_async_engine = database_module.create_async_engine

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return real_create_async_engine(*args, **kwargs)

    monkeypatch.setattr(database_module, "create_async_engine", spy)
    return calls


# --- シングルトン性 ---


def test_get_engine_is_singleton():
    engine1 = database_module.get_engine()
    engine2 = database_module.get_engine()

    assert engine1 is engine2
    assert isinstance(engine1, AsyncEngine)


def test_get_session_factory_is_singleton():
    factory1 = database_module.get_session_factory()
    factory2 = database_module.get_session_factory()

    assert factory1 is factory2
    assert isinstance(factory1, async_sessionmaker)


def test_get_session_factory_binds_to_get_engine_result():
    engine = database_module.get_engine()
    factory = database_module.get_session_factory()

    assert factory.kw["bind"] is engine


def test_get_route_generation_engine_is_singleton():
    engine1 = database_module.get_route_generation_engine()
    engine2 = database_module.get_route_generation_engine()

    assert engine1 is engine2
    assert isinstance(engine1, AsyncEngine)


def test_get_route_generation_session_factory_is_singleton():
    factory1 = database_module.get_route_generation_session_factory()
    factory2 = database_module.get_route_generation_session_factory()

    assert factory1 is factory2
    assert isinstance(factory1, async_sessionmaker)


def test_get_route_generation_session_factory_binds_to_route_generation_engine():
    engine = database_module.get_route_generation_engine()
    factory = database_module.get_route_generation_session_factory()

    assert factory.kw["bind"] is engine


def test_route_generation_engine_is_separate_from_tile_engine():
    # コメント（12-85行目）の意図どおり、タイル配信用（command_timeout=20）と
    # 経路生成用（command_timeout=180）は別エンジン・別コネクションプールであること。
    # 片方に緩めるともう片方の保護目的（ハング検知）が損なわれるため、混同していないか
    # を確認する回帰テスト。
    tile_engine = database_module.get_engine()
    route_engine = database_module.get_route_generation_engine()

    assert tile_engine is not route_engine
    assert tile_engine.pool is not route_engine.pool


# --- create_async_engineへ渡される接続設定 ---


def test_get_engine_passes_expected_connect_args(monkeypatch):
    calls = _spy_on_create_async_engine(monkeypatch)

    database_module.get_engine()

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == database_module.settings.database_url
    assert kwargs["pool_pre_ping"] is True
    # タイル配信用の20秒（route_generation用の180秒と混同していないことも兼ねて確認）。
    assert kwargs["connect_args"] == {"command_timeout": 20}


def test_get_route_generation_engine_passes_expected_connect_args(monkeypatch):
    calls = _spy_on_create_async_engine(monkeypatch)

    database_module.get_route_generation_engine()

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == database_module.settings.database_url
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["connect_args"] == {
        "command_timeout": database_module.ROUTE_GENERATION_COMMAND_TIMEOUT_SECONDS
    }
    assert database_module.ROUTE_GENERATION_COMMAND_TIMEOUT_SECONDS == 180


def test_get_engine_uses_database_url_from_settings_at_call_time(monkeypatch):
    # settings.database_url（DATABASE_URL環境変数由来）を切り替えると、get_engine()が
    # 生成するエンジンの接続先もそれに追従すること。
    monkeypatch.setattr(
        database_module.settings,
        "database_url",
        "postgresql+asyncpg://someone:pw@example.invalid:5432/otherdb",
    )
    calls = _spy_on_create_async_engine(monkeypatch)

    engine = database_module.get_engine()

    args, _kwargs = calls[0]
    assert args[0] == "postgresql+asyncpg://someone:pw@example.invalid:5432/otherdb"
    assert str(engine.url) == "postgresql+asyncpg://someone:***@example.invalid:5432/otherdb"
