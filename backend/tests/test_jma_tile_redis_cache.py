
from app.infrastructure import jma_tile_redis_cache
from tests.fake_redis import FakeRedis


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


async def test_set_empty_then_get_returns_empty_tile_sentinel(monkeypatch):
    # 描くものが無いと確認したタイルは、次回`get`で`EMPTY_TILE`センチネルが
    # 返ることを確認する（実際のタイル内容[tuple]・未キャッシュ[None]とは別の3値目）。
    fake = FakeRedis()
    monkeypatch.setattr(jma_tile_redis_cache, "get_redis_client_or_none", lambda: fake)
    path = "bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/land/11/1818/805.png"

    await jma_tile_redis_cache.set_empty(path)
    result = await jma_tile_redis_cache.get(path)

    assert result is jma_tile_redis_cache.EMPTY_TILE
    assert isinstance(result, jma_tile_redis_cache.EmptyTile)


async def test_set_empty_fails_open_on_redis_exception_without_raising(monkeypatch):
    fake = FakeRedis(raise_on_set=ConnectionError("boom"))
    monkeypatch.setattr(jma_tile_redis_cache, "get_redis_client_or_none", lambda: fake)

    # 例外を送出せず静かに失敗すること（set()と同じfail-open方針）。
    await jma_tile_redis_cache.set_empty("bosai/jmatile/data/risk/.../x.png")


async def test_set_empty_no_ops_when_redis_client_unavailable(monkeypatch):
    monkeypatch.setattr(jma_tile_redis_cache, "get_redis_client_or_none", lambda: None)

    # 例外を送出しないこと。
    await jma_tile_redis_cache.set_empty("bosai/jmatile/data/risk/.../x.png")


def _transparent_png(size: int = 8) -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGBA", (size, size), (0, 0, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


async def test_set_stores_a_flag_instead_of_the_body_for_an_empty_tile(monkeypatch):
    # 中身が空なら実体を持たない。上流が「404」で返すか「200＋全画素透明」で返すかに
    # 関わらず、保持する事実は1つ（描くものが無い）へ揃える。
    fake = FakeRedis()
    monkeypatch.setattr(jma_tile_redis_cache, "get_redis_client_or_none", lambda: fake)
    path = "bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/land/11/1818/805.png"

    await jma_tile_redis_cache.set(path, _transparent_png(), "image/png")

    assert await jma_tile_redis_cache.get(path) is jma_tile_redis_cache.EMPTY_TILE
    stored = next(iter(fake.store.values()))
    assert "body_b64" not in stored


async def test_set_stores_the_body_for_a_vector_tile_that_has_features(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(jma_tile_redis_cache, "get_redis_client_or_none", lambda: fake)
    path = "bosai/jmatile/data/flood/20260829170000/none/20260829170000/surf/flood/11/1818/805.pbf"
    content = b"\x1a\x0bnot-empty-mvt"

    await jma_tile_redis_cache.set(path, content, "application/x-protobuf")

    assert await jma_tile_redis_cache.get(path) == (content, "application/x-protobuf")


async def test_set_stores_a_flag_for_an_empty_vector_tile(monkeypatch):
    # 空のMVTは0バイトで配信される。
    fake = FakeRedis()
    monkeypatch.setattr(jma_tile_redis_cache, "get_redis_client_or_none", lambda: fake)
    path = "bosai/jmatile/data/flood/20260829170000/none/20260829170000/surf/flood/11/1818/805.pbf"

    await jma_tile_redis_cache.set(path, b"", "application/x-protobuf")

    assert await jma_tile_redis_cache.get(path) is jma_tile_redis_cache.EMPTY_TILE


async def test_set_keeps_the_body_when_emptiness_cannot_be_judged(monkeypatch):
    # 判定できないものは「中身あり」へ倒す（誤って空と判定すると危険情報が出なくなる）。
    fake = FakeRedis()
    monkeypatch.setattr(jma_tile_redis_cache, "get_redis_client_or_none", lambda: fake)
    path = "bosai/jmatile/data/liden/20260829170000/none/20260829170000/surf/liden.geojson?id=liden"
    content = b'{"type":"FeatureCollection","features":[]}'

    await jma_tile_redis_cache.set(path, content, "application/json")

    assert await jma_tile_redis_cache.get(path) == (content, "application/json")
