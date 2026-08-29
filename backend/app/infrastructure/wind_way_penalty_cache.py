"""way_id→wind_penalty配信層（改善計画T405→T414で作り直し）専用のRedis cache-asideキャッシュ。

`wind_forecast_cache.py`（風グリッド地点そのもののキャッシュ）とは別レイヤー。

**T414での設計変更**: 旧実装（T405）は`way_id`をキーに、道路自身の向き（OSM格納方向）と
風グリッド値から計算したway単位の評価値をキャッシュしていた。訂正後の契約
（docs/tasks/T400.md「2.」節）では、ある道路のwind_penaltyは「その道路が属するタイルの
最寄り風グリッド点の値」と「ユーザーが指定した単一の向き（全道路共通、コンパススライダー
由来）」だけから決まり、道路自身の向きは計算に一切関与しない。つまり**同じタイル内の全ての
wayは常に同じwind_penalty値を持つ**（風グリッドはタイルの中心1点で代表させる既存の近似、
wind_way_service.py参照）。そのため、way_idごとに個別の値をキャッシュする意味が無くなり、
`(タイル, 時刻バケット, 向きバケット)`につき1個のスカラー値だけをキャッシュすれば足りる
——旧設計の「way_idの数だけキーが増える」キャッシュ空間から、「タイルの数だけキーが増える」
はるかに小さいキャッシュ空間へ縮小した。

キーには時刻の1時間バケット（`YYYY-MM-DDTHH`）に加えて、向きの5度バケットを含める。
向きはユーザーがスライダーで連続的に指定する値（0〜360度）のため、バケット化せずそのまま
キーへ使うとキャッシュヒット率がほぼ0になってしまう（スライダーをわずかに動かすたびに
別キー扱いになる）。5度刻みなら72通りのバケットに収まり、同じ向き付近を指す別ユーザー・
別操作の間でキャッシュが共有されつつ、wind_penalty＝speed×cos(角度差)の値としては5度の
丸め誤差は体感できるほど大きくない（cos関数はなだらかで、角度差が0/180度付近以外では
5度のずれによる値の変化はごくわずか）。

TTLは`weather_client.WIND_GRID_CACHE_TTL_SECONDS`（風グリッドの新鮮判定TTL、3時間）に
合わせる——バケット自体がキーに含まれるため、TTLは正しさの担保ではなく単なるRedis側の
自動ガベージコレクション（無限に古いバケット×向きの組み合わせのキーが溜まり続けるのを
防ぐ）としての役割になる。

**正本を持たないキャッシュ**（wind_forecast_cache.pyと同じ性質）: 失っても風グリッド・
タイル中心座標から再計算すればよいだけで、失敗時はfail-open（未キャッシュとして扱い実計算へ
進む）。Redis障害時も機能は止まらない（再計算コストが少し増えるだけ）。
"""

from app.infrastructure.debug_log import log_throttled_warning
from app.infrastructure.redis_client import (
    get_redis_client,
    record_redis_failure,
    record_redis_success,
    redis_available,
)
from app.infrastructure.weather_client import WIND_GRID_CACHE_TTL_SECONDS

_KEY_PREFIX = "wind:tile-penalty"
_TTL_SECONDS = WIND_GRID_CACHE_TTL_SECONDS

# 向きバケットの粒度（度）。モジュールdocstring参照。
BEARING_BUCKET_DEG = 5


def bearing_bucket(bearing_deg: float) -> int:
    """向き（0〜360度、範囲外は正規化）をBEARING_BUCKET_DEG刻みのバケット番号（int）へ
    丸める。360度は0度と同じバケットに正規化する（`% 360`をBEARING_BUCKET_DEG丸めの後に
    適用するため、359度台の値がBEARING_BUCKET_DEG刻み数で割り切れずズレたバケットへ
    分類されることはない）。"""
    normalized = bearing_deg % 360
    return round(normalized / BEARING_BUCKET_DEG) % (360 // BEARING_BUCKET_DEG)


def _key(z: int, x: int, y: int, hour_bucket: str, bearing_bucket_value: int) -> str:
    return f"{_KEY_PREFIX}:{z}:{x}:{y}:{hour_bucket}:{bearing_bucket_value}"


async def get_tile_penalty(z: int, x: int, y: int, hour_bucket: str, bearing_deg: float) -> float | None:
    """指定タイル・時刻バケット・向きバケットに対応するwind_penaltyスカラー値を返す
    （タイル内の全wayに共通の値、モジュールdocstring参照）。未キャッシュ・Redis疎通不能は
    Noneへfail-openする（呼び出し元は実計算へ進む）。"""
    if not redis_available():
        return None
    client = get_redis_client()
    key = _key(z, x, y, hour_bucket, bearing_bucket(bearing_deg))
    try:
        raw = await client.get(key)
    except Exception as exc:  # noqa: BLE001 Redis障害は「未キャッシュ」へのfail-open対象
        record_redis_failure()
        log_throttled_warning("cache:wind-tile-penalty-redis", "[cache:wind-tile-penalty-redis] read failed error=%r", exc)
        return None
    record_redis_success()
    if raw is None:
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        # 壊れたエントリ（手動編集等）は未キャッシュ扱いにする。
        return None


async def set_tile_penalty(z: int, x: int, y: int, hour_bucket: str, bearing_deg: float, value: float) -> None:
    """新規に計算できたwind_penaltyスカラー値をRedisへ書き戻す（キャッシュの最適化であり、
    書き込み失敗はレスポンス自体の成否には関与しない。失敗時は抑制付きWARNINGで記録する
    だけに留める）。"""
    if not redis_available():
        return
    client = get_redis_client()
    key = _key(z, x, y, hour_bucket, bearing_bucket(bearing_deg))
    try:
        await client.set(key, str(value), ex=_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001 書き込み失敗は次回の実計算で自己修復する
        record_redis_failure()
        log_throttled_warning("cache:wind-tile-penalty-redis", "[cache:wind-tile-penalty-redis] write failed error=%r", exc)
    else:
        record_redis_success()
