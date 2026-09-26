import time

from cachetools import TTLCache

# 路面ベクタタイル・basemapプロキシは認証なしで叩けるため、x/y（または path）を
# 総当たりされるとディスク（tile_cache）や上流（Overpass/OpenFreeMap）への負荷が
# 無制限にかかりうる。プロセス内メモリのみの簡易な移動窓レート制限で歯止めをかける
# （標高・天候キャッシュと同じ「プロセス内・永続化なし」の割り切り）。
_WINDOW_SECONDS = 60.0

# 接続元が1回ずつ入れ替わりながら来る形で10万件≈40MB（コンテナの上限6GBの1%未満）。
# 1窓の間に来る接続元の数より十分大きく取る——超えると最も古い接続元の回数が忘れられる。
_MAX_CLIENTS = 100_000

# 期限は最後に通した1回から窓の長さなので、記録は中身が窓を出たときにちょうど消える。
# TTLCacheはスレッド安全でないが、呼び出し元はすべてイベントループ上のasyncハンドラである。
_hits: TTLCache[str, list[float]] = TTLCache(maxsize=_MAX_CLIENTS, ttl=_WINDOW_SECONDS)


def check_rate_limit(client_id: str, max_requests: int) -> bool:
    """client_idからの直近1窓のリクエスト数がmax_requests未満なら、1回を数えてTrue（許可）。"""
    now = time.monotonic()
    hits = [hit for hit in _hits.get(client_id, ()) if hit > now - _WINDOW_SECONDS]
    if len(hits) >= max_requests:
        return False
    hits.append(now)
    _hits[client_id] = hits
    return True
