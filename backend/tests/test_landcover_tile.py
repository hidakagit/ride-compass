"""`services/landcover_tile_service.py`——土地被覆ラスタタイルの配信（キャッシュの鍵・ラスタが無いときの扱い）。

ここで見ないもの:
- ラスタの読み取り・再投影・PNGへの描画 → `test_landcover_raster.py`
- 配信の口（ズームの範囲・503） → `test_region_routes.py`
- キャッシュの読み書きと空タイルの扱いの骨格 → `test_tile_serving.py`
- ラスタ構成の指紋の作り方 → `test_landcover.py`

ラスタ（`landcover_raster`の口）と、キャッシュを通す骨格（`serve_cached_tile`）は代役へ差し替え、
本物の署名へ当てる（`bound`）。警告を出した時刻はモジュールが持つ状態なので、テストごとに
時計ごと差し替えて、前のテストの状態を読まない。
"""

import logging
from types import SimpleNamespace

import pytest

from app.services import landcover_tile_service as service
from tests.bound_fake import bound

RASTER = service.landcover_raster


class Raster:
    """ラスタの口の代役。開けているパスと、描いた絵を持つ。"""

    def __init__(self, opened: list[str]):
        self.opened = list(opened)
        self.rendered: list[tuple[int, int, int]] = []

    def has_sources(self) -> bool:
        return bool(self.opened)

    def opened_raster_paths(self) -> list[str]:
        return list(self.opened)

    def render_tile(self, z, x, y):
        self.rendered.append((z, x, y))
        return b"png-bytes"


@pytest.fixture
def clock(monkeypatch):
    """警告の間引きが読む時計。`[秒]`を書き換えると進む。前回の警告時刻もここで初期化する。"""
    now = [1_000.0]
    monkeypatch.setattr(service, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(service, "_last_unavailable_log", 0.0)
    return now


@pytest.fixture
def raster(monkeypatch):
    fake = Raster(["/data/zone53.tif"])
    for name in ("has_sources", "opened_raster_paths", "render_tile"):
        monkeypatch.setattr(RASTER, name, bound(getattr(RASTER, name), getattr(fake, name)))
    return fake


@pytest.fixture
def served(monkeypatch):
    """キャッシュを通す骨格の代役。渡された引数を残し、タイルを作る関数を呼んでその結果を返す。"""
    calls: list[dict] = []

    async def serve(**kwargs):
        calls.append(kwargs)
        content = await kwargs["fetch_tile"]({})
        return service.TileResponse(content=content)

    monkeypatch.setattr(service, "serve_cached_tile", bound(service.serve_cached_tile, serve))
    return calls


# ---- 配信 ----


async def test_a_tile_is_drawn_from_the_raster_through_the_cache(clock, raster, served):
    response = await service.get_landcover_tile(10, 905, 403)

    assert response == service.TileResponse(content=b"png-bytes")
    assert raster.rendered == [(10, 905, 403)]
    (call,) = served
    assert (call["z"], call["x"], call["y"]) == (10, 905, 403)
    assert call["content_type"] == "image/png"
    assert call["cache_path"].endswith("/10/905/403.png")
    # 範囲外で描けないときに返るのは、ラスタの塗りと同じ形の透明なPNG
    assert call["empty_tile"] == RASTER.empty_tile_png()


async def test_the_cache_key_follows_the_rasters_actually_opened(clock, raster, served):
    await service.get_landcover_tile(10, 905, 403)
    raster.opened = ["/data/zone53.tif", "/data/zone54.tif"]
    await service.get_landcover_tile(10, 905, 403)
    raster.opened = ["/other/zone54.tif", "/other/zone53.tif"]
    await service.get_landcover_tile(10, 905, 403)

    first, added, reordered = (call["cache_path"] for call in served)
    # ラスタを1枚足したら別の鍵——継ぎ目のタイルが古い絵（片側が透明）を返し続けない
    assert added != first
    # 同じ構成なら置き場所・並びに依らず同じ鍵
    assert reordered == added


async def test_the_cache_key_carries_the_tile_version(clock, raster, served):
    await service.get_landcover_tile(10, 905, 403)

    assert f"/v{service.LANDCOVER_TILE_VERSION}/" in served[0]["cache_path"]


# ---- ラスタが1枚も無いとき ----


@pytest.mark.parametrize(
    ("configured", "cause"),
    [
        ("", "LULC_RASTER_PATHSが未設定"),
        ("/data/a.tif,/data/b.tif", "設定された2件のいずれも開けません"),
    ],
)
async def test_without_any_raster_there_is_no_tile_and_the_cause_is_logged(
    clock, raster, served, monkeypatch, caplog, configured, cause
):
    raster.opened = []
    monkeypatch.setattr(service.settings, "lulc_raster_paths", configured)

    with caplog.at_level(logging.WARNING, logger=service.logger.name):
        assert await service.get_landcover_tile(10, 905, 403) is None

    # 範囲外の空タイルとは区別する（空を返すと、地図は空なのに正常に見える）
    assert served == []
    (record,) = [r for r in caplog.records if r.name == service.logger.name]
    assert cause in record.getMessage()


async def test_the_missing_raster_warning_is_repeated_only_once_in_a_while(clock, raster, served, caplog):
    raster.opened = []
    interval = service._UNAVAILABLE_LOG_INTERVAL_SECONDS

    with caplog.at_level(logging.WARNING, logger=service.logger.name):
        await service.get_landcover_tile(10, 905, 403)
        clock[0] += interval - 1
        await service.get_landcover_tile(10, 905, 404)
        clock[0] += 1
        await service.get_landcover_tile(10, 905, 405)

    # 1枚ごとに出すと地図を1画面開くだけで数十行になる。間隔が過ぎたら1回出す
    assert len([r for r in caplog.records if r.name == service.logger.name]) == 2
