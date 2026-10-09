"""外部ソースの取込。**経路は1本で、ソースごとに違うのはアダプタだけ**。

アダプタが持つのは「外部の形を開いて1件ずつ返す」ことだけである。ステージング・
差し替え・run記録・パーティションの選択・絞り込みの宣言の記録は、すべてこのモジュールが
引き受ける。ソースを足すときに書くのはアダプタ（`source_adapters/__init__.py`で読み込んで登録する）と
`source_profile.yaml`のエントリで、この経路は書き換えない。派生・読み手がそのソースを名指して読むなら、
`infrastructure/source_models.py: Source`にも名前を足す。

ジオメトリはアダプタからWKBで受け取る。点・線・面を同じ経路へ載せるためで、形ごとに
書き込みを分けない。

差し替えは「そのソースのパーティションを空にしてから入れ直す」。同一トランザクション内で
行うため、途中の状態が読まれることはない。

取込は派生の作り直しと同時に走らない（`common.py: SOURCE_DATA_LOCK`）。作り直しが走っていれば
始めずに止まる。

**入力が前回と同じなら取り込まない。** 取込の行は、アダプタが読むファイルの中身・プロファイルの宣言・
アダプタのコード・ライブラリの版だけで決まる（どのアダプタも時刻・乱数・網の向こうを読まない）。取込はこれらから
指紋（`input_fingerprint`）を作って成功したrunへ残し、そのソースの成功した最新のrunと同じなら、行を入れ替えず、
新しいrunも作らずに、そのrunを返す。runが変わらないので、派生の作り直しも生データが変わっていないと読める。
読むファイルを言えないアダプタ（`inputs`を宣言しないもの）は、毎回取り込む。
"""

import hashlib
import json
import logging
import sys
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg
from sqlalchemy.orm import InstrumentedAttribute

from app.batch.code_fingerprint import code_fingerprint, library_versions
from app.batch.common import PROGRESS_INTERVAL_SECONDS, SOURCE_DATA_LOCK, format_progress
from app.batch.source_profile import NoFields, SourceProfile, SourceSpec
from app.infrastructure.source_models import SourceRunStatus, latest_succeeded_run_by_column_sql

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
class AdapterInputs:
    """アダプタが読む入力。取込は、行を読む前にこれを聞いて指紋（`input_fingerprint`）を作る。"""

    #: 読むファイル全部。読み方（どのファイルを開くか）はプロファイルと置き場で決まる。
    files: tuple[Path, ...]
    #: このソースのほかに、宣言（`rows`・`grid`）を読むソースの名前。
    sources: tuple[str, ...] = ()


#: アダプタが読む入力を、行を読まずに答える関数。
InputsOf = Callable[[SourceSpec, SourceProfile], AdapterInputs]


@dataclass(frozen=True)
class RegisteredAdapter:
    read: SourceAdapter
    #: プロファイルの`rows`/`grid`の型。読み込みはこのフィールドにある欄だけを受け付ける。
    rows: type
    grid: type
    #: このアダプタのソースの行が必ず持つ列（`SourceFeatureRow`の空を許す列）。取込が区画を作るときに
    #: NOT NULLで張り、`scripts/schema_gap.py`が実DBの区画と比べる。
    required: tuple[InstrumentedAttribute[Any], ...] = ()
    #: 読む入力。無ければ指紋を作れず、毎回取り込む。
    inputs: InputsOf | None = None


ADAPTERS: dict[str, RegisteredAdapter] = {}


def register_adapter(name: str, *, rows: type = NoFields, grid: type = NoFields,
                     required: tuple[InstrumentedAttribute[Any], ...] = (),
                     inputs: InputsOf | None = None
                     ) -> Callable[[SourceAdapter], SourceAdapter]:
    def decorate(fn: SourceAdapter) -> SourceAdapter:
        if name in ADAPTERS:
            raise ValueError(f"アダプタ名が重複しています: {name}")
        ADAPTERS[name] = RegisteredAdapter(read=fn, rows=rows, grid=grid, required=required, inputs=inputs)
        return fn

    return decorate


#: 成功したrunの`origin`に、取込が入力の指紋を書く項目。
INPUT_FINGERPRINT = "input_fingerprint"


def input_fingerprint(spec: SourceSpec, profile: SourceProfile) -> str | None:
    """そのソースの取込の入力の指紋。アダプタが入力を宣言していなければNone。

    入力は、読むファイルの場所と中身・範囲と読むソースの宣言・アダプタからたどれるコード
    （`code_fingerprint.py`）・Pythonとライブラリの版。ファイルは中身を全部読む——大きさと更新時刻が
    同じでも、中身が同じとは言えない。
    """
    registered = ADAPTERS[spec.adapter]
    if registered.inputs is None:
        return None
    inputs = registered.inputs(spec, profile)
    digest = hashlib.sha256(_json({
        "target": asdict(profile.target),
        "sources": [_source_dict(profile.source(name)) for name in (spec.name, *inputs.sources)],
        "code": code_fingerprint(registered.read.__module__),
        "python": sys.version,
        "libraries": library_versions(),
    }).encode())
    for name, path in sorted({str(path.resolve()): path for path in inputs.files}.items()):
        digest.update(name.encode())
        with path.open("rb") as file:
            digest.update(hashlib.file_digest(file, "sha256").digest())
    return digest.hexdigest()


def file_origin(path: "Path") -> dict[str, Any]:
    """読んだファイルの素性。**取り直したかどうかを後から言えるだけの材料**を残す。

    中身が同じかは、取込が別に残す入力の指紋（`input_fingerprint`）で言う。
    """
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()}


def partition_table_name(source: str) -> str:
    return f"source_features_{source}"


def partition_required_columns(spec: SourceSpec) -> tuple[str, ...]:
    """そのソースの区画が NOT NULL で持つ列（親の表が NOT NULL の列を除く）。アダプタの宣言から導く。"""
    return tuple(column.key for column in ADAPTERS[spec.adapter].required)


async def _ensure_partition(conn: asyncpg.Connection, spec: SourceSpec) -> None:
    """そのソースの子パーティションを用意する。

    どのソースが在るかはデータで決まるため、宣言（ORMモデル）ではなく取込の側が作る。
    空間の索引は親の表の宣言（`infrastructure/source_models.py: SourceFeatureRow`）にあり、PostgreSQLが
    子パーティションへ張る。アダプタが必ず持つと宣言した列は、作るときにNOT NULLで張る。在る区画へは
    張り直さない——張るには区画を読み通す排他ロックが要る。在る区画の欠けは`scripts/schema_gap.py`が出す。
    """
    table = partition_table_name(spec.name)
    required = partition_required_columns(spec)
    columns = f" ({', '.join(f'{column} NOT NULL' for column in required)})" if required else ""
    await conn.execute(
        f'CREATE TABLE IF NOT EXISTS "{table}" '
        f"PARTITION OF source_features{columns} FOR VALUES IN ($tag${spec.name}$tag$)"
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

    入力の指紋がそのソースの成功した最新のrunと同じなら、取り込まずにそのrunの`run_id`を返す。読むファイルが
    揃っていなければ、runを作らずに止まる。
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

    hashing = time.perf_counter()
    fingerprint = input_fingerprint(spec, profile)
    hashed = time.perf_counter() - hashing
    if fingerprint is not None:
        previous = await conn.fetchrow(
            f"SELECT run_id, origin ->> '{INPUT_FINGERPRINT}' AS fingerprint "
            f"FROM {latest_succeeded_run_by_column_sql('$1')} r", spec.name)
        if previous is not None and previous["fingerprint"] == fingerprint:
            logger.info("取り込まなかった（入力が前回と同じ）: source=%s 前回のrun_id=%d 入力の指紋=%.1fs",
                        spec.name, previous["run_id"], hashed)
            return previous["run_id"]

    await _ensure_partition(conn, spec)
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
                             {"records": written, "elapsed_seconds": round(elapsed, 1)},
                             {**origin, INPUT_FINGERPRINT: fingerprint})
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
    logger.info("取込完了: source=%s run_id=%d records=%d elapsed=%.1fs パーティションの排他ロック（待ちを含む）=%.1fs"
                " 入力の指紋=%.1fs", spec.name, run_id, written, elapsed, locked, hashed)
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
