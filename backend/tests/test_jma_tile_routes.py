"""`api/routers/jma_tile.py`——気象庁のタイルの中継と、在否インデックスの配信。

確かめるのは、キャッシュ・補間・上流の結果がどの応答になるか（中身・404・502とブラウザに覚えさせる時間）、
回数制限（429）をキャッシュの外れにだけ当てること、問い合わせの文字列を上流へ渡すこと、
配信元が持たないズームを親タイルから補間して書き戻すこと（`services/jma_tile_interpolation_service.py`の段取りも
ここで通す）、インデックスの有無の応答。取得の口（`get_jma_tile_client`）は応答を差し替え、Redisは`fake_redis`で通す。

ここで見ないもの:
- キャッシュの読み書き・上流への取得・「描くものが無い」の記憶 → `test_jma_tile_client.py`・`test_jma_tile_redis_cache.py`
- どのズームを補間するか・親のパス・恒久の404か → `test_jma_tile_specs.py`・`test_jma_tile_interpolation.py`
- 切り出しそのもの（象限・地物の属性・空の象限） → `test_jma_tile_interpolation.py`
- 回数制限の数え方そのもの → `test_rate_limiter.py`
"""

import io

import mapbox_vector_tile
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from shapely.geometry import LineString

from app.api.dependencies import get_jma_tile_client
from app.config import settings
from app.infrastructure import rate_limiter
from app.infrastructure.jma_tile_client import EmptyTile, JmaTileNotFoundError
from app.infrastructure.jma_tile_index import JmaTileIndex, set_index
from app.main import app

client = TestClient(app)

TILE = "/api/jma-tile/bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/land/11/1818/805.png"
TARGET_TIMES = "/api/jma-tile/bosai/jmatile/data/risk/targetTimes.json"
RAIN_FRAME = "bosai/jmatile/data/risk/20260906191000/immed0/20260906191000/surf/rain_mesh"
FLOOD_FRAME = "bosai/jmatile/data/risk/20260906191000/immed0/20260906191000/surf/flood"


class FakeJmaTileClient:
    """キャッシュ（`get_cached`）・上流（`fetch`）・親タイル（`get`）の応答を決める。

    読むだけの口は応答を返すだけにし、状態を変える上流への取得と、キャッシュへの書き戻しだけを記録する。
    """

    def __init__(self, cached=None, fetched=None, parent=None):
        self._cached = cached
        self._fetched = fetched
        self._parent = parent
        self.fetched_paths: list[str] = []
        self.stored: list[tuple[str, str]] = []

    async def get_cached(self, path):
        return self._cached

    async def fetch(self, path):
        self.fetched_paths.append(path)
        if isinstance(self._fetched, Exception):
            raise self._fetched
        return self._fetched

    async def get(self, path):
        return self._parent

    async def store(self, path, content, content_type):
        self.stored.append((path, content_type))


def _answer(monkeypatch, **answers) -> FakeJmaTileClient:
    fake = FakeJmaTileClient(**answers)
    monkeypatch.setitem(app.dependency_overrides, get_jma_tile_client, lambda: fake)
    return fake


def _fill_rate_limit_but_one():
    for _ in range(settings.jma_tile_rate_limit_per_minute - 1):
        rate_limiter.check_rate_limit("jma-tile:testclient", settings.jma_tile_rate_limit_per_minute)


@pytest.mark.parametrize(("path", "cache_control"), [
    # タイル本体のURLはbasetime/validtimeを含み内容が確定して以後変化しないため、再検証なしで返させる。
    (TILE, "public, max-age=1200, immutable"),
    # 時刻一覧だけは同じURLのまま内容が更新されるため、immutableにせず短命にする。
    ("/api/jma-tile/bosai/jmatile/data/nowc/targetTimes_N3.json", "public, max-age=60"),
])
def test_a_cached_tile_is_served_without_asking_upstream(monkeypatch, path, cache_control):
    fake = _answer(monkeypatch, cached=(b"\x89PNG", "image/png"))

    response = client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content == b"\x89PNG"
    assert response.headers["cache-control"] == cache_control
    assert fake.fetched_paths == []


def test_jma_tile_proxy_returns_404_from_cached_empty_tile_without_fetching(monkeypatch):
    # 描くものが無いと確認済みなら、レート制限もfetchも経由せず即座に404を返す。
    fake = _answer(monkeypatch, cached=EmptyTile())

    response = client.get(TILE)

    assert response.status_code == 404
    assert fake.fetched_paths == []


def test_jma_tile_proxy_is_rate_limited_per_client_on_cache_miss(monkeypatch):
    _answer(monkeypatch, fetched=(b"{}", "application/json"))

    _fill_rate_limit_but_one()
    assert client.get(TARGET_TIMES).status_code == 200

    assert client.get(TARGET_TIMES).status_code == 429


def test_jma_tile_proxy_cache_hit_does_not_consume_rate_limit(monkeypatch):
    """キャッシュヒットはレート制限を一切消費しない（消費すると、キャッシュ済みのタイルを
    往復するだけのパンで429になる）。"""
    _answer(monkeypatch, cached=(b"\x89PNG", "image/png"))

    _fill_rate_limit_but_one()

    # 消費していれば2回目が429になる。
    assert [client.get(TILE).status_code for _ in range(2)] == [200, 200]


def test_jma_tile_proxy_forwards_query_string_to_client(monkeypatch):
    fake = _answer(monkeypatch, fetched=(b'{"type":"FeatureCollection"}', "application/json"))

    response = client.get(
        "/api/jma-tile/bosai/jmatile/data/nowc/20260904120000/none/20260904120000/surf/liden/data.geojson",
        params={"id": "liden"},
    )

    assert response.status_code == 200
    assert fake.fetched_paths == [
        "bosai/jmatile/data/nowc/20260904120000/none/20260904120000/surf/liden/data.geojson?id=liden"
    ]


@pytest.mark.parametrize(("path", "params", "cache_control"), [
    # 疎な格子状タイルに無いz/x/yは珍しくない正常系で、上流障害（502）と分ける。恒久404（basetimeが
    # 確定した過去の一時点に対する結果）は再要求させない。
    ("bosai/jmatile/data/nowc/20260829170000/none/20260829170000/surf/hrpns/10/909/403.png", None,
     "public, max-age=600"),
    # 配信元はコマの地物（GeoJSON）を配信するまで404を返す。ブラウザが覚えると、配信された後もその間は取れない。
    ("bosai/jmatile/data/nowc/20260829170000/none/20260829170000/surf/slmcs_unify/data.geojson",
     {"id": "slmcs_unify"}, "no-store"),
])
def test_a_tile_missing_upstream_is_404_remembered_as_long_as_it_stays_missing(monkeypatch, path, params, cache_control):
    _answer(monkeypatch, fetched=JmaTileNotFoundError("boom"))

    response = client.get(f"/api/jma-tile/{path}", params=params)

    assert response.status_code == 404
    assert response.headers["cache-control"] == cache_control


def test_jma_tile_proxy_does_not_cache_upstream_failures(monkeypatch):
    # 上流障害は一時的なため、次のリクエストで取り直させる。
    _answer(monkeypatch, fetched=None)

    response = client.get(TILE)

    assert response.status_code == 502
    assert "cache-control" not in response.headers


def _tile_png(color):
    """指定色で塗りつぶした256x256のPNG。"""
    buffer = io.BytesIO()
    Image.new("RGBA", (256, 256), color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_jma_tile_proxy_interpolates_zoom_without_native_data(monkeypatch):
    # 大雨キキクルはzoomUse="even"のためz9に実データが無い。上流へ問い合わせる代わりに
    # 親（z8）のタイルから該当象限を切り出し、元のパスのキーでキャッシュへ書き戻す（次回は補間をやり直さない）。
    fake = _answer(monkeypatch, parent=(_tile_png((255, 0, 0, 255)), "image/png"))

    response = client.get(f"/api/jma-tile/{RAIN_FRAME}/9/455/201.png")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert fake.fetched_paths == []
    assert fake.stored == [(f"{RAIN_FRAME}/9/455/201.png", "image/png")]


def test_jma_tile_proxy_interpolates_vector_tiles(monkeypatch):
    # 洪水キキクル（ベクタ）もラスタ3種と同じズームで消えないよう、親から切り出して返す。
    # Content-Typeは親タイルのものをそのまま引き継ぐ。
    parent = mapbox_vector_tile.encode(
        [{"name": "flood", "features": [{"geometry": LineString([(0, 0), (4096, 4096)]), "properties": {}}]}],
    )
    fake = _answer(monkeypatch, parent=(parent, "binary/octet-stream"))

    response = client.get(f"/api/jma-tile/{FLOOD_FRAME}/9/455/201.pbf")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("binary/octet-stream")
    assert fake.stored == [(f"{FLOOD_FRAME}/9/455/201.pbf", "binary/octet-stream")]


def test_jma_tile_proxy_falls_back_when_parent_tile_is_unavailable(monkeypatch):
    # 親タイルが取れない場合は補間せず、通常のフェッチ経路へ進む。
    _answer(monkeypatch, parent=None, fetched=(b"\x89PNG-fallback", "image/png"))

    response = client.get(f"/api/jma-tile/{RAIN_FRAME}/9/455/201.png")

    assert response.status_code == 200
    assert response.content == b"\x89PNG-fallback"


# --- 在否インデックスの配信（GET /api/jma-tile-index） ---


def test_index_reports_unavailable_when_nothing_is_stored(fake_redis):
    response = client.get("/api/jma-tile-index")

    assert response.status_code == 200
    # インデックスが無いことで表示が欠けてはならない。クライアントは全タイルを取りに行く。
    assert response.json() == {"available": False}
    # プリウォーム（10分間隔）ごとに内容が変わる。古いものを掴むと、中身があるタイルを取りに行かないことになる。
    assert response.headers["cache-control"] == "public, max-age=60"


async def test_the_index_the_prewarm_stored_is_what_the_client_receives(fake_redis):
    await set_index(JmaTileIndex.model_validate({
        "coverage": {
            "min_longitude": 138.35,
            "min_latitude": 34.85,
            "max_longitude": 140.95,
            "max_latitude": 37.20,
        },
        "elements": {
            "rain_mesh": {
                "basetime": "20260907025000",
                "validtime": "20260907025000",
                "member": "immed0",
                "zooms": {"10": [[909, 403]]},
            }
        },
    }))

    response = client.get("/api/jma-tile-index")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["elements"]["rain_mesh"]["zooms"]["10"] == [[909, 403]]
    assert body["elements"]["rain_mesh"]["member"] == "immed0"
    assert body["coverage"]["min_longitude"] == 138.35
