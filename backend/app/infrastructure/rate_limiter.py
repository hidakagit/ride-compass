import time
from collections import defaultdict

# 路面ベクタタイル・basemapプロキシは認証なしで叩けるため、x/y（または path）を
# 総当たりされるとディスク（tile_cache）や上流（Overpass/OpenFreeMap）への負荷が
# 無制限にかかりうる。プロセス内メモリのみの簡易な固定窓レート制限で歯止めをかける
# （標高・天候キャッシュと同じ「プロセス内・永続化なし」の割り切り）。
_WINDOW_SECONDS = 60.0
_hits: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(client_id: str, max_requests: int, window_seconds: float = _WINDOW_SECONDS) -> bool:
    """client_idからの直近window_seconds秒間のリクエスト数がmax_requests以下ならTrue（許可）。"""
    now = time.monotonic()
    hits = _hits[client_id]
    cutoff = now - window_seconds
    while hits and hits[0] <= cutoff:
        hits.pop(0)
    if len(hits) >= max_requests:
        return False
    hits.append(now)
    return True
