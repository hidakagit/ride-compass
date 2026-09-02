class RoutingError(Exception):
    pass


class RouteDistanceExceededError(RoutingError):
    """周回探索中、残りレグの下限距離（直線距離）を足しても距離許容範囲の上限を
    確実に超えることが判明した場合の早期打ち切り（改善計画T540）。

    通常の`RoutingError`（経路そのものが見つからない等のエンジン都合の失敗）とは
    意味的に区別し、呼び出し元（`RouteGenerator.generate_loops`）が従来の距離フィルタ
    棄却（`filtered_out`）と同じ扱いで集計できるようにする。
    """

    pass
