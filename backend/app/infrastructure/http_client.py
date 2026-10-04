import httpx

# httpx.AsyncClientの生成はSSLコンテキスト構築（CA証明書バンドルの読み込み・パース）を
# 伴い、リクエストごとに作るとその構築コストがイベントループを同期的にブロックする。
# timeoutの値ごとに1つだけ生成して使い回す。
clients: dict[float, httpx.AsyncClient] = {}


def get_http_client(timeout: float) -> httpx.AsyncClient:
    if timeout not in clients:
        clients[timeout] = httpx.AsyncClient(timeout=timeout)
    return clients[timeout]


async def close_all_http_clients() -> None:
    """プロセス終了時にmain.pyのlifespanシャットダウン段から呼ぶ。"""
    for client in clients.values():
        await client.aclose()
    clients.clear()
