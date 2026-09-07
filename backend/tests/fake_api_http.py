"""JSON・CSVを取得する外部APIクライアントのテストが共有するHTTPフェイク。

`flood_client`・`jma_warning_client`・`wbgt_client`はいずれも`simple_api_client`を
通して`get(url, params=..., timeout=...)`を呼ぶため、フェイクもその署名に合わせる。
`call_count`はキャッシュヒット（上流を呼ばないこと）の検証に、`last_params`は
クエリ組み立ての検証に使う。
"""

import httpx


class FakeResponse:
    def __init__(self, payload=None, *, text=None):
        self._payload = payload
        self._text = text

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload

    @property
    def text(self):
        return self._text


class FakeHttpClient:
    def __init__(self, payload=None, *, text=None):
        self.call_count = 0
        self.last_params = None
        self._payload = payload
        self._text = text

    async def get(self, url, params=None, timeout=None):
        self.call_count += 1
        self.last_params = params
        return FakeResponse(self._payload, text=self._text)


class FailingHttpClient:
    """接続そのものが失敗する上流。"""

    async def get(self, url, params=None, timeout=None):
        raise httpx.RequestError("boom")


class HttpStatusErrorResponse:
    status_code = 500

    def raise_for_status(self):
        raise httpx.HTTPStatusError("500 Server Error", request=None, response=self)


class HttpStatusErrorHttpClient:
    def __init__(self):
        self.call_count = 0

    async def get(self, url, params=None, timeout=None):
        self.call_count += 1
        return HttpStatusErrorResponse()
