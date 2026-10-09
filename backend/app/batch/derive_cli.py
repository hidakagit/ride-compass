"""派生を作り直す入口。**順番はここだけが持つ**。

生データを差し替えたら、下流を全部作り直す。段は次の依存で決まっており、飛ばせない:
形（`road_edges`）が無いと材料の行が作れず、ノードの枝数が無いと交差点を数えられず、
区間の値が無いと道の値を導けない。

    .venv\\Scripts\\python.exe -m app.batch.derive_cli
    .venv\\Scripts\\python.exe -m app.batch.derive_cli --from counts

途中から流し直すのは、ある段のやり方だけを変えたとき（分類器を直した・しきい値を
変えた）。`--from`はその段から後ろを全部流す。生データを取り直したとき・派生の表の列を足した・消したときは
最初から通す——`--from`は、全ソースの成功した最新の取込と派生の表の宣言の列が前の作り直しの記録
（`derived_source_runs`・`derived_columns`）と同じときだけ流し、違えば止まる（流すと、前の段が古い取込から
作った値や、前の段が書く足した列のNULLが残る）。
作り直しは取込と同時に走らない（`common.py: SOURCE_DATA_LOCK`）。

後ろの段がみな直前の段の値を読むわけではない。面を線へ落とす段（`raster`）はノードの値も
数の値も読まず、数の段が作る道1本の行へ書き込むためにその後ろにある。そのため`--from`は、
変えた段の値を読まない段まで流し直すことがある。段は単独の入口を持たない——どの段がどの段の
値を読むかは宣言されておらず、1段だけ流してそれを読む段を流し忘れると、古い入力から作った
値が残る。

**作り直しは作業用のスキーマで行い、道路網の配列まで作ってから1つのトランザクションで`public`の
表と入れ替える**（仕組みと理由は`docs/modules/backend/static-road-attributes.md`「派生」）。
段のSQLは表の名前をスキーマを付けずに書く——接続の`search_path`が作業用のスキーマを先に探し、
生データは`public`から読む。

**段が読む較正値は、作り直しを始めるときに1度だけDBの上書きから読み、段の関数へ値で渡す**。
バッチはwebアプリと別のプロセスで、プロセス内の較正値（`domain/tuning.py: TUNING_VALUES`）へは
何も読み込まれていない——そこを読むと、管理画面で変えた値ではなく宣言の既定が効く。
どの段がどの較正値を読むかは`STAGES`が持つ。
"""

import argparse
import asyncio
import logging
import shutil
import sys
import time
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncpg  # noqa: E402

from app.batch import (  # noqa: E402
    derive_addresses,
    derive_counts,
    derive_node_materials,
    derive_raster_materials,
    derive_stop_places,
    derive_topology,
    derive_way_materials,
)
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
from app.infrastructure.source_models import LATEST_SUCCEEDED_RUNS_SQL  # noqa: E402

logger = logging.getLogger("ridecompass.derive_cli")

#: 段は接続と、いま効くべき較正値（id → 値）を受ける。
Stage = Callable[[asyncpg.Connection, Mapping[str, float]], Awaitable[object]]

#: 本番の読み手はこのファイルだけだが、テストが段の後ろに覗き窓・失敗を挟むために公開する（testing.md「確かめる高さ」の
#: 例外）: 入れ替えまでは読み手が前の表を読むこと・途中で落ちても読み手の見るものが何も変わらないことは、段と段の
#: 間に入らないと作れず、入口（`run`）の引数で段を受けると、本番がいつも同じ表を渡すだけのテストのための口になる。
STAGES: tuple[tuple[str, Stage], ...] = (
    ("topology", lambda conn, tuning: derive_topology.derive(conn)),
    ("nodes", lambda conn, tuning: derive_node_materials.derive(
        conn, signal_radius_m=tuning["signal.match_radius_m"])),
    ("counts", lambda conn, tuning: derive_counts.derive(conn)),
    ("raster", lambda conn, tuning: derive_raster_materials.derive(conn)),
    ("ways", lambda conn, tuning: derive_way_materials.derive(conn)),
    # 住所の区画は、施設の辺り（立ち寄り先の段）を区画から決められるよう、その前に置く。
    ("addresses", lambda conn, tuning: derive_addresses.derive(conn)),
    ("stop_places", lambda conn, tuning: derive_stop_places.derive(conn)),
)

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


async def run(database_url: str, start_from: str | None) -> int:
    names = [name for name, _ in STAGES]
    begin = names.index(start_from) if start_from else 0
    # 作った取込と列の記録も写す——事故密度の分母が取込の記録から読まれ、写しから作る道路網の配列も数と同じ取込の年で
    # 割るため。どちらの記録も派生の表と一緒に入れ替わる。
    tables = [*(table.name for table in derived_tables()), derived_data_meta.DerivedSourceRunRow.__tablename__,
              derived_data_meta.DerivedColumnRow.__tablename__]
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
        if start_from and (runs != await derived_data_meta.read_source_runs(conn)
                           or columns != await derived_data_meta.read_columns(conn)):
            raise RuntimeError("生データか派生の表の列が前の作り直しから変わっている。--from を外して最初から流す")
        await _copy_to_work_schema(conn, tables)
        await derived_data_meta.replace_source_runs(conn, runs)
        await derived_data_meta.replace_columns(conn, columns)
        for index, (name, stage) in enumerate(STAGES[begin:], start=1):
            stage_started = time.perf_counter()
            logger.info("段 %s を開始（%d/%d）", name, index, len(STAGES) - begin)
            await stage(conn, tuning)
            logger.info("段 %s 完了 / %s", name,
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
    logger.info("派生を作り直して入れ替えた: %s / 派生データの世代 %d / %s",
                "→".join(names[begin:]), revision, format_duration(time.perf_counter() - started))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="生データから派生を作り直す")
    parser.add_argument("--from", dest="start_from", default=None,
                        choices=[name for name, _ in STAGES])
    return run_batch_cli(parser, lambda args, database_url: run(database_url, args.start_from))


if __name__ == "__main__":
    raise SystemExit(main())
