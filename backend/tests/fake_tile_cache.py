"""`tile_cache`（同期的なディスクI/O）の差し替え。

読み書きが走ったスレッドを憶える——タイルのプロキシは多数の要求が同時に来るため、
ディスクI/Oをイベントループ上で行うと同時に処理中の他の要求が止まる。それを
確かめられるのは、呼ばれたスレッドを見たときだけ。
"""

import threading


class FakeTileCache:
    def __init__(self, seed: dict | None = None):
        self.entries = dict(seed or {})
        self.thread_idents: list[int] = []

    def get(self, path):
        self.thread_idents.append(threading.get_ident())
        return self.entries.get(path)

    def set(self, path, content, content_type):
        self.thread_idents.append(threading.get_ident())
        self.entries[path] = (content, content_type)
