import httpx

# httpx.AsyncClientの生成はSSLコンテキスト構築（CA証明書バンドルの読み込み・パース）を
# 伴い、環境によっては1回あたり高コストになりうる。リクエストごとに新規生成すると
# この構築コストがリクエストのたびにイベントループを同期的にブロックするため、
# database.pyのエンジンと同じ「プロセス全体で1つを使い回す」方針に合わせ、timeoutの値
# ごとにクライアントを1つだけ生成してキャッシュする。
_clients: dict[float, httpx.AsyncClient] = {}


def get_http_client(timeout: float) -> httpx.AsyncClient:
    if timeout not in _clients:
        _clients[timeout] = httpx.AsyncClient(timeout=timeout)
    return _clients[timeout]


async def close_all_http_clients() -> None:
    """プロセス終了時にmain.pyのlifespanシャットダウン段から呼ぶ。

    通常運用ではプロセス終了自体がソケットを回収するため実害は小さいが、テスト・
    スクリプト等でこのモジュールを繰り返しimportして使う場合にコネクションが溜まる
    可能性がある（database.py: get_session_factoryのエンジンも同様に明示closeを持たない
    設計だが、こちらはlifespanに既存のシャットダウン段があるため対で揃えた）。"""
    for client in _clients.values():
        await client.aclose()
    _clients.clear()
