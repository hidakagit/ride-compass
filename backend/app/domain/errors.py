class RoutingError(Exception):
    pass


class SearchAreaTooLargeError(Exception):
    """探索範囲の道路が多すぎて、1回の生成に使えるメモリへ収まらない。

    経路が無い（`RoutingError`）のとは別の理由で、利用者には範囲を狭めれば作れると伝える。
    """

    def __init__(self, road_edges: int, limit: int):
        super().__init__(f"road_edges={road_edges} limit={limit}")
        self.road_edges = road_edges
        self.limit = limit
