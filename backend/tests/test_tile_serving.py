"""`services/tile_serving.py`——タイル配信の共通の骨格（キャッシュ確認・取得・キャッシュ書き込み）。

ここで見ないもの:
- 各タイル種別のキャッシュの鍵・取得の仕方 → `test_landcover_tile.py`等、種別ごとのテスト
- キャッシュのファイルの読み書き → `test_tile_cache.py`
- 記録した項目のログ・統計への出し方 → `test_debug_log.py`

ディスクのキャッシュ（`tile_cache`の読み書き）と、記録の口（`log_external_call`）は代役へ差し替え、
本物の署名へ当てる（`bound`）。
"""

import contextlib
import threading

import pytest

from app.services import tile_serving
from tests.bound_fake import bound
from tests.fake_tile_cache import FakeTileCache

EMPTY = b"empty-tile"
PATH = "kind/v1/10/905/403.png"


@pytest.fixture
def cache(monkeypatch):
    fake = FakeTileCache()
    monkeypatch.setattr(tile_serving.tile_cache, "get", bound(tile_serving.tile_cache.get, fake.get))
    monkeypatch.setattr(tile_serving.tile_cache, "set", bound(tile_serving.tile_cache.set, fake.set))
    return fake


@pytest.fixture
def records(monkeypatch):
    """記録の口へ渡された分類・座標と、処理の最後に残った記録の項目。"""
    calls: list[dict] = []

    @contextlib.contextmanager
    def record(category, **fields):
        entry = {"category": category, "given": fields, "fields": {}}
        calls.append(entry)
        yield entry["fields"]

    monkeypatch.setattr(tile_serving, "log_external_call", bound(tile_serving.log_external_call, record))
    return calls


def _fetch(result, fields_to_set=None):
    calls: list[dict] = []

    async def fetch(fields):
        calls.append(fields)
        fields.update(fields_to_set or {})
        return result

    return fetch, calls


async def _serve(fetch, **overrides):
    arguments = {
        "z": 10,
        "x": 905,
        "y": 403,
        "cache_path": PATH,
        "empty_tile": EMPTY,
        "content_type": "image/png",
        "external_call_name": "kind-tile",
        "fetch_tile": fetch,
        "source_label": "raster",
        **overrides,
    }
    return await tile_serving.serve_cached_tile(**arguments)


async def test_a_cached_tile_is_returned_without_making_it_again(cache, records):
    cache.entries[PATH] = (b"cached", "image/png")
    fetch, fetched = _fetch(b"new")

    response = await _serve(fetch)

    assert response == tile_serving.TileResponse(b"cached")
    assert fetched == []
    assert records[0]["fields"]["cache"] == "hit"


async def test_a_missing_tile_is_made_stored_and_returned(cache, records):
    fetch, fetched = _fetch(b"new")

    response = await _serve(fetch)

    assert response == tile_serving.TileResponse(b"new")
    assert cache.entries == {PATH: (b"new", "image/png")}
    (record,) = records
    assert record["category"] == "kind-tile"
    assert record["given"] == {"z": 10, "x": 905, "y": 403}
    # 取得元は呼び出し元が名乗る（統計の内訳が実際の取得元と食い違わないため）
    assert record["fields"] == {"cache": "miss", "source": "raster", "tile_bytes": 3, "persisted": True}
    # 作る関数は、記録の項目を書き足せるよう同じ辞書を受け取る
    assert fetched == [record["fields"]]


async def test_disk_reads_and_writes_run_off_the_event_loop(cache, records):
    fetch, _ = _fetch(b"new")

    await _serve(fetch)

    # 同時に処理中の他のタイル・ルート生成をディスクI/Oで止めない
    assert len(cache.thread_idents) == 2
    assert threading.get_ident() not in cache.thread_idents


async def test_a_tile_made_without_knowing_its_generation_is_not_stored(cache, records):
    fetch, _ = _fetch(b"new")

    response = await _serve(fetch, persist=False)

    assert response == tile_serving.TileResponse(b"new")
    assert cache.entries == {}
    assert records[0]["fields"]["persisted"] is False


@pytest.mark.parametrize(
    ("fields_to_set", "cacheable"),
    [
        ({}, True),  # 範囲外で恒久的に無い
        ({"postgis": "error"}, False),  # 一時的に取れなかった——ブラウザに空白を残さない
    ],
)
async def test_a_tile_that_cannot_be_made_is_the_empty_tile_and_is_not_stored(cache, records, fields_to_set, cacheable):
    fetch, _ = _fetch(None, fields_to_set)

    response = await _serve(fetch)

    assert response == tile_serving.TileResponse(EMPTY, cacheable=cacheable)
    assert cache.entries == {}
    assert records[0]["fields"]["source"] == "uncovered_empty"
