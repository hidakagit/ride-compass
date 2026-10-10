import httpx

# httpx.AsyncClientの生成はSSLコンテキスト構築（CA証明書バンドルの読み込み・パース）を
# 伴い、リクエストごとに作るとその構築コストがイベントループを同期的にブロックする。
# timeoutの値ごとに1つだけ生成して使い回す。
_clients: dict[float, httpx.AsyncClient] = {}

#: 軽いJSON・CSVを取りに行く外部API（警報・アメダス・WBGT・洪水予報）のタイムアウト（秒）。
JSON_API_TIMEOUT = 10.0
#: 地図のタイルを中継する外部（ベースマップ・JMA・GSI）のタイムアウト（秒）。
TILE_PROXY_TIMEOUT = 15.0


def get_http_client(timeout: float) -> httpx.AsyncClient:
    if timeout not in _clients:
        _clients[timeout] = httpx.AsyncClient(timeout=timeout)
    return _clients[timeout]


async def close_all_http_clients() -> None:
    """プロセス終了時に`process_resources.py: close_process_resources`から呼ぶ。"""
    for client in _clients.values():
        await client.aclose()
    _clients.clear()
