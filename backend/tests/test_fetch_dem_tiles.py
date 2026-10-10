"""標高タイルの取得（scripts/fetch_dem_tiles.py）。

入口は`fetch`。配信元は`httpx.MockTransport`の代役に、置き場は一時ディレクトリに差し替える。取る母集団は
本物のプロファイルの宣言（製品とズーム）から導き、範囲だけをz15のタイル2×2枚ぶんへ絞る。
見るのは、宣言した製品をそれぞれのズームでPNG形式のURLから取り、返ったものをタイルごとに置いて404は区域外の印にすることと、
次の実行がどちらも叩かないこと。同じ製品の中で列・行の違うタイルと、置いたタイルと区域外の印が隣り合う形を含め、
置き場で別のタイルが重なると、別の場所の標高を読むか、取るべきタイルを取らない。

ここで見ないもの:
- 置き場のパスと印の形（`app/batch/dem_tile_store.py`）→ 置いたものを同じモジュールで読み戻すだけで、形は見ない
- 一時的な失敗の試し直しと、諦めたタイルがあれば失敗で終えること → どのテストも通さない
"""

import re
from dataclasses import replace

import httpx
import pytest

from app.batch import dem_tile_store
from app.batch.source_profile import Target, load_source_profile
from app.domain.region import BoundingBox, tile_bounds_lonlat, tiles_covering_bbox
from scripts import fetch_dem_tiles

#: 範囲の左上に使うz15のタイル（東京）。範囲はここから右と下へ1枚ずつ広げる。
ZOOM, X, Y = 15, 29100, 12902

#: 代役が200を返す製品。残りは404（その製品の区域外）を返す。
SERVED = {"dem5a", "dem"}
#: SERVEDの製品でも、代役が404を返すタイル（範囲の右下）。
UNSERVED_TILE = (X + 1, Y + 1)

#: 配信元のPNG形式のURLの道（https://maps.gsi.go.jp/development/ichiran.html）。製品名に`_png`が付く。
PNG_PATH = re.compile(r"/xyz/(?P<product>\w+)_png/(?P<z>\d+)/(?P<x>\d+)/(?P<y>\d+)\.png")



def _body(product: str, x: int, y: int) -> bytes:
    """代役が返す本文。置き場は中身を読まないので、PNGである必要は無く、タイルごとに違えばよい。"""
    return f"{product}/{x}/{y}".encode()


def _served(product: str, zoom: int, x: int, y: int) -> bool:
    return product in SERVED and (zoom, x, y) != (ZOOM, *UNSERVED_TILE)


def _profile():
    top_left = tile_bounds_lonlat(ZOOM, X, Y)
    bottom_right = tile_bounds_lonlat(ZOOM, X + 1, Y + 1)
    inset = 1e-6
    bbox = (bottom_right.min_latitude + inset, top_left.min_longitude + inset,
            top_left.max_latitude - inset, bottom_right.max_longitude - inset)
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
    """配信元の代役。受けた要求を (製品, ズーム, x, y) で覚える。PNG形式のURLでなければ400を返す。"""

    def __init__(self):
        self.requests: list[tuple[str, int, int, int]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        match = PNG_PATH.fullmatch(request.url.path)
        if match is None:
            return httpx.Response(400)
        product, z, x, y = match["product"], int(match["z"]), int(match["x"]), int(match["y"])
        self.requests.append((product, z, x, y))
        if _served(product, z, x, y):
            return httpx.Response(200, content=_body(product, x, y))
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

    declared = _declared_requests(profile)
    assert ("dem5a", ZOOM, *UNSERVED_TILE) in declared  # 範囲が2×2枚に掛かっている
    for product, zoom, x, y in declared:
        stored = dem_tile_store.is_stored(tmp_path, product, zoom, x, y)
        absent = dem_tile_store.is_absent(tmp_path, product, zoom, x, y)
        served = _served(product, zoom, x, y)
        assert (stored, absent) == (served, not served), (product, zoom, x, y)
        if served:
            assert dem_tile_store.read_tile(tmp_path, product, zoom, x, y) == _body(product, x, y)


async def test_a_second_run_does_not_ask_the_origin_again(tmp_path, profile):
    """取れたものも、区域外と分かったものも、次からは叩かない。"""
    first = Origin()
    async with first.client() as client:
        await fetch_dem_tiles.fetch(client, tmp_path, profile, attempts=1)

    second = Origin()
    async with second.client() as client:
        await fetch_dem_tiles.fetch(client, tmp_path, profile, attempts=1)

    assert second.requests == []
