import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_jma_tile_client
from app.config import settings
from app.infrastructure import rate_limiter
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_rate_limiter():
    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


class FakeJmaTileClient:
    """改善計画T510: ルーターがレート制限より先にキャッシュを参照する構成
    （`get_cached`→ミスなら`enforce_rate_limit`→`fetch`）に合わせ、2つのメソッドを
    個別に差し替えられるフェイク。"""

    def __init__(self, cached_result=None, fetch_result=None, fetch_raises=None):
        self._cached_result = cached_result
        self._fetch_result = fetch_result
        self._fetch_raises = fetch_raises
        self.get_cached_calls = 0
        self.fetch_calls = 0
        self.requested_paths: list[str] = []

    async def get_cached(self, path):
        self.get_cached_calls += 1
        self.requested_paths.append(path)
        return self._cached_result

    async def fetch(self, path):
        self.fetch_calls += 1
        self.requested_paths.append(path)
        if self._fetch_raises is not None:
            raise self._fetch_raises
        return self._fetch_result


def test_jma_tile_proxy_returns_cached_content_with_correct_media_type():
    fake = FakeJmaTileClient(cached_result=(b"\x89PNG", "image/png"))
    app.dependency_overrides[get_jma_tile_client] = lambda: fake

    try:
        response = client.get(
            "/api/jma-tile/bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/land/11/1818/805.png"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content == b"\x89PNG"
    assert fake.fetch_calls == 0


def test_jma_tile_proxy_returns_502_on_upstream_failure():
    fake = FakeJmaTileClient(cached_result=None, fetch_result=None)
    app.dependency_overrides[get_jma_tile_client] = lambda: fake

    try:
        response = client.get("/api/jma-tile/bosai/jmatile/data/risk/targetTimes.json")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502


def test_jma_tile_proxy_returns_404_when_tile_not_found_upstream():
    # 改善計画T603: 疎な格子状タイルでは特定のz/x/yが上流(JMA)に存在しない(404)ことは
    # 珍しくない正常系のため、他の失敗（タイムアウト・5xx等の502）と区別して404を返す。
    from app.infrastructure.jma_tile_client import JmaTileNotFoundError

    fake = FakeJmaTileClient(cached_result=None, fetch_raises=JmaTileNotFoundError("boom"))
    app.dependency_overrides[get_jma_tile_client] = lambda: fake

    try:
        response = client.get(
            "/api/jma-tile/bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/land/11/1818/805.png"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


def test_jma_tile_proxy_returns_404_from_cached_tile_not_found_without_fetching():
    # 改善計画T605: get_cachedがTileNotFound（恒久404を確認済み）を返した場合、
    # レート制限もfetchも経由せず即座に404を返す。
    from app.infrastructure.jma_tile_client import TileNotFound

    fake = FakeJmaTileClient(cached_result=TileNotFound())
    app.dependency_overrides[get_jma_tile_client] = lambda: fake

    try:
        response = client.get(
            "/api/jma-tile/bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/land/11/1818/805.png"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert fake.fetch_calls == 0


def test_jma_tile_proxy_is_rate_limited_per_client_on_cache_miss():
    fake = FakeJmaTileClient(cached_result=None, fetch_result=(b"{}", "application/json"))
    app.dependency_overrides[get_jma_tile_client] = lambda: fake

    try:
        for _ in range(settings.jma_tile_rate_limit_per_minute - 1):
            rate_limiter.check_rate_limit("jma-tile:testclient", settings.jma_tile_rate_limit_per_minute)
        assert client.get("/api/jma-tile/bosai/jmatile/data/risk/targetTimes.json").status_code == 200
        response = client.get("/api/jma-tile/bosai/jmatile/data/risk/targetTimes.json")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429


def test_jma_tile_proxy_cache_hit_does_not_consume_rate_limit():
    """改善計画T510: キャッシュヒットはレート制限を一切消費しない（以前は
    enforce_rate_limitがキャッシュ参照より先に呼ばれており、既にキャッシュ済みの
    タイルへの往復パンだけで429になっていた——ユーザー報告の直接原因）。"""
    fake = FakeJmaTileClient(cached_result=(b"\x89PNG", "image/png"))
    app.dependency_overrides[get_jma_tile_client] = lambda: fake

    try:
        # レート制限の残り枠を1つだけ残した状態を直接作る（境界値テストは
        # rate_limiter.check_rate_limitを直接呼んで埋める方針、docs/testing.md参照）。
        for _ in range(settings.jma_tile_rate_limit_per_minute - 1):
            rate_limiter.check_rate_limit("jma-tile:testclient", settings.jma_tile_rate_limit_per_minute)
        path = "/api/jma-tile/bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/land/11/1818/805.png"
        # 残り枠1つの状態でキャッシュヒットのリクエストを2回行っても、どちらも枠を
        # 消費しないため両方とも200になる（消費していれば2回目が429になるはず）。
        first = client.get(path)
        second = client.get(path)
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 200
    assert second.status_code == 200
    assert fake.fetch_calls == 0


def test_jma_tile_proxy_forwards_query_string_to_client():
    fake = FakeJmaTileClient(cached_result=(b'{"type":"FeatureCollection"}', "application/json"))
    app.dependency_overrides[get_jma_tile_client] = lambda: fake

    try:
        response = client.get(
            "/api/jma-tile/bosai/jmatile/data/nowc/20260904120000/none/20260904120000/surf/liden/data.geojson",
            params={"id": "liden"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert fake.requested_paths == [
        "bosai/jmatile/data/nowc/20260904120000/none/20260904120000/surf/liden/data.geojson?id=liden"
    ]


def test_jma_tile_proxy_marks_tile_body_immutable():
    # タイル本体のURLはbasetime/validtimeを含み内容が確定して以後変化しないため、
    # ブラウザに再検証なしでキャッシュから返させる。
    fake = FakeJmaTileClient(cached_result=(b"\x89PNG", "image/png"))
    app.dependency_overrides[get_jma_tile_client] = lambda: fake

    try:
        response = client.get(
            "/api/jma-tile/bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/land/11/1818/805.png"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=1200, immutable"


def test_jma_tile_proxy_uses_short_cache_for_target_times():
    # 時刻一覧だけは同じURLのまま内容が更新されるため、immutableにせず短命にする。
    fake = FakeJmaTileClient(cached_result=(b"[]", "application/json"))
    app.dependency_overrides[get_jma_tile_client] = lambda: fake

    try:
        response = client.get("/api/jma-tile/bosai/jmatile/data/nowc/targetTimes_N3.json")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60"
    assert "immutable" not in response.headers["cache-control"]


def test_jma_tile_proxy_caches_not_found_responses():
    # 恒久404（basetimeが確定した過去の一時点に対する結果）も再要求させない。
    from app.infrastructure.jma_tile_client import JmaTileNotFoundError

    fake = FakeJmaTileClient(cached_result=None, fetch_raises=JmaTileNotFoundError("boom"))
    app.dependency_overrides[get_jma_tile_client] = lambda: fake

    try:
        response = client.get(
            "/api/jma-tile/bosai/jmatile/data/nowc/20260829170000/none/20260829170000/surf/hrpns/10/909/403.png"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.headers["cache-control"] == "public, max-age=600"


def test_jma_tile_proxy_does_not_cache_upstream_failures():
    # 上流障害は一時的なため、次のリクエストで取り直させる。
    fake = FakeJmaTileClient(cached_result=None, fetch_result=None)
    app.dependency_overrides[get_jma_tile_client] = lambda: fake

    try:
        response = client.get(
            "/api/jma-tile/bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/land/11/1818/805.png"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    assert "cache-control" not in response.headers


def _tile_png(color):
    """指定色で塗りつぶした256x256のPNG。"""
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGBA", (256, 256), color).save(buffer, format="PNG")
    return buffer.getvalue()


class InterpolatingFakeClient(FakeJmaTileClient):
    """親タイルの`get()`と、補間結果の`store()`を観測できるフェイク。"""

    def __init__(self, parent_result=None):
        super().__init__(cached_result=None, fetch_result=None)
        self._parent_result = parent_result
        self.get_paths: list[str] = []
        self.stored: list[tuple[str, str]] = []

    async def get(self, path):
        self.get_paths.append(path)
        return self._parent_result

    async def store(self, path, content, content_type):
        self.stored.append((path, content_type))


def test_jma_tile_proxy_interpolates_zoom_without_native_data():
    # 大雨キキクルはzoomUse="even"のためz9に実データが無い。上流へ問い合わせる代わりに
    # 親（z8）のタイルから該当象限を切り出して返す。
    fake = InterpolatingFakeClient(parent_result=(_tile_png((255, 0, 0, 255)), "image/png"))
    app.dependency_overrides[get_jma_tile_client] = lambda: fake

    try:
        response = client.get(
            "/api/jma-tile/bosai/jmatile/data/risk/20260906191000/immed0/20260906191000/surf/rain_mesh/9/455/201.png"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    # 親のパスはz8・座標は切り捨て（455//2=227、201//2=100）。
    assert fake.get_paths == [
        "bosai/jmatile/data/risk/20260906191000/immed0/20260906191000/surf/rain_mesh/8/227/100.png"
    ]
    # 上流への直接フェッチは行わない。
    assert fake.fetch_calls == 0
    # 補間結果は元のパスのキーでキャッシュへ書き戻す（次回は補間をやり直さない）。
    assert fake.stored == [
        ("bosai/jmatile/data/risk/20260906191000/immed0/20260906191000/surf/rain_mesh/9/455/201.png", "image/png")
    ]


def test_jma_tile_proxy_does_not_interpolate_zoom_with_native_data():
    # z8は実データがあるため、補間せず通常のフェッチ経路を通る。
    fake = InterpolatingFakeClient(parent_result=(_tile_png((0, 255, 0, 255)), "image/png"))
    fake._fetch_result = (b"\x89PNG-native", "image/png")
    app.dependency_overrides[get_jma_tile_client] = lambda: fake

    try:
        response = client.get(
            "/api/jma-tile/bosai/jmatile/data/risk/20260906191000/immed0/20260906191000/surf/rain_mesh/8/227/100.png"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.content == b"\x89PNG-native"
    assert fake.get_paths == []
    assert fake.stored == []


def test_jma_tile_proxy_does_not_interpolate_vector_tiles():
    # 洪水キキクルはベクタタイル（.pbf）で、MVTの再エンコードが必要なため対象外。
    fake = InterpolatingFakeClient(parent_result=(b"parent-pbf", "application/x-protobuf"))
    fake._fetch_result = (b"native-pbf", "application/x-protobuf")
    app.dependency_overrides[get_jma_tile_client] = lambda: fake

    try:
        response = client.get(
            "/api/jma-tile/bosai/jmatile/data/risk/20260906191000/immed0/20260906191000/surf/flood/9/455/201.pbf"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.content == b"native-pbf"
    assert fake.get_paths == []


def test_jma_tile_proxy_falls_back_when_parent_tile_is_unavailable():
    # 親タイルが取れない場合は補間せず、通常のフェッチ経路へ進む。
    fake = InterpolatingFakeClient(parent_result=None)
    fake._fetch_result = (b"\x89PNG-fallback", "image/png")
    app.dependency_overrides[get_jma_tile_client] = lambda: fake

    try:
        response = client.get(
            "/api/jma-tile/bosai/jmatile/data/risk/20260906191000/immed0/20260906191000/surf/rain_mesh/9/455/201.png"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.content == b"\x89PNG-fallback"
    assert fake.stored == []
