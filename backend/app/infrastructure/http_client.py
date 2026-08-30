import httpx

# httpx.AsyncClientの生成はSSLコンテキスト構築（CA証明書バンドルの読み込み・パース）を
# 伴い、実測でこの環境（.venvがOneDrive同期フォルダ内にあるため、証明書ファイルの読み取りに
# OneDriveの同期処理が割り込む）では1回あたり約1秒かかっていた。api/routes.pyの各Dependsは
# リクエストごとに新規AsyncClientを生成していたため、この約1秒がリクエストのたびにイベント
# ループを同期的にブロックし、地図の初期表示で数十件のタイル/フォント要求が重なると数十秒
# 規模まで積み上がっていた（basemap:openfreemap等の外部呼び出しがキャッシュヒット時ですら
# 数秒かかる形で現れた）。database.pyのエンジンと同じ「プロセス全体で1つを使い回す」方針に
# 合わせ、timeoutの値ごとにクライアントを1つだけ生成してキャッシュする。
_clients: dict[float, httpx.AsyncClient] = {}


def get_http_client(timeout: float) -> httpx.AsyncClient:
    if timeout not in _clients:
        _clients[timeout] = httpx.AsyncClient(timeout=timeout)
    return _clients[timeout]


async def close_all_http_clients() -> None:
    """プロセス終了時にmain.pyのlifespanシャットダウン段から呼ぶ（改善計画T463）。

    通常運用ではプロセス終了自体がソケットを回収するため実害は小さいが、テスト・
    スクリプト等でこのモジュールを繰り返しimportして使う場合にコネクションが溜まる
    可能性がある（database.py: get_session_factoryのエンジンも同様に明示closeを持たない
    設計だが、こちらはlifespanに既存のシャットダウン段があるため対で揃えた）。"""
    for client in _clients.values():
        await client.aclose()
    _clients.clear()
