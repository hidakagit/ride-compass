"""外部ソースの取込。**経路は1本で、ソースごとに違うのはアダプタだけ**。

アダプタが持つのは「外部の形を開いて1件ずつ返す」ことだけである。ステージング・
差し替え・run記録・パーティションの選択・絞り込みの宣言の記録は、すべてこのモジュールが
引き受ける。ソースが増えても、増えるのはアダプタ1本と`source_profile.yaml`の1エントリだけ。

ジオメトリはアダプタからWKBで受け取る。点・線・面を同じ経路へ載せるためで、形ごとに
書き込みを分けない。

差し替えは「そのソースのパーティションを空にしてから入れ直す」。同一トランザクション内で
行うため、途中の状態が読まれることはない。
"""

import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import asyncpg

from app.batch.source_profile import SourceProfile, SourceSpec, Target

logger = logging.getLogger("ridecompass.ingest")

#: 1回のCOPYへ積む件数。大きすぎるとメモリが膨らみ、小さすぎると往復が増える。
COPY_CHUNK = 20_000


@dataclass(frozen=True)
class SourceRecord:
    """外部ソースの1件。アダプタが返す唯一の形。"""

    #: 外部が持つ識別子。同じソースの中で一意。
    natural_key: str
    #: WKB（SRID 4326の座標で作る）。
    geom_wkb: bytes
    #: 外部が持っていた属性。取込の時点では何も捨てない。
    attrs: dict[str, Any]
    #: 属性として読めない配列実体（ラスタの画素・参照ノードid列・タイル本体）。
    payload: bytes | None = None


#: プロファイルの`adapter`名 → 実装。**ソースを足す唯一の追加点**。
#:
#: 非同期にするのは、外部からタイル単位で取るソースが並行取得を要るため。同期で足りる
#: ソース（ローカルのCSVを読むだけ等）も同じ契約に乗せ、経路を2本にしない。
SourceAdapter = Callable[[SourceSpec, SourceProfile], AsyncIterator[SourceRecord]]
ADAPTERS: dict[str, SourceAdapter] = {}


def register_adapter(name: str) -> Callable[[SourceAdapter], SourceAdapter]:
    def decorate(fn: SourceAdapter) -> SourceAdapter:
        if name in ADAPTERS:
            raise ValueError(f"アダプタ名が重複しています: {name}")
        ADAPTERS[name] = fn
        return fn

    return decorate


def partition_table_name(source: str) -> str:
    return f"source_features_{source}"


async def ensure_partition(conn: asyncpg.Connection, source: str) -> None:
    """そのソースの子パーティションを用意する。

    どのソースが在るかはデータで決まるため、宣言（ORMモデル）ではなく取込の側が作る。
    """
    await conn.execute(
        f'CREATE TABLE IF NOT EXISTS "{partition_table_name(source)}" '
        f"PARTITION OF source_features FOR VALUES IN ($tag${source}$tag$)"
    )


async def _open_run(conn: asyncpg.Connection, spec: SourceSpec, profile: SourceProfile,
                    origin: dict[str, Any]) -> int:
    return await conn.fetchval(
        "INSERT INTO source_runs (source, status, started_at, origin, profile, counts) "
        "VALUES ($1, 'running', $2, $3, $4, $5) RETURNING run_id",
        spec.name,
        datetime.now(timezone.utc),
        _json(origin),
        _json({"profile_hash": profile.profile_hash, "target": _target_dict(profile.target),
               "source": _source_dict(spec)}),
        _json({}),
    )


async def _close_run(conn: asyncpg.Connection, run_id: int, status: str,
                     counts: dict[str, Any]) -> None:
    await conn.execute(
        "UPDATE source_runs SET status = $2, finished_at = $3, counts = $4 WHERE run_id = $1",
        run_id, status, datetime.now(timezone.utc), _json(counts),
    )


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)


def _target_dict(target: Target) -> dict[str, Any]:
    return {"prefectures": list(target.prefectures) if target.prefectures else "all",
            "bbox": list(target.bbox)}


def _source_dict(spec: SourceSpec) -> dict[str, Any]:
    return {"name": spec.name, "adapter": spec.adapter, "rows": spec.rows,
            "grid": spec.grid, "columns": spec.columns, "tags": spec.tags}


async def ingest_source(
    conn: asyncpg.Connection,
    profile: SourceProfile,
    source_name: str,
    origin: dict[str, Any] | None = None,
) -> int:
    """1ソースぶんを取り込み、`run_id`を返す。

    既にあるそのソースの行は入れ替える。呼び出し側はトランザクションを開いておくこと
    （途中で落ちたら run は`failed`のまま残り、行は元のまま）。
    """
    spec = profile.source(source_name)
    adapter = ADAPTERS.get(spec.adapter)
    if adapter is None:
        raise ValueError(f"未登録のアダプタです: {spec.adapter}（{source_name}）")

    await ensure_partition(conn, spec.name)
    run_id = await _open_run(conn, spec, profile, origin or {})
    started = time.perf_counter()

    staging = f"_stage_{spec.name}"
    await conn.execute(f'CREATE TEMP TABLE "{staging}" '
                       "(natural_key text, geom_wkb bytea, attrs jsonb, payload bytea) "
                       "ON COMMIT DROP")

    written = 0
    batch: list[tuple[str, bytes, str, bytes | None]] = []
    async for record in adapter(spec, profile):
        batch.append((record.natural_key, record.geom_wkb, _json(record.attrs), record.payload))
        if len(batch) >= COPY_CHUNK:
            await conn.copy_records_to_table(
                staging, records=batch,
                columns=["natural_key", "geom_wkb", "attrs", "payload"])
            written += len(batch)
            batch.clear()
    if batch:
        await conn.copy_records_to_table(
            staging, records=batch, columns=["natural_key", "geom_wkb", "attrs", "payload"])
        written += len(batch)

    # そのソースぶんだけを入れ替える。パーティションを切ってあるので他のソースへ触らない。
    await conn.execute(f'TRUNCATE "{partition_table_name(spec.name)}"')
    await conn.execute(
        f'INSERT INTO "{partition_table_name(spec.name)}" '
        "(source, natural_key, run_id, geom, attrs, payload) "
        "SELECT $1, natural_key, $2, ST_SetSRID(ST_GeomFromWKB(geom_wkb), 4326), attrs, payload "
        f'FROM "{staging}"',
        spec.name, run_id,
    )

    elapsed = time.perf_counter() - started
    await _close_run(conn, run_id, "succeeded",
                     {"records": written, "elapsed_seconds": round(elapsed, 1)})
    logger.info("取込完了: source=%s run_id=%d records=%d elapsed=%.1fs",
                spec.name, run_id, written, elapsed)
    return run_id
