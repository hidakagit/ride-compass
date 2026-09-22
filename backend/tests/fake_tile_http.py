"""タイル・バイナリ配信のクライアントのテストが共有するHTTPフェイク。

`jma_tile_client`・`gsi_tile_client`・`basemap_client`は上流のレスポンスを
バイト列のまま通す設計のため、フェイク側が持つのは`content`・`content-type`・
`status_code`（/api/debug/statsの集計へ載る）だけでよい。
"""


class FakeResponse:
    """`content_type=None`を渡すと**ヘッダそのものが無い**応答になる。

    上流がContent-Typeを付けずに返すことは実際にあり、そのときクライアントが既定へ
    倒せるかは、ヘッダを持たない応答でしか確かめられない（空文字のヘッダとは別物）。
    """

    def __init__(self, content: bytes, content_type: str | None, status_code: int = 200):
        self.content = content
        self.headers = {} if content_type is None else {"content-type": content_type}
        self.status_code = status_code

    def raise_for_status(self):
        pass


class FakeHttpClient:
    """同じレスポンスを返し続け、要求されたURLを記録する。

    `raises`を渡すと、レスポンスを返す代わりにその例外を送出する（上流障害の再現用）。
    """

    def __init__(self, content: bytes, content_type: str | None, raises=None, status_code: int = 200):
        self._content = content
        self._content_type = content_type
        self._raises = raises
        self._status_code = status_code
        self.requested_urls = []

    async def get(self, url):
        self.requested_urls.append(url)
        if self._raises:
            raise self._raises
        return FakeResponse(self._content, self._content_type, self._status_code)
