"""`services/landcover_tile_service.py`——土地被覆ラスタタイルの配信（キャッシュの鍵・ラスタが無いときの扱い）。

ここで見ないもの:
- ラスタの読み取り・再投影・PNGへの描画 → `test_landcover_raster.py`
- 配信の口（ズームの範囲・503） → `test_region_routes.py`
- キャッシュの読み書きと空タイルの扱いの骨格 → `test_region_tile_cache.py`
- 骨格へ渡すタイルの種類（`content_type`）——キャッシュの項目に書かれるだけで読み手が無く、応答の種類はルーターが
  決める（`test_region_routes.py`）
- ラスタ構成の指紋の作り方 → `test_landcover.py`

ラスタ（`landcover_raster`の口）と、キャッシュを通す骨格（`serve_region_tile`）は代役へ差し替え、
本物の署名へ当てる（`bound`）。範囲外の空のタイルのテストだけは骨格を本物で通す。
"""

import logging
import pytest

from app.infrastructure import debug_log
from app.infrastructure.cache_identity import LANDCOVER_TILE_VERSION
from app.services import landcover_tile_service as service
from tests.bound_fake import bound

RASTER = service.landcover_raster

class Raster:
    """ラスタの口の代役。開けているパスと、描いた絵を持つ。"""

    def __init__(self, opened: list[str]):
        self.opened = list(opened)
        self.rendered: list[tuple[int, int, int]] = []
        #: 描いた絵。None は範囲外で描けないこと。
        self.drawn: bytes | None = b"png-bytes"

    def has_sources(self) -> bool:
        return bool(self.opened)

    def opened_raster_paths(self) -> list[str]:
        return list(self.opened)

    def render_tile(self, z, x, y):
        self.rendered.append((z, x, y))
        return self.drawn


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

    monkeypatch.setattr(service, "serve_region_tile", bound(service.serve_region_tile, serve))
    return calls


# ---- 配信 ----


async def test_a_tile_is_drawn_from_the_raster_through_the_cache(raster, served):
    response = await service.get_landcover_tile(10, 905, 403)

    assert response == service.TileResponse(content=b"png-bytes")
    assert raster.rendered == [(10, 905, 403)]
    assert (served[0]["z"], served[0]["x"], served[0]["y"]) == (10, 905, 403)


async def test_outside_the_rasters_the_tile_is_the_clear_image_of_the_raster(raster):
    """範囲外で描けないときは、ラスタの塗りと同じ形の透明なPNGを返し、ブラウザに持たせてよい。
    キャッシュの骨格は本物を通す（空のタイルはディスクへ書かないので、ほかのテストへ残らない）。"""
    raster.drawn = None

    response = await service.get_landcover_tile(10, 905, 403)

    assert response == service.TileResponse(content=RASTER.empty_tile_png(), cacheable=True)


async def test_the_cache_key_follows_the_rasters_actually_opened(raster, served):
    await service.get_landcover_tile(10, 905, 403)
    raster.opened = ["/data/zone53.tif", "/data/zone54.tif"]
    await service.get_landcover_tile(10, 905, 403)
    raster.opened = ["/other/zone54.tif", "/other/zone53.tif"]
    await service.get_landcover_tile(10, 905, 403)

    first, added, reordered = (call["generation"] for call in served)
    # ラスタを1枚足したら別の鍵——継ぎ目のタイルが古い絵（片側が透明）を返し続けない
    assert added != first
    # 同じ構成なら置き場所・並びに依らず同じ鍵
    assert reordered == added


async def test_the_cache_key_carries_the_tile_version(raster, served):
    await service.get_landcover_tile(10, 905, 403)

    assert served[0]["generation"].startswith(f"{LANDCOVER_TILE_VERSION}/")


# ---- ラスタが1枚も無いとき ----


@pytest.mark.parametrize(
    ("configured", "cause"),
    [
        ("", "LULC_RASTER_PATHSが未設定"),
        ("/data/a.tif,/data/b.tif", "設定された2件のいずれも開けません"),
    ],
)
async def test_without_any_raster_there_is_no_tile_and_the_cause_is_logged(
    raster, served, monkeypatch, caplog, configured, cause
):
    raster.opened = []
    monkeypatch.setattr(service.settings, "lulc_raster_paths", configured)

    with caplog.at_level(logging.WARNING, logger=debug_log.logger.name):
        assert await service.get_landcover_tile(10, 905, 403) is None

    # 範囲外の空タイルとは区別する（空を返すと、地図は空なのに正常に見える）
    assert served == []
    # 前のテストで抑えた件数の知らせが、窓が替わって最初の警告の前に出ることがあるので、原因を持つ行で読む。
    assert [r for r in caplog.records if r.name == debug_log.logger.name and cause in r.getMessage()]


async def test_the_missing_raster_warning_is_not_repeated_for_every_tile(raster, served, caplog):
    raster.opened = []
    tiles = debug_log.WARN_BURST_PER_WINDOW + 3

    with caplog.at_level(logging.WARNING, logger=debug_log.logger.name):
        for y in range(tiles):
            await service.get_landcover_tile(10, 905, 403 + y)

    # 1枚ごとに出すと地図を1画面開くだけで数十行になる
    assert len([r for r in caplog.records if r.name == debug_log.logger.name]) < tiles
