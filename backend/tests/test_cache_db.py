import pytest

from app.infrastructure import cache_db


@pytest.fixture(autouse=True)
def use_temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cache_db, "DB_PATH", tmp_path / "test_cache.db")
    yield


async def test_elevation_cache_miss_returns_missing_sentinel():
    result = await cache_db.get_elevation(35.0, 139.0)

    assert result is cache_db.MISSING


async def test_elevation_cache_roundtrip():
    await cache_db.set_elevation(35.0, 139.0, 12.3)

    assert await cache_db.get_elevation(35.0, 139.0) == 12.3


async def test_elevation_cache_stores_none_as_a_hit_not_a_miss():
    await cache_db.set_elevation(35.0, 139.0, None)

    result = await cache_db.get_elevation(35.0, 139.0)

    assert result is None  # MISSINGではなく「キャッシュ済みの失敗」


async def test_elevation_cache_persists_across_separate_calls_simulating_restart():
    await cache_db.set_elevation(35.5, 139.5, 42.0)

    # 新しいDB接続を模擬（cache_dbはリクエストごとに新規sqlite3接続を張る実装のため、
    # プロセス再起動をまたいだ永続性はこの往復だけで十分に検証できる）
    result = await cache_db.get_elevation(35.5, 139.5)

    assert result == 42.0
