"""`infrastructure/region_tile_cache.py`——地域タイルのディスクの口（キャッシュ確認・取得・キャッシュ書き込みの骨格と、旧世代の掃除）。

ここで見ないもの:
- 各タイル種別の取得の仕方 → `test_landcover_tile.py`等、種別ごとのテスト
- ディスクのキャッシュの読み書きと、読めない・消せないときの扱い → `test_tile_cache.py`
- 記録した項目のログ・統計への出し方 → `test_debug_log.py`

骨格のテストは、ディスクのキャッシュ（`tile_cache`の読み書き）と記録の口（`log_external_call`）を代役へ差し替え、
本物の署名へ当てる（`bound`）。旧世代の掃除のテストは、ディスクを本物で通し（置き場は`tests/conftest.py`が
テストごとの一時ディレクトリへ向けてある）、ラスタの口だけを代役にする。
"""

import contextlib
import threading

import pytest

from app.infrastructure import region_tile_cache, tile_cache
from app.infrastructure.cache_identity import UNKNOWN_REVISION, region_tile_key
from app.infrastructure.debug_log import mark_failed
from tests.bound_fake import bound
from tests.fake_tile_cache import FakeTileCache

EMPTY = b"empty-tile"
TILE = {"kind": "kind", "generation": "1", "z": 10, "x": 905, "y": 403, "extension": "png"}
KEY = region_tile_key(**TILE)


@pytest.fixture
def cache(monkeypatch):
    fake = FakeTileCache()
    disk = region_tile_cache.tile_cache
    monkeypatch.setattr(disk, "get", bound(disk.get, fake.get))
    monkeypatch.setattr(disk, "set", bound(disk.set, fake.set))
    return fake


@pytest.fixture
def records(monkeypatch):
    """処理の最後に残った記録の項目。"""
    calls: list[dict] = []

    @contextlib.contextmanager
    def record(category, **fields):
        calls.append({})
        yield calls[-1]

    monkeypatch.setattr(region_tile_cache, "log_external_call", bound(region_tile_cache.log_external_call, record))
    return calls


def _fetch(result, failure=None):
    calls: list[dict] = []

    async def fetch(fields):
        calls.append(fields)
        if failure is not None:
            mark_failed(fields, failure)
        return result

    return fetch, calls


async def _serve(fetch, **overrides):
    arguments = {
        **TILE,
        "empty_tile": EMPTY,
        "content_type": "image/png",
        "external_call_name": "kind-tile",
        "fetch_tile": fetch,
        "source_label": "raster",
        **overrides,
    }
    return await region_tile_cache.serve_region_tile(**arguments)


async def test_a_cached_tile_is_returned_without_making_it_again(cache, records):
    cache.entries[KEY] = (b"cached", "image/png")
    fetch, fetched = _fetch(b"new")

    response = await _serve(fetch)

    assert response == region_tile_cache.TileResponse(b"cached")
    assert fetched == []
    assert records[0]["cache"] == "hit"


async def test_a_missing_tile_is_made_stored_and_returned(cache, records):
    fetch, _ = _fetch(b"new")

    response = await _serve(fetch)

    assert response == region_tile_cache.TileResponse(b"new")
    assert cache.entries == {KEY: (b"new", "image/png")}
    # 取得元は呼び出し元が名乗る（統計の内訳が実際の取得元と食い違わないため）
    assert records == [{"cache": "miss", "source": "raster", "tile_bytes": 3, "persisted": True}]


async def test_disk_reads_and_writes_run_off_the_event_loop(cache, records):
    fetch, _ = _fetch(b"new")

    await _serve(fetch)

    # 同時に処理中の他のタイル・ルート生成をディスクI/Oで止めない
    assert len(cache.thread_idents) == 2
    assert threading.get_ident() not in cache.thread_idents


async def test_a_tile_made_without_knowing_its_generation_is_not_stored(cache, records):
    fetch, _ = _fetch(b"new")

    response = await _serve(fetch, persist=False)

    assert response == region_tile_cache.TileResponse(b"new")
    assert cache.entries == {}
    assert records[0]["persisted"] is False


@pytest.mark.parametrize(
    ("failure", "cacheable"),
    [
        (None, True),  # 範囲外で恒久的に無い
        (ConnectionRefusedError("db down"), False),  # 一時的に取れなかった——ブラウザに空白を残さない
    ],
)
async def test_a_tile_that_cannot_be_made_is_the_empty_tile_and_is_not_stored(cache, records, failure, cacheable):
    fetch, _ = _fetch(None, failure)

    response = await _serve(fetch)

    assert response == region_tile_cache.TileResponse(EMPTY, cacheable=cacheable)
    assert cache.entries == {}
    assert records[0]["source"] == "uncovered_empty"


# ---- 旧世代の掃除 ----


@pytest.fixture
def opened_rasters(monkeypatch):
    """開けている土地被覆ラスタのパス（代役）。空にすると1枚も開けない状態になる。"""
    opened = ["/data/zone53.tif"]
    raster = region_tile_cache.landcover_raster
    monkeypatch.setattr(raster, "has_sources", bound(raster.has_sources, lambda: bool(opened)))
    monkeypatch.setattr(raster, "opened_raster_paths", bound(raster.opened_raster_paths, lambda: list(opened)))
    return opened


def _store(*keys: str) -> None:
    for key in keys:
        tile_cache.set(key, b"tile", "application/octet-stream")


def _kept(*keys: str) -> set[str]:
    return {key for key in keys if tile_cache.get(key) is not None}


def test_only_the_generations_being_served_stay_on_disk(opened_rasters):
    landcover_now = region_tile_cache.landcover_generation()
    opened_rasters.append("/data/zone54.tif")
    landcover_with_another_zone = region_tile_cache.landcover_generation()
    opened_rasters.pop()
    keys = {
        "路面の今の世代": region_tile_key("road_surface", "3.2-aaa", 12, 1, 1, "pbf"),
        "路面の前の世代": region_tile_key("road_surface", "2.2-aaa", 12, 1, 1, "pbf"),
        "形の署名だけ違う世代": region_tile_key("road_surface", "3.2-bbb", 12, 1, 1, "pbf"),
        "世代を読めていない系統": region_tile_key("poi", "3.2-ccc", 12, 1, 1, "pbf"),
        "表に無い系統": region_tile_key("road-surface", "3.2-aaa", 12, 1, 1, "pbf"),
        "土地被覆の今のラスタ構成": region_tile_key("landcover", landcover_now, 12, 1, 1, "png"),
        "土地被覆の別のラスタ構成": region_tile_key("landcover", landcover_with_another_zone, 12, 1, 1, "png"),
        "基礎地図（地域タイルでない）": "styles/liberty",
    }
    _store(*keys.values())

    removed = region_tile_cache.prune_other_generations(
        {"road_surface": "3.2-aaa", "poi": f"{UNKNOWN_REVISION}-ccc"}
    )

    kept = _kept(*keys.values())
    assert {name for name, key in keys.items() if key in kept} == {
        "路面の今の世代",
        "世代を読めていない系統",
        "土地被覆の今のラスタ構成",
        "基礎地図（地域タイルでない）",
    }
    assert removed == len(keys) - len(kept)


def test_landcover_tiles_stay_while_no_raster_can_be_opened(opened_rasters):
    """どれが今の構成か分からない間は消さない（起動時にラスタが一時に置かれていない等）。"""
    key = region_tile_key("landcover", region_tile_cache.landcover_generation(), 12, 1, 1, "png")
    _store(key)
    opened_rasters.clear()

    region_tile_cache.prune_other_generations({})

    assert _kept(key) == {key}
