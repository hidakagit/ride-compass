"""Redis cache-asideのテストが共有するフェイク。

実装側（`redis_json_cache`・`jma_tile_redis_cache`）が使うコマンドは`get`/`set`だけの
ため、フェイクもその2つで足りる。`raise_on_get`/`raise_on_set`には送出させたい例外を
渡す（Redis不通時にfail-openすることの検証に使う）。
"""


class FakeRedis:
    def __init__(self, raise_on_get=None, raise_on_set=None):
        self.store: dict[str, str] = {}
        self._raise_on_get = raise_on_get
        self._raise_on_set = raise_on_set

    async def get(self, key):
        if self._raise_on_get:
            raise self._raise_on_get
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        if self._raise_on_set:
            raise self._raise_on_set
        self.store[key] = value
