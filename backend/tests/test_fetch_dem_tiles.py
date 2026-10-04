"""標高タイルの取得（scripts/fetch_dem_tiles.py）。

入口は`fetch`。配信元は`httpx.MockTransport`の代役に、置き場は一時ディレクトリに差し替える。取る母集団は
本物のプロファイルの宣言（製品とズーム）から導き、範囲だけをタイル1枚ぶんへ絞る。
見るのは、宣言した製品をそれぞれのズームで取り、返ったものを置いて404は区域外の印にすることと、
次の実行がどちらも叩かないこと。

ここで見ないもの:
- 置き場のパスと印の形（`app/batch/dem_tile_store.py`）→ 置いたものを同じモジュールで読み戻すだけで、形は見ない
- 一時的な失敗の試し直しと、諦めたタイルがあれば失敗で終えること → どのテストも通さない
"""

from dataclasses import replace

import httpx
import pytest

from app.batch import dem_tile_store
from app.batch.source_profile import Target, load_source_profile
from app.domain.region import BoundingBox, tile_bounds_lonlat, tiles_covering_bbox
from scripts import fetch_dem_tiles

#: 範囲に使うz15のタイル（東京）。
ZOOM, X, Y = 15, 29100, 12902

#: 代役が200を返す製品。残りは404（その製品の区域外）を返す。
SERVED = {"dem5a", "dem"}


def _profile():
    bounds = tile_bounds_lonlat(ZOOM, X, Y)
    inset = 1e-6
    bbox = (bounds.min_latitude + inset, bounds.min_longitude + inset,
            bounds.max_latitude - inset, bounds.max_longitude - inset)
    return replace(load_source_profile(None), target=Target(bbox=bbox))


def _declared_requests(profile) -> set[tuple[str, int, int, int]]:
    """宣言どおりなら叩くはずの (製品, ズーム, x, y)。"""
    low_lat, low_lon, high_lat, high_lon = profile.target.bbox
    bbox = BoundingBox(min_latitude=low_lat, min_longitude=low_lon,
                       max_latitude=high_lat, max_longitude=high_lon)
    return {(product, zoom, x, y)
            for product, zoom in profile.source("dem").grid.products.items()
            for x, y in tiles_covering_bbox(bbox, zoom)}


class Origin:
    """配信元の代役。受けた要求を (製品, ズーム, x, y) で覚える。"""

    def __init__(self):
        self.requests: list[tuple[str, int, int, int]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        product, z, x, y = request.url.path.removesuffix(".txt").split("/")[-4:]
        self.requests.append((product, int(z), int(x), int(y)))
        if product in SERVED:
            return httpx.Response(200, text="1.00,e\n")
        return httpx.Response(404)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))


@pytest.fixture
def profile():
    return _profile()


async def test_served_tiles_are_stored_and_the_rest_marked_absent_per_product(tmp_path, profile):
    """1つの製品が返しても他の製品を取りやめず、各製品を宣言したズームで取る。"""
    origin = Origin()
    async with origin.client() as client:
        await fetch_dem_tiles.fetch(client, tmp_path, profile, attempts=1)

    for product, zoom, x, y in _declared_requests(profile):
        stored = dem_tile_store.is_stored(tmp_path, product, zoom, x, y)
        absent = dem_tile_store.is_absent(tmp_path, product, zoom, x, y)
        assert (stored, absent) == ((True, False) if product in SERVED else (False, True))
    served = next(r for r in _declared_requests(profile) if r[0] in SERVED)
    assert dem_tile_store.read_tile(tmp_path, *served) == "1.00,e\n"


async def test_a_second_run_does_not_ask_the_origin_again(tmp_path, profile):
    """取れたものも、区域外と分かったものも、次からは叩かない。"""
    first = Origin()
    async with first.client() as client:
        await fetch_dem_tiles.fetch(client, tmp_path, profile, attempts=1)

    second = Origin()
    async with second.client() as client:
        await fetch_dem_tiles.fetch(client, tmp_path, profile, attempts=1)

    assert second.requests == []
