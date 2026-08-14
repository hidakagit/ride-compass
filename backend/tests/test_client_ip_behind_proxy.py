"""Renderのようなリバースプロキシ配下でのクライアントIP解決の回帰テスト。

Renderは自前のロードバランサーをWebサービスの手前に置くため、コンテナ内のuvicornから
見ると全リクエストがRenderの内部プロキシから接続してきたように見える。uvicornの
--proxy-headers（既定で有効）はX-Forwarded-Forを見てrequest.client.hostを実際の
訪問者IPへ書き換えられるが、--forwarded-allow-ips（既定は127.0.0.1のみ）で信頼される
ピアからの接続でなければヘッダーは無視される。backend/Dockerfileでこのオプションを
渡し忘れると、api/routes.py: _client_id（infrastructure/rate_limiter.pyが使う）が
「実際の訪問者ごと」ではなく「Renderの内部プロキシ」という単一の値になり、路面タイル/
basemapタイルのレート制限をデプロイ先の全アクセスが共有してしまい、通常のパン/ズーム
操作だけで上限に達して429になる不具合が実機で確認された（ローカルはリバースプロキシを
挟まないため再現しない）。

ここではUvicornのProxyHeadersMiddlewareを直接appへ被せることで、backend/Dockerfileの
`--proxy-headers --forwarded-allow-ips=*`と、それを渡し忘れた場合それぞれを再現し、
_client_idが返す値の違いを確認する。
"""

from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

import app.api.routes as routes_module
from app.main import app

FORWARDED_CLIENT_IP = "203.0.113.5"
# ズーム範囲外(5)のリクエストにする。check_rate_limitはズーム検証より先に実行されるため、
# rate limit判定に使われたclient_idは観測できる（レスポンス自体は400になるがそれで良い）。
ROAD_TILE_PATH = "/api/region/road-surface-tiles/5/10/10.pbf"


def _client_id_seen_by(trusted_hosts) -> str:
    wrapped = ProxyHeadersMiddleware(app, trusted_hosts=trusted_hosts)
    client = TestClient(wrapped)

    captured: list[str] = []
    real_client_id = routes_module._client_id

    def spy_client_id(request):
        client_id = real_client_id(request)
        captured.append(client_id)
        return client_id

    routes_module._client_id = spy_client_id
    try:
        client.get(ROAD_TILE_PATH, headers={"X-Forwarded-For": f"{FORWARDED_CLIENT_IP}, 10.0.0.1"})
    finally:
        routes_module._client_id = real_client_id

    assert len(captured) == 1
    return captured[0]


def test_forwarded_for_is_ignored_without_trusted_proxy_config():
    # backend/Dockerfileの--forwarded-allow-ipsを渡し忘れた場合の挙動（既定はtrusted_hosts="127.0.0.1"）。
    # TestClientの接続元は"testclient"という文字列であり127.0.0.1と一致しないため、
    # X-Forwarded-Forは信頼されず無視される（＝全リクエストが同じclient_idに潰れる不具合を再現）。
    assert _client_id_seen_by(trusted_hosts="127.0.0.1") == "testclient"


def test_forwarded_for_is_honored_with_trusted_proxy_config():
    # backend/Dockerfileの--forwarded-allow-ips=*相当。コンテナへの着信経路はRenderの
    # プロキシ経由のみのため、この設定で正しくX-Forwarded-Forの先頭（実際の訪問者IP）が
    # request.client.host（＝_client_idの戻り値）へ反映される。
    assert _client_id_seen_by(trusted_hosts="*") == FORWARDED_CLIENT_IP
