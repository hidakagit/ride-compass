"""MSM（メソスケールモデル、5kmメッシュ）データのRedis保存インターフェース（改善計画T387）。

GRIB2バイナリの実解析（parse_grib2）は将来のタスクへ委ねるスケルトンで、ここでは
「解析済みレコードをどう保存・取得するか」というRedis側のデータ構造だけを定義する。

Keyパターン: `jma:msm:{mesh_id}`（Redis Hash）、TTL 2時間。JMA気象データは短命のため
PostGISへは書き込まない（CLAUDE.md「JMA気象データ連携・キャッシュ基盤」節）。
"""

import logging

from app.domain.jma_msm import MsmMeshRecord
from app.infrastructure.debug_log import log_throttled_warning
from app.infrastructure.redis_client import (
    get_redis_client,
    record_redis_failure,
    record_redis_success,
    redis_available,
)

logger = logging.getLogger("app.services.jma_msm_service")

_KEY_PREFIX = "jma:msm"
_TTL_SECONDS = 2 * 60 * 60


def _key(mesh_id: str) -> str:
    return f"{_KEY_PREFIX}:{mesh_id}"


def parse_grib2_stub(raw_grib2: bytes) -> list[MsmMeshRecord]:
    """MSM GRIB2バイナリを`MsmMeshRecord`のリストへ解析する（未実装スケルトン）。

    実装にはpygrib/cfgrib等のGRIB2デコードライブラリ（ネイティブ依存を伴う）が必要で、
    導入判断（依存追加）は本タスクのスコープ外のため意図的に未実装のままにしてある。
    将来この関数を実装する際は、戻り値を`save_batch`へそのまま渡せば保存経路は
    そのまま使える。
    """
    raise NotImplementedError("MSM GRIB2解析は未実装（改善計画T387はデータ構造のみ定義）")


async def save_batch(records: list[MsmMeshRecord]) -> None:
    """解析済みMSMレコードをメッシュ単位でRedis Hashへバッチ保存する。

    書き込み失敗はメッシュ単位で握りつぶし、他メッシュの保存は継続する（気象データの
    部分欠損は他のJMA/Open-Meteo連携と同じfail-open方針）。
    """
    if not records or not redis_available():
        return
    client = get_redis_client()
    try:
        pipe = client.pipeline(transaction=False)
        for record in records:
            key = _key(record.mesh_id)
            pipe.hset(
                key,
                mapping={
                    "u_wind": record.u_wind,
                    "v_wind": record.v_wind,
                    "temp": record.temp,
                    "precip_1h": record.precip_1h,
                    "valid_time": record.valid_time,
                },
            )
            pipe.expire(key, _TTL_SECONDS)
        await pipe.execute()
    except Exception as exc:  # noqa: BLE001 書き込み失敗はバッチ全体を失敗させない
        record_redis_failure()
        log_throttled_warning("cache:jma-msm-redis", "[cache:jma-msm-redis] write failed error=%r", exc)
    else:
        record_redis_success()


async def get_mesh(mesh_id: str) -> MsmMeshRecord | None:
    if not redis_available():
        return None
    client = get_redis_client()
    try:
        fields = await client.hgetall(_key(mesh_id))
    except Exception as exc:  # noqa: BLE001
        record_redis_failure()
        log_throttled_warning("cache:jma-msm-redis", "[cache:jma-msm-redis] read failed error=%r", exc)
        return None
    record_redis_success()
    if not fields:
        return None
    return MsmMeshRecord(
        mesh_id=mesh_id,
        u_wind=float(fields["u_wind"]),
        v_wind=float(fields["v_wind"]),
        temp=float(fields["temp"]),
        precip_1h=float(fields["precip_1h"]),
        valid_time=fields["valid_time"],
    )
