"""外部ソースの取込。**経路は1本で、ソースごとに違うのはアダプタだけ**。

アダプタが持つのは「外部の形を開いて1件ずつ返す」ことだけである。ステージング・
差し替え・run記録・パーティションの選択・絞り込みの宣言の記録は、すべてこのモジュールが
引き受ける。ソースが増えても、増えるのはアダプタ1本と`source_profile.yaml`の1エントリだけ。

ジオメトリはアダプタからWKBで受け取る。点・線・面を同じ経路へ載せるためで、形ごとに
書き込みを分けない。

差し替えは「そのソースのパーティションを空にしてから入れ直す」。同一トランザクション内で
行うため、途中の状態が読まれることはない。

取込は派生の作り直しと同時に走らない（`common.py: SOURCE_DATA_LOCK`）。作り直しが走っていれば
始めずに止まる。
"""

import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg

from app.batch.common import PROGRESS_INTERVAL_SECONDS, SOURCE_DATA_LOCK, format_progress
from app.batch.source_profile import NoFields, SourceProfile, SourceSpec
from app.infrastructure.source_models import SourceRunStatus

logger = logging.getLogger("ridecompass.ingest")


@dataclass(frozen=True)
class SourceRecord:
    """外部ソースの1件。アダプタが返す唯一の形。"""

    #: 外部が持つ識別子。同じソースの中で一意。
    natural_key: str
    #: WKB（SRID 4326の座標で作る）。
    geom_wkb: bytes
    #: 外部が持っていた属性。取込の時点では何も捨てない。
    attrs: dict[str, Any]
    #: 属性として読めない配列実体（参照ノードid列・タイル本体）。
    payload: bytes | None = None
    #: 面のソースの画素（raster WKB。`raster_wkb.tile_raster_wkb`が作る）。
    rast: bytes | None = None


#: プロファイルの`adapter`名 → 実装。**ソースを足す唯一の追加点**。
#:
#: 非同期にするのは、外部からタイル単位で取るソースが並行取得を要るため。同期で足りる
#: ソース（ローカルのCSVを読むだけ等）も同じ契約に乗せ、経路を2本にしない。
#:
#: 第3引数は`origin`。**どこから取ったかを知っているのはアダプタだけ**なので、ここへ
#: 書き込ませて`source_runs.origin`へ残す。呼び出し側は中身を知らない——ソースごとに
#: 意味のある項目が違い、共通の型を決めるとソースを足すたびに型が増える。
SourceAdapter = Callable[
    [SourceSpec, SourceProfile, dict[str, Any]], AsyncIterator[SourceRecord]]


@dataclass(frozen=True)
class RegisteredAdapter:
    read: SourceAdapter
    #: プロファイルの`rows`/`grid`の型。読み込みはこのフィールドにある欄だけを受け付ける。
    rows: type
    grid: type


ADAPTERS: dict[str, RegisteredAdapter] = {}


def register_adapter(name: str, *, rows: type = NoFields,
                     grid: type = NoFields) -> Callable[[SourceAdapter], SourceAdapter]:
    def decorate(fn: SourceAdapter) -> SourceAdapter:
        if name in ADAPTERS:
            raise ValueError(f"アダプタ名が重複しています: {name}")
        ADAPTERS[name] = RegisteredAdapter(read=fn, rows=rows, grid=grid)
        return fn

    return decorate


def file_origin(path: "Path") -> dict[str, Any]:
    """読んだファイルの素性。**取り直したかどうかを後から言えるだけの材料**を残す。

    中身のハッシュは取らない——GB級のファイルを取込のたびにもう一度読むことになる。
    """
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()}


def partition_table_name(source: str) -> str:
    return f"source_features_{source}"


async def _ensure_partition(conn: asyncpg.Connection, source: str) -> None:
    """そのソースの子パーティションを用意する。

    どのソースが在るかはデータで決まるため、宣言（ORMモデル）ではなく取込の側が作る。
    空間の索引は親の表の宣言（`infrastructure/source_models.py: SourceFeatureRow`）にあり、PostgreSQLが
    子パーティションへ張る。
    """
    table = partition_table_name(source)
    await conn.execute(
        f'CREATE TABLE IF NOT EXISTS "{table}" '
        f"PARTITION OF source_features FOR VALUES IN ($tag${source}$tag$)"
    )


async def _open_run(conn: asyncpg.Connection, spec: SourceSpec, profile: SourceProfile,
                    origin: dict[str, Any]) -> int:
    return await conn.fetchval(
        "INSERT INTO source_runs (source, status, started_at, origin, profile, counts) "
        "VALUES ($1, $2, $3, $4, $5, $6) RETURNING run_id",
        spec.name,
        SourceRunStatus.RUNNING,
        datetime.now(timezone.utc),
        _json(origin),
        _json({"profile_hash": profile.profile_hash, "target": asdict(profile.target),
               "source": _source_dict(spec)}),
        _json({}),
    )


async def _close_run(conn: asyncpg.Connection, run_id: int, status: SourceRunStatus,
                     counts: dict[str, Any], origin: dict[str, Any]) -> None:
    """runを閉じる。`origin`はアダプタが走り終わってからでないと確定しないため、
    開くときではなくここで書く（ファイルの実体・配信元のタイムスタンプは、読みに
    行って初めて分かる）。"""
    await conn.execute(
        "UPDATE source_runs SET status = $2, finished_at = $3, counts = $4, origin = $5 "
        "WHERE run_id = $1",
        run_id, status, datetime.now(timezone.utc), _json(counts), _json(origin),
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _source_dict(spec: SourceSpec) -> dict[str, Any]:
    return {"name": spec.name, "adapter": spec.adapter,
            "rows": asdict(spec.rows), "grid": asdict(spec.grid)}


async def ingest_source(
    conn: asyncpg.Connection,
    profile: SourceProfile,
    source_name: str,
) -> int:
    """1ソースぶんを取り込み、`run_id`を返す。

    既にあるそのソースの行は入れ替える。`conn`はトランザクションの外で渡す——runを開く記録と
    失敗の記録は、行の入れ替えとは別のトランザクションで書く。入れ替えが途中で落ちても行は元の
    ままで、runは`failed`で残る。成功の記録は入れ替えと同じトランザクションで書くので、
    `succeeded`のrunの行は必ず入っている。
    """
    if conn.is_in_transaction():
        raise RuntimeError("取込はトランザクションの外の接続で呼ぶ（中で呼ぶと、失敗の記録が行と一緒に巻き戻る）")
    if not await conn.fetchval("SELECT pg_try_advisory_lock_shared(hashtext($1))", SOURCE_DATA_LOCK):
        raise RuntimeError("派生の作り直しが走っている")
    try:
        return await _ingest(conn, profile, source_name)
    finally:
        await conn.execute("SELECT pg_advisory_unlock_shared(hashtext($1))", SOURCE_DATA_LOCK)


async def _ingest(conn: asyncpg.Connection, profile: SourceProfile, source_name: str) -> int:
    spec = profile.source(source_name)
    adapter = ADAPTERS[spec.adapter].read

    await _ensure_partition(conn, spec.name)
    origin: dict[str, Any] = {}
    run_id = await _open_run(conn, spec, profile, origin)
    started = time.perf_counter()
    written = 0

    async def rows() -> AsyncIterator[tuple[str, bytes, str, bytes | None, bytes | None]]:
        nonlocal written
        last_report = started
        async for record in adapter(spec, profile, origin):
            written += 1
            now = time.perf_counter()
            if now - last_report >= PROGRESS_INTERVAL_SECONDS:
                last_report = now
                logger.info("取込中 source=%s %s", spec.name,
                            format_progress(written, None, now - started))
            yield (record.natural_key, record.geom_wkb, _json(record.attrs),
                   record.payload, record.rast)

    try:
        async with conn.transaction():
            locked_at = await _replace_rows(conn, spec.name, run_id, rows())
            elapsed = time.perf_counter() - started
            await _close_run(conn, run_id, SourceRunStatus.SUCCEEDED,
                             {"records": written, "elapsed_seconds": round(elapsed, 1)}, origin)
        locked = time.perf_counter() - locked_at
    except BaseException:
        elapsed = time.perf_counter() - started
        logger.warning("取込失敗: source=%s run_id=%d records=%d elapsed=%.1fs",
                       spec.name, run_id, written, elapsed)
        try:
            await _close_run(conn, run_id, SourceRunStatus.FAILED,
                             {"records": written, "elapsed_seconds": round(elapsed, 1)}, origin)
        except Exception:
            logger.warning("取込の失敗をrunへ書けなかった（runは running のまま残る）: run_id=%d",
                           run_id, exc_info=True)
        raise
    logger.info("取込完了: source=%s run_id=%d records=%d elapsed=%.1fs パーティションの排他ロック（待ちを含む）=%.1fs",
                spec.name, run_id, written, elapsed, locked)
    return run_id


async def _replace_rows(conn: asyncpg.Connection, source: str, run_id: int,
                        rows: AsyncIterator[tuple[str, bytes, str, bytes | None, bytes | None]]) -> float:
    """そのソースのパーティションの行を、`rows`で入れ替える。トランザクションの中で呼ぶ。

    パーティションの排他ロックを取りにいった時刻（`time.perf_counter()`）を返す。ロックはコミットまで続く。
    """
    staging = f"_stage_{source}"
    await conn.execute(f'CREATE TEMP TABLE "{staging}" '
                       "(natural_key text, geom_wkb bytea, attrs jsonb, payload bytea, rast bytea) "
                       "ON COMMIT DROP")

    # 行を溜めずに1本のCOPYへ流す。asyncpgは非同期のイテラブルを一定の大きさずつ送るため、
    # 取込が抱えるのは送りかけの分だけで、件数にも1件の大きさにもよらない。
    await conn.copy_records_to_table(
        staging, records=rows, columns=["natural_key", "geom_wkb", "attrs", "payload", "rast"])

    # そのソースぶんだけを入れ替える。パーティションを切ってあるので他のソースへ触らない。
    partition = partition_table_name(source)
    locked_at = time.perf_counter()
    await conn.execute(f'TRUNCATE "{partition}"')
    await conn.execute(
        f'INSERT INTO "{partition}" '
        "(source, natural_key, run_id, geom, attrs, payload, rast) "
        "SELECT $1, natural_key, $2, ST_SetSRID(ST_GeomFromWKB(geom_wkb), 4326), attrs, "
        # rasterは16進のテキストからしか作れない。DB側で変換し、転送量を倍にしない。
        "payload, encode(rast, 'hex')::raster "
        f'FROM "{staging}"',
        source, run_id,
    )
    # 入れ替えた直後に統計を作る。autovacuumは行数がしきい値（既定50）に満たない表を
    # 永久に拾わないため、タイルのように枚数の少ないソースは自動では統計を持てない。
    # 統計の無い表を派生が読むと、実行計画が桁で外れる。
    await conn.execute(f'ANALYZE "{partition}"')
    return locked_at
