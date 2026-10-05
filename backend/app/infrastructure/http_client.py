import httpx

# httpx.AsyncClientの生成はSSLコンテキスト構築（CA証明書バンドルの読み込み・パース）を
# 伴い、リクエストごとに作るとその構築コストがイベントループを同期的にブロックする。
# timeoutの値ごとに1つだけ生成して使い回す。
_clients: dict[float, httpx.AsyncClient] = {}


def get_http_client(timeout: float) -> httpx.AsyncClient:
    if timeout not in _clients:
        _clients[timeout] = httpx.AsyncClient(timeout=timeout)
    return _clients[timeout]


async def close_all_http_clients() -> None:
    """プロセス終了時にmain.pyのlifespanシャットダウン段から呼ぶ。"""
    for client in _clients.values():
        await client.aclose()
    _clients.clear()
