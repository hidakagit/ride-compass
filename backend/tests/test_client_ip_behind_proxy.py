"""Renderのようなリバースプロキシ配下でのクライアントIP解決の回帰テスト。

Renderは自前のロードバランサーをWebサービスの手前に置くため、コンテナ内のuvicornから
見ると全リクエストがRenderの内部プロキシから接続してきたように見える。uvicornの
--proxy-headers（既定で有効）はX-Forwarded-Forを見てrequest.client.hostを実際の
訪問者IPへ書き換えられるが、--forwarded-allow-ips（既定は127.0.0.1のみ）で信頼される
ピアからの接続でなければヘッダーは無視される。backend/Dockerfileでこのオプションを
渡し忘れると、api/dependencies.py: client_id（infrastructure/rate_limiter.pyのキーに使う）が
「実際の訪問者ごと」ではなく「Renderの内部プロキシ」という単一の値になり、路面タイル/
basemapタイルのレート制限をデプロイ先の全アクセスが共有してしまい、通常のパン/ズーム
操作だけで上限に達して429になる不具合が実機で確認された（ローカルはリバースプロキシを
挟まないため再現しない）。

ここではUvicornのProxyHeadersMiddlewareを直接appへ被せることで、backend/Dockerfileの
`--proxy-headers --forwarded-allow-ips=*`と、それを渡し忘れた場合それぞれを再現し、
_client_idが返す値の違いを確認する。
"""

import logging

from fastapi import Request
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

import app.api.dependencies as dependencies_module
from app.main import app

FORWARDED_CLIENT_IP = "203.0.113.5"
# ズーム範囲外(5)のリクエストにする。check_rate_limitはズーム検証より先に実行されるため、
# rate limit判定に使われたclient_idは観測できる（レスポンス自体は400になるがそれで良い）。
ROAD_TILE_PATH = "/api/region/road-surface-tiles/5/10/10.pbf"


def _client_id_seen_by(trusted_hosts) -> str:
    wrapped = ProxyHeadersMiddleware(app, trusted_hosts=trusted_hosts)
    client = TestClient(wrapped)

    captured: list[str] = []
    # ルータのレート制限チェックは`app/api/dependencies.py: enforce_rate_limit`
    # （改善計画T425、全routerの429処理を集約）がモジュール内で直接`client_id(request)`を
    # 呼ぶため、そちらのモジュール属性を差し替えれば観測できる。
    real_client_id = dependencies_module.client_id

    def spy_client_id(request):
        client_id = real_client_id(request)
        captured.append(client_id)
        return client_id

    dependencies_module.client_id = spy_client_id
    try:
        client.get(ROAD_TILE_PATH, headers={"X-Forwarded-For": f"{FORWARDED_CLIENT_IP}, 10.0.0.1"})
    finally:
        dependencies_module.client_id = real_client_id

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


def test_client_id_falls_back_to_unknown_and_warns_when_request_client_is_none(caplog):
    # 改善計画T467: request.clientがNone（ASGI呼び出し元がclient情報を渡さない場合）に、
    # 固定文字列"unknown"へ落ちること自体は既存挙動（複数クライアントが1つのレート制限
    # バケットへ相乗りするリスクがある）だが、運用側が検知できるようWARNINGログを追加した。
    scope = {"type": "http", "client": None, "headers": []}
    request = Request(scope)

    with caplog.at_level(logging.WARNING, logger="ridecompass.dependencies"):
        result = dependencies_module.client_id(request)

    assert result == "unknown"
    assert any("unknown" in record.message for record in caplog.records)
