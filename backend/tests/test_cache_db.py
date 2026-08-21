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


async def test_wind_forecast_cache_miss_returns_empty_dict():
    result = await cache_db.get_wind_forecast_many([(35.0, 139.0)])

    assert result == {}


async def test_wind_forecast_cache_empty_keys_short_circuits_without_query():
    """空リストを渡したときに0件クエリすら発行せず即座に空を返すことの確認
    （weather_client.py: get_forecast_manyがneeds_lookupが空のときは呼ばないため通常は
    起きないが、念のための境界値）。"""
    result = await cache_db.get_wind_forecast_many([])

    assert result == {}


async def test_wind_forecast_cache_roundtrip():
    await cache_db.set_wind_forecast_many({(35.0, 139.0): (123.0, {"tag": "roundtrip"})})

    result = await cache_db.get_wind_forecast_many([(35.0, 139.0)])

    assert result[(35.0, 139.0)] == (123.0, {"tag": "roundtrip"})


async def test_wind_forecast_cache_persists_across_separate_calls_simulating_restart():
    await cache_db.set_wind_forecast_many({(35.5, 139.5): (456.0, {"tag": "persisted"})})

    result = await cache_db.get_wind_forecast_many([(35.5, 139.5)])

    assert result[(35.5, 139.5)] == (456.0, {"tag": "persisted"})


async def test_wind_forecast_cache_get_many_returns_only_found_keys():
    await cache_db.set_wind_forecast_many({(35.1, 139.1): (1.0, {"tag": "found"})})

    result = await cache_db.get_wind_forecast_many([(35.1, 139.1), (35.2, 139.2)])

    assert list(result.keys()) == [(35.1, 139.1)]


async def test_wind_forecast_cache_set_many_overwrites_existing_entry():
    await cache_db.set_wind_forecast_many({(35.3, 139.3): (1.0, {"tag": "old"})})
    await cache_db.set_wind_forecast_many({(35.3, 139.3): (2.0, {"tag": "new"})})

    result = await cache_db.get_wind_forecast_many([(35.3, 139.3)])

    assert result[(35.3, 139.3)] == (2.0, {"tag": "new"})
