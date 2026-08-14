import time
from collections import defaultdict

# 路面ベクタタイル・basemapプロキシは認証なしで叩けるため、x/y（または path）を
# 総当たりされるとディスク（tile_cache）や上流（Overpass/OpenFreeMap）への負荷が
# 無制限にかかりうる。プロセス内メモリのみの簡易な固定窓レート制限で歯止めをかける
# （標高・天候キャッシュと同じ「プロセス内・永続化なし」の割り切り）。
_WINDOW_SECONDS = 60.0
_hits: dict[str, list[float]] = defaultdict(list)

# _hitsはウィンドウ超過分のタイムスタンプを都度間引くが、キー自体（"category:IP"）は
# アクセスが無くなった後も残り続けるため、一度でもアクセスしたIPが辞書に無期限に
# 溜まり続けるメモリリークになる（IPをローテーションされると特に顕著）。定期的に
# 全キーを掃除して、直近ウィンドウ内にヒットが無いキーを削除する。
_SWEEP_INTERVAL_SECONDS = 300.0
_last_sweep = time.monotonic()


def _sweep(now: float) -> None:
    cutoff = now - _WINDOW_SECONDS
    stale_client_ids = [client_id for client_id, hits in _hits.items() if not hits or hits[-1] <= cutoff]
    for client_id in stale_client_ids:
        del _hits[client_id]


def check_rate_limit(client_id: str, max_requests: int, window_seconds: float = _WINDOW_SECONDS) -> bool:
    """client_idからの直近window_seconds秒間のリクエスト数がmax_requests以下ならTrue（許可）。"""
    global _last_sweep
    now = time.monotonic()
    hits = _hits[client_id]
    cutoff = now - window_seconds
    while hits and hits[0] <= cutoff:
        hits.pop(0)
    if len(hits) >= max_requests:
        return False
    hits.append(now)
    if now - _last_sweep >= _SWEEP_INTERVAL_SECONDS:
        _sweep(now)
        _last_sweep = now
    return True
