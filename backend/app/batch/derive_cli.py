"""派生を作り直す入口。**順番と、段ごとの入力の宣言はここだけが持つ**。

生データを差し替えたら、下流を作り直す。段は次の依存で決まっており、並べ替えられない:
形（`road_edges`）が無いと材料の行が作れず、ノードの枝数が無いと交差点を数えられず、
区間の値が無いと道の値を導けない。

    .venv\\Scripts\\python.exe -m app.batch.derive_cli

**入力が前回の作り直しと同じ段は流さない。** 段の出力は、読むソースの取込・読む前の段の出力・較正値・書く表の列・
段のコード・実行環境の版（Python・ライブラリ・DB）だけで決まる（乱数・時刻・外部への問い合わせを読まない）ので、段ごとにこれらから指紋を作って
（`stage_fingerprints`）派生の記録（`derived_stages`）と比べ、同じ段は作業用のスキーマへ写した前回の値をそのまま使う。
前の段の指紋も入力に入れるので、流した段を読む後ろの段は必ず流れる。全部の段が同じなら、写しも道路網の配列も
入れ替えもせずに終える。段は単独の入口を持たない。

**区間の値がその区間の形と前の段の外の入力だけで決まる段（`DeriveStage.per_edge`）は、区間ごとに前回の値を写す。**
前の段が区間を作り直して段が流れても、前の段を除いた入力の指紋が前回と同じなら、段へ前回の表のスキーマ（`public`。
入れ替えまで前回の表が残っている）を渡し、形の同じ区間は前回の値を写させて、残りの区間だけを計算させる。

段が何を読むかは`STAGES`の宣言が持ち、宣言の漏れは段が読んだ表の数で見張る（`tests/test_derive_skip.py: test_each_stage_declares_what_it_reads_and_writes`）。
前の段（`after`）には、読む表を書く段と、自分が書く表の行を入れる・消す段を挙げる。同じ表の別の列だけを書く段は
挙げない——その段が流れても、自分の列は前回の値のまま正しい（例: `landcover`は`counts`を挙げない）。
作り直しは取込と同時に走らない（`common.py: SOURCE_DATA_LOCK`）。

**作り直しは作業用のスキーマで行い、道路網の配列まで作ってから1つのトランザクションで`public`の
表と入れ替える**（仕組みと理由は`docs/modules/backend/static-road-attributes.md`「派生」）。
段のSQLは表の名前をスキーマを付けずに書く——接続の`search_path`が作業用のスキーマを先に探し、
生データは`public`から読む。

**段が読む較正値は、作り直しを始めるときに1度だけDBの上書きから読み、段の関数へ値で渡す**。
バッチはwebアプリと別のプロセスで、プロセス内の較正値（`domain/tuning.py: TUNING_VALUES`）へは
何も読み込まれていない——そこを読むと、管理画面で変えた値ではなく宣言の既定が効く。
段へ渡るのは`STAGES`が宣言した較正値だけである。
"""

import argparse
import asyncio
import hashlib
import json
import logging
import shutil
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncpg  # noqa: E402

from app.batch import (  # noqa: E402
    derive_addresses,
    derive_counts,
    derive_elevation,
    derive_landcover,
    derive_node_materials,
    derive_stop_places,
    derive_topology,
    derive_way_materials,
)
from app.batch.code_fingerprint import code_fingerprint, library_versions  # noqa: E402
from app.batch.common import (  # noqa: E402
    SOURCE_DATA_LOCK,
    asyncpg_dsn,
    batch_session_factory,
    format_duration,
    run_batch_cli,
)
from app.infrastructure.tuning_overrides import load_tuning_values  # noqa: E402
from app.infrastructure import derived_data_meta, road_network_store  # noqa: E402
from app.infrastructure.derived_data_freshness import declared_columns, derived_tables  # noqa: E402
from app.infrastructure.road_graph_repository import RoadGraphRepository  # noqa: E402
from app.infrastructure.source_models import LATEST_SUCCEEDED_RUNS_SQL, Source  # noqa: E402

logger = logging.getLogger("ridecompass.derive_cli")


@dataclass(frozen=True)
class DeriveStage:
    """段1つの宣言。指紋（`stage_fingerprints`）は、ここに挙げた入力とコードから作る。"""

    name: str
    #: 段のモジュール。`derive(conn, **較正値)`を持ち、段のコードの指紋はここからたどる。
    module: ModuleType
    #: 読むソース。
    sources: frozenset[Source]
    #: 前の段（名前。この段より前にあるもの）。挙げる基準は冒頭。
    after: tuple[str, ...]
    #: 書く派生の表。
    tables: tuple[str, ...]
    #: `derive`の引数の名前 → 渡す較正値のid。
    tuning: Mapping[str, str] = field(default_factory=dict)
    #: 区間の値が、その区間の形と前の段の外の入力だけで決まり、ほかの区間を読まない。`derive`は引数`previous`に
    #: 前回の表のスキーマ（写せないならNone）を受け、形の同じ区間へ前回の値を写す。
    per_edge: bool = False

    async def run(self, conn: asyncpg.Connection, tuning: Mapping[str, float], previous: str | None) -> None:
        arguments: dict[str, object] = {argument: tuning[param] for argument, param in self.tuning.items()}
        if self.per_edge:
            arguments["previous"] = previous
        await self.module.derive(conn, **arguments)


def _outside_key(stage: DeriveStage) -> str:
    """区間ごとに写す段の、前の段を除いた入力の指紋を記録する名前。"""
    return f"{stage.name}/outside"


#: 区間を切る段が行を作り直す表（区間・ノード・道・区間の値）。
_ROAD_ROWS = ("road_edges", "node_materials", "way_materials", "edge_materials")

STAGES: tuple[DeriveStage, ...] = (
    DeriveStage("topology", derive_topology, frozenset({Source.OSM_WAY}), (), _ROAD_ROWS),
    DeriveStage("nodes", derive_node_materials, frozenset({Source.OSM_NODE, Source.OSM_WAY}), ("topology",),
                ("node_materials",), {"signal_radius_m": "signal.match_radius_m"}),
    DeriveStage("counts", derive_counts, frozenset({Source.OSM_NODE, Source.OSM_WAY, Source.ACCIDENT}),
                ("topology", "nodes"), ("edge_materials", "way_materials")),
    DeriveStage("elevation", derive_elevation, frozenset({Source.OSM_WAY, Source.DEM}), ("topology",), ("edge_materials",)),
    DeriveStage("landcover", derive_landcover, frozenset({Source.LULC}), ("topology",), ("edge_materials", "way_materials"),
                per_edge=True),
    DeriveStage("ways", derive_way_materials, frozenset({Source.OSM_WAY}), ("topology",), ("way_materials",)),
    # 住所の区画は、道路（`osm_way`）のパーティションを読まず、取込の記録から範囲だけを読む（読んだ数の見張りに出ないので、
    # 手で挙げる）。
    DeriveStage("addresses", derive_addresses, frozenset({Source.ABR, Source.ISJ_BLOCK, Source.OSM_WAY}), (),
                ("address_areas", "address_search_keys", "address_blocks")),
    DeriveStage("stop_places", derive_stop_places,
                frozenset({Source.OVERTURE_PLACE, Source.BUNKA_HERITAGE, Source.ESTAT_SMALL_AREA}), (),
                ("stop_places",)),
)


def stage_fingerprints(runs: Mapping[str, int], tuning: Mapping[str, float],
                       columns: Mapping[str, frozenset[str]], database: str) -> dict[str, str]:
    """段ごとの入力の指紋（段の名前 → 指紋）。区間ごとに写す段は、前の段を除いた入力の指紋も`_outside_key`の名前で持つ。
    `runs`は全ソースの成功した最新の取込、`columns`は派生の表の宣言の列、`database`はDBの版（PostgreSQLとPostGIS）。"""
    runtime = {"python": sys.version, "libraries": library_versions(), "database": database}
    fingerprints: dict[str, str] = {}
    for stage in STAGES:
        inputs = {
            "sources": {source: runs.get(source) for source in sorted(stage.sources)},
            "after": {name: fingerprints[name] for name in stage.after},
            "tuning": {param: tuning[param] for param in sorted(stage.tuning.values())},
            "columns": {table: sorted(columns[table]) for table in stage.tables},
            "code": code_fingerprint(stage.module.__name__),
            "runtime": runtime,
        }
        if stage.per_edge:
            fingerprints[_outside_key(stage)] = _digest({key: value for key, value in inputs.items() if key != "after"})
        fingerprints[stage.name] = _digest(inputs)
    return fingerprints


def _digest(inputs: Mapping[str, object]) -> str:
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


#: 作り直す間の表を置くスキーマ。同時に2本走ると互いの表を消し合うため、作り直しは排他の鍵
#: （`SOURCE_DATA_LOCK`）を取って1本に限る。
_WORK_SCHEMA = "derived_rebuild"

#: 入れ替えが読み手を待つ上限。入れ替えは表の排他ロックを取り、待つ間は後から来た読み手も
#: 後ろに並ぶ——長く読む相手（道路網の配列を作るデプロイの前処理等）がいると、その間の
#: タイル配信が止まる。上限で諦め、間を置いてやり直す。
_SWAP_LOCK_TIMEOUT = "5s"
_SWAP_ATTEMPTS = 60
_SWAP_RETRY_SECONDS = 10.0

#: 写す表の、索引を伴う制約（主キー・一意）と外部キー。外部キーは参照先の鍵の後に作る。
#: 定義は`search_path`が`public`だけのときに読むので、`public`の表は名前だけで出る——
#: 作業用のスキーマを先に探す接続で打てば、写した表どうしを指し、生データの表は`public`を指す。
_CONSTRAINTS_SQL = """
SELECT r.relname AS table_name, c.conname AS name, pg_get_constraintdef(c.oid) AS definition
FROM pg_constraint c
JOIN pg_class r ON r.oid = c.conrelid
JOIN pg_namespace n ON n.oid = r.relnamespace
WHERE n.nspname = 'public' AND r.relname = ANY($1::text[]) AND c.contype IN ('p', 'u', 'x', 'f')
ORDER BY c.contype = 'f', r.relname, c.conname
"""

#: 制約に属さない索引（空間索引等）。名前を保つため、定義を写して作る。
_INDEXES_SQL = """
SELECT r.relname AS table_name, pg_get_indexdef(x.indexrelid) AS definition
FROM pg_index x
JOIN pg_class r ON r.oid = x.indrelid
JOIN pg_namespace n ON n.oid = r.relnamespace
WHERE n.nspname = 'public' AND r.relname = ANY($1::text[])
  AND NOT EXISTS (SELECT 1 FROM pg_constraint c
                  WHERE c.conindid = x.indexrelid AND c.conrelid = x.indrelid)
ORDER BY r.relname
"""


async def _copy_to_work_schema(conn: asyncpg.Connection, tables: list[str]) -> None:
    """派生の表を今の中身ごと作業用のスキーマへ写し、接続がそちらを先に探すようにする。

    列・既定値・検査制約は`LIKE`で、鍵・外部キー・索引は`public`の定義から名前ごと写す——
    入れ替えた後の`public`の表は、入れ替える前と同じ名前の制約と索引を持つ。索引は行を
    入れてから作る（1行ずつ索引を伸ばすより速い）。
    """
    started = time.perf_counter()
    await conn.execute("SET search_path = public")
    constraints = await conn.fetch(_CONSTRAINTS_SQL, tables)
    indexes = await conn.fetch(_INDEXES_SQL, tables)
    await conn.execute(f"DROP SCHEMA IF EXISTS {_WORK_SCHEMA} CASCADE")
    await conn.execute(f"CREATE SCHEMA {_WORK_SCHEMA}")
    for table in tables:
        await conn.execute(
            f"CREATE TABLE {_WORK_SCHEMA}.{table} (LIKE public.{table} INCLUDING ALL EXCLUDING INDEXES)")
        await conn.execute(f"INSERT INTO {_WORK_SCHEMA}.{table} SELECT * FROM public.{table}")
    await conn.execute(f"SET search_path = {_WORK_SCHEMA}, public")
    for row in constraints:
        await conn.execute(f'ALTER TABLE {row["table_name"]} ADD CONSTRAINT {row["name"]} {row["definition"]}')
    for row in indexes:
        qualified = f" ON public.{row['table_name']} "
        if qualified not in row["definition"]:
            raise RuntimeError(f"索引の定義を読み替えられない: {row['definition']}")
        await conn.execute(row["definition"].replace(qualified, f" ON {_WORK_SCHEMA}.{row['table_name']} ", 1))
    await conn.execute("ANALYZE " + ", ".join(tables))
    logger.info("派生の表を作業用のスキーマ %s へ写した / %s",
                _WORK_SCHEMA, format_duration(time.perf_counter() - started))


async def _build_road_network(database_url: str, revision: int) -> Path:
    """作業用のスキーマの表から道路網の配列を作り、読み手がまだ拾わない名前で置く。"""
    started = time.perf_counter()
    async with batch_session_factory(database_url, schema=_WORK_SCHEMA) as session_factory:
        async with session_factory() as session:
            network = await road_network_store.build(RoadGraphRepository(session), revision)
    pending = road_network_store.write_pending(network)
    logger.info("道路網の配列を作った / %s", format_duration(time.perf_counter() - started))
    return pending


async def _swap(conn: asyncpg.Connection, tables: list[str], revision: int) -> None:
    """`public`の派生の表を作業用のスキーマの表で置き換え、世代を`revision`へ進める（1トランザクション）。"""
    for attempt in range(1, _SWAP_ATTEMPTS + 1):
        started = time.perf_counter()
        try:
            async with conn.transaction():
                await conn.execute(f"SET LOCAL lock_timeout = '{_SWAP_LOCK_TIMEOUT}'")
                await conn.execute("DROP TABLE " + ", ".join(f"public.{table}" for table in tables))
                for table in tables:
                    await conn.execute(f"ALTER TABLE {_WORK_SCHEMA}.{table} SET SCHEMA public")
                bumped = await derived_data_meta.bump_revision(conn)
                if bumped != revision:
                    raise RuntimeError(
                        f"派生データの世代が作り直しの間に動いた（道路網は {revision} で作った。今 {bumped}）")
            logger.info("派生の表を入れ替えた（%d回目） / 表の排他ロック（待ちを含む）=%.1fs",
                        attempt, time.perf_counter() - started)
            return
        except asyncpg.exceptions.LockNotAvailableError:
            logger.warning("入れ替えが表を読んでいる相手を待ちきれなかった。%.0f秒後にやり直す（%d/%d）",
                           _SWAP_RETRY_SECONDS, attempt, _SWAP_ATTEMPTS)
            await asyncio.sleep(_SWAP_RETRY_SECONDS)
    raise RuntimeError("入れ替えられなかった: 派生の表を読み続けている相手がいる")


async def _read_tuning(database_url: str) -> dict[str, float]:
    """DBの上書きを宣言の既定へ重ねた、いま効くべき較正値（webアプリが起動時に読むのと同じ値）。"""
    async with batch_session_factory(database_url) as session_factory:
        async with session_factory() as session:
            return await load_tuning_values(session)


async def run(database_url: str) -> int:
    # 作った取込・列・段の指紋の記録も写す——事故密度の分母が取込の記録から読まれ、写しから作る道路網の配列も数と
    # 同じ取込の年で割るため。どの記録も派生の表と一緒に入れ替わる。
    tables = [*(table.name for table in derived_tables()), derived_data_meta.DerivedSourceRunRow.__tablename__,
              derived_data_meta.DerivedColumnRow.__tablename__, derived_data_meta.DerivedStageRow.__tablename__]
    columns = declared_columns()
    tuning = await _read_tuning(database_url)
    conn = await asyncpg.connect(asyncpg_dsn(database_url))
    if not await conn.fetchval("SELECT pg_try_advisory_lock(hashtext($1))", SOURCE_DATA_LOCK):
        await conn.close()
        raise RuntimeError("別の派生の作り直しか取込が走っている")
    pending: Path | None = None
    started = time.perf_counter()
    try:
        runs = {row["source"]: row["run_id"] for row in await conn.fetch(LATEST_SUCCEEDED_RUNS_SQL)}
        database = await conn.fetchval("SELECT version() || ' / ' || postgis_full_version()")
        fingerprints = stage_fingerprints(runs, tuning, columns, database)
        recorded = await derived_data_meta.read_stage_fingerprints(conn)
        changed = [stage for stage in STAGES if recorded.get(stage.name) != fingerprints[stage.name]]
        if not changed:
            logger.info("どの段も入力が前回と同じなので、作り直さずに終える（派生の表・世代・道路網の配列は前のまま）")
            return 0
        await _copy_to_work_schema(conn, tables)
        await derived_data_meta.replace_source_runs(conn, runs)
        await derived_data_meta.replace_columns(conn, columns)
        await derived_data_meta.replace_stage_fingerprints(conn, fingerprints)
        for stage in STAGES:
            if stage not in changed:
                logger.info("段 %s を飛ばした（入力が前回と同じ）", stage.name)
                continue
            stage_started = time.perf_counter()
            logger.info("段 %s を開始（%d/%d）", stage.name, changed.index(stage) + 1, len(changed))
            reusable = stage.per_edge and recorded.get(_outside_key(stage)) == fingerprints[_outside_key(stage)]
            await stage.run(conn, tuning, "public" if reusable else None)
            logger.info("段 %s 完了 / %s", stage.name,
                        format_duration(time.perf_counter() - stage_started))
        revision = (await conn.fetchval("SELECT revision FROM derived_data_meta") or 0) + 1
        pending = await _build_road_network(database_url, revision)
        await _swap(conn, tables, revision)
        road_network_store.publish(pending)
        pending = None
    finally:
        if pending is not None:
            shutil.rmtree(pending, ignore_errors=True)
        try:
            await conn.execute(f"DROP SCHEMA IF EXISTS {_WORK_SCHEMA} CASCADE")
        except (asyncpg.PostgresError, OSError):
            logger.warning("作業用のスキーマ %s を消せなかった（次の作り直しの最初に消す）",
                           _WORK_SCHEMA, exc_info=True)
        await conn.close()
    logger.info("派生を作り直して入れ替えた: 流した段 %s / 派生データの世代 %d / %s",
                "→".join(stage.name for stage in changed), revision, format_duration(time.perf_counter() - started))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="生データから派生を作り直す（入力が前回と同じ段は流さない）")
    return run_batch_cli(parser, lambda args, database_url: run(database_url))


if __name__ == "__main__":
    raise SystemExit(main())
