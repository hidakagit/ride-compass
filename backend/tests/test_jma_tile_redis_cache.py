import pytest

from app.infrastructure import jma_tile_redis_cache


class FakeRedis:
    """jma_tile_redis_cache.pyが使うコマンド（get/set）だけを実装したフェイク
    （他のRedisキャッシュのテストと同じパターン）。"""

    def __init__(self, raise_on_get=None, raise_on_set=None):
        self.store: dict[str, str] = {}
        self._raise_on_get = raise_on_get
        self._raise_on_set = raise_on_set

    async def get(self, key):
        if self._raise_on_get:
            raise self._raise_on_get
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        if self._raise_on_set:
            raise self._raise_on_set
        self.store[key] = value


async def test_set_then_get_roundtrip_preserves_binary_content(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(jma_tile_redis_cache, "get_redis_client_or_none", lambda: fake)

    path = "bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/land/11/1818/805.png"
    content = b"\x89PNG\x00\x01\x02not-actually-a-real-png"

    await jma_tile_redis_cache.set(path, content, "image/png")
    result = await jma_tile_redis_cache.get(path)

    assert result == (content, "image/png")


async def test_get_returns_none_when_not_cached(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(jma_tile_redis_cache, "get_redis_client_or_none", lambda: fake)

    result = await jma_tile_redis_cache.get("bosai/jmatile/data/risk/.../never-set.png")

    assert result is None


async def test_get_fails_open_on_redis_exception(monkeypatch):
    fake = FakeRedis(raise_on_get=ConnectionError("boom"))
    monkeypatch.setattr(jma_tile_redis_cache, "get_redis_client_or_none", lambda: fake)

    result = await jma_tile_redis_cache.get("bosai/jmatile/data/risk/.../x.png")

    assert result is None


async def test_set_fails_open_on_redis_exception_without_raising(monkeypatch):
    fake = FakeRedis(raise_on_set=ConnectionError("boom"))
    monkeypatch.setattr(jma_tile_redis_cache, "get_redis_client_or_none", lambda: fake)

    # 例外を送出せず静かに失敗すること（書き込み失敗はレスポンス自体の成否に関与しない）。
    await jma_tile_redis_cache.set("bosai/jmatile/data/risk/.../x.png", b"content", "image/png")


async def test_get_returns_none_when_redis_client_unavailable(monkeypatch):
    monkeypatch.setattr(jma_tile_redis_cache, "get_redis_client_or_none", lambda: None)

    result = await jma_tile_redis_cache.get("bosai/jmatile/data/risk/.../x.png")

    assert result is None


async def test_set_no_ops_when_redis_client_unavailable(monkeypatch):
    monkeypatch.setattr(jma_tile_redis_cache, "get_redis_client_or_none", lambda: None)

    # 例外を送出しないこと。
    await jma_tile_redis_cache.set("bosai/jmatile/data/risk/.../x.png", b"content", "image/png")


async def test_get_returns_none_for_corrupted_entry(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(jma_tile_redis_cache, "get_redis_client_or_none", lambda: fake)
    fake.store[jma_tile_redis_cache._key("bosai/jmatile/data/risk/.../x.png")] = "not-valid-json"

    result = await jma_tile_redis_cache.get("bosai/jmatile/data/risk/.../x.png")

    assert result is None


async def test_set_not_found_then_get_returns_tile_not_found_sentinel(monkeypatch):
    # 改善計画T605: 恒久404を確認したタイルは、次回`get`で`TILE_NOT_FOUND`センチネルが
    # 返ることを確認する（実際のタイル内容[tuple]・未キャッシュ[None]とは別の3値目）。
    fake = FakeRedis()
    monkeypatch.setattr(jma_tile_redis_cache, "get_redis_client_or_none", lambda: fake)
    path = "bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/land/11/1818/805.png"

    await jma_tile_redis_cache.set_not_found(path)
    result = await jma_tile_redis_cache.get(path)

    assert result is jma_tile_redis_cache.TILE_NOT_FOUND
    assert isinstance(result, jma_tile_redis_cache.TileNotFound)


async def test_set_not_found_fails_open_on_redis_exception_without_raising(monkeypatch):
    fake = FakeRedis(raise_on_set=ConnectionError("boom"))
    monkeypatch.setattr(jma_tile_redis_cache, "get_redis_client_or_none", lambda: fake)

    # 例外を送出せず静かに失敗すること（set()と同じfail-open方針）。
    await jma_tile_redis_cache.set_not_found("bosai/jmatile/data/risk/.../x.png")


async def test_set_not_found_no_ops_when_redis_client_unavailable(monkeypatch):
    monkeypatch.setattr(jma_tile_redis_cache, "get_redis_client_or_none", lambda: None)

    # 例外を送出しないこと。
    await jma_tile_redis_cache.set_not_found("bosai/jmatile/data/risk/.../x.png")
