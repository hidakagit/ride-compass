"""タイル・バイナリ配信のクライアントのテストが共有するHTTPフェイク。

`jma_tile_client`・`gsi_relief_tile_client`・`basemap_client`は上流のレスポンスを
バイト列のまま通す設計のため、フェイク側も`content`と`content-type`だけを持てば足りる。
"""


class FakeResponse:
    def __init__(self, content: bytes, content_type: str):
        self.content = content
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        pass


class FakeHttpClient:
    """同じレスポンスを返し続け、要求されたURLを記録する。

    `raises`を渡すと、レスポンスを返す代わりにその例外を送出する（上流障害の再現用）。
    """

    def __init__(self, content: bytes, content_type: str, raises=None):
        self._content = content
        self._content_type = content_type
        self._raises = raises
        self.requested_urls = []

    async def get(self, url):
        self.requested_urls.append(url)
        if self._raises:
            raise self._raises
        return FakeResponse(self._content, self._content_type)
