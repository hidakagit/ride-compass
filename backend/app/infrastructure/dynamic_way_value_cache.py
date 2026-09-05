"""動的＋向きあり材料の「way_id→値」配信専用のRedis cache-asideキャッシュ。
`wind_forecast_cache.py`（風グリッド地点そのもののキャッシュ）とは別レイヤー。

キーは`(material_id, z, x, y, 時刻バケット, 向きバケット, 速度バケット)`。値は
`{way_id: 値}`のJSONオブジェクト——風のように「タイル内全wayが同値」の場合も勾配のように
「way単位で異なる値」の場合も同じ表現で吸収するため、材料側は「タイル単位でいくつ値を
返すか」を意識せずこのモジュールを共有できる（風はdict.fromkeys(way_ids, penalty)で
作った「全キー同値」のdictを渡すだけ）。

時刻バケットは1時間丸め（`YYYY-MM-DDTHH`、時刻に依存しない材料はNone）、向きバケットは
`BEARING_BUCKET_DEG`（5度）刻み（向きに依存しない材料はNone）、速度バケットは1km/h刻み
（速度に依存しない材料はNone）。バケット化する理由は、スライダーの連続値をそのまま
キーへ使うとキャッシュヒット率がほぼ0になるため。

TTLは呼び出し元（各材料のサービス）が渡す——風は気象データの新鮮さ
（`weather_client.WIND_GRID_CACHE_TTL_SECONDS`）に合わせる必要があるが、勾配は道路の向き・
標高由来の値でほぼ不変のため、材料ごとに異なる基準で決めてよい（このモジュール自体は
特定のTTL値を持たない）。

**正本を持たないキャッシュ**（wind_forecast_cache.pyと同じ性質）: 失っても呼び出し元が
再計算すればよいだけで、失敗時はfail-open（未キャッシュとして扱い実計算へ進む）。Redis
障害時も機能は止まらない（再計算コストが少し増えるだけ）。
"""

import json
import math

from app.infrastructure.debug_log import error_type_label, log_external_call
from app.infrastructure.redis_client import (
    get_redis_client_or_none,
    record_redis_failure,
    record_redis_success,
    redis_available,
)

_KEY_PREFIX = "dynway"

# 向きバケットの粒度（度）。モジュールdocstring参照。
BEARING_BUCKET_DEG = 5


def bearing_bucket(bearing_deg: float) -> int:
    """向き（0〜360度、範囲外は正規化）をBEARING_BUCKET_DEG刻みのバケット番号（int）へ
    丸める。360度は0度と同じバケットに正規化する（`% 360`をBEARING_BUCKET_DEG丸めの後に
    適用するため、359度台の値がBEARING_BUCKET_DEG刻み数で割り切れずズレたバケットへ
    分類されることはない）。組み込み`round()`は偶数への銀行丸め（非対称、境界の
    バケット幅が理論値からずれる）のため、`math.floor(x+0.5)`（四捨五入、0.5は常に
    切り上げ）を使い境界幅を均一にする。"""
    normalized = bearing_deg % 360
    return math.floor(normalized / BEARING_BUCKET_DEG + 0.5) % (360 // BEARING_BUCKET_DEG)


def speed_bucket(speed_kmh: float) -> int:
    """想定速度（km/h）を1km/h刻みのバケット番号へ丸める（向きと同じ理由で連続値をそのまま
    キーにしない）。"""
    return math.floor(speed_kmh + 0.5)


def _key(
    material_id: str, z: int, x: int, y: int, hour_bucket: str | None, bearing_deg: float | None,
    speed_kmh: float | None,
) -> str:
    bearing_token = str(bearing_bucket(bearing_deg)) if bearing_deg is not None else "-"
    speed_token = str(speed_bucket(speed_kmh)) if speed_kmh is not None else "-"
    return f"{_KEY_PREFIX}:{material_id}:{z}:{x}:{y}:{hour_bucket or '-'}:{bearing_token}:{speed_token}"


async def get_tile_values(
    material_id: str, z: int, x: int, y: int, hour_bucket: str | None, bearing_deg: float | None,
    speed_kmh: float | None = None,
) -> dict[int, float] | None:
    """指定タイル・材料・時刻バケット・向きバケット・速度バケット（速度に依存しない材料は
    None）に対応する`{way_id: 値}`を返す。
    未キャッシュ・Redis疎通不能・壊れたエントリはいずれもNoneへfail-openする（呼び出し元は
    実計算へ進む）。"""
    if not redis_available():
        return None
    client = get_redis_client_or_none()
    if client is None:
        return None
    key = _key(material_id, z, x, y, hour_bucket, bearing_deg, speed_kmh)
    with log_external_call(f"cache:dynway-{material_id}-redis") as fields:
        try:
            raw = await client.get(key)
        except Exception as exc:  # noqa: BLE001 Redis障害は「未キャッシュ」へのfail-open対象
            record_redis_failure()
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
            return None
        record_redis_success()
        if raw is None:
            fields["result"] = "ok"
            fields["cache"] = "miss"
            return None
        try:
            parsed = json.loads(raw)
            values = {int(way_id): float(value) for way_id, value in parsed.items()}
        except (ValueError, TypeError, json.JSONDecodeError, AttributeError):
            # 壊れたエントリ（手動編集等）は未キャッシュ扱いにする。
            fields["result"] = "ok"
            fields["cache"] = "miss"
            return None
        fields["result"] = "ok"
        fields["cache"] = "hit"
        return values


async def set_tile_values(
    material_id: str,
    z: int,
    x: int,
    y: int,
    hour_bucket: str | None,
    bearing_deg: float | None,
    values: dict[int, float],
    ttl_seconds: int,
    speed_kmh: float | None = None,
) -> None:
    """新規に計算できた`{way_id: 値}`をRedisへ書き戻す（キャッシュの最適化であり、
    書き込み失敗はレスポンス自体の成否には関与しない。失敗時は抑制付きWARNINGで記録する
    だけに留める）。"""
    if not redis_available():
        return
    client = get_redis_client_or_none()
    if client is None:
        return
    key = _key(material_id, z, x, y, hour_bucket, bearing_deg, speed_kmh)
    payload = json.dumps({str(way_id): value for way_id, value in values.items()})
    with log_external_call(f"cache:dynway-{material_id}-redis") as fields:
        try:
            await client.set(key, payload, ex=ttl_seconds)
        except Exception as exc:  # noqa: BLE001 書き込み失敗は次回の実計算で自己修復する
            record_redis_failure()
            fields["result"] = "error"
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
        else:
            record_redis_success()
            fields["result"] = "ok"
