"""派生データの世代（1行のみ、id=1固定）と、今の派生の表を作った取込（`derived_source_runs`）・列（`derived_columns`）。

派生の作り直し（`app/batch/derive_cli.py`）が作り直した表を入れ替えるたびにインクリメントする単調カウンタ。
道路網全体の配列の置き場の名前（`road_network_store.py`）と、配信する地図タイルの世代
（`tile_version_service.py`）が、中身が作り直されたかをこの値で見分ける。タイルは生データも
直接読むため、生データの世代と一緒に読む（`get_revisions`）。

**作り直しに使った取込の記録（`derived_source_runs`）では代用できない。** 同じ取込runのままバッチをもう一度
回す（バッチ側のバグ修正後の再実行、`derive_cli.py`の再実行）と値は変わりうるのに、
記録は変わらないためである。「中身を書き直した」という事実を
表せるのは書いた側が進めるカウンタだけである。

行は最初に世代を進めたとき（`bump_revision`）に作られる。行が無い間は`get_revisions()`の
派生の世代がNoneになる。
"""

from collections.abc import Mapping
from dataclasses import dataclass

import asyncpg
from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Integer, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.orm_base import Base
from app.infrastructure.source_models import succeeded_run_count


class DerivedDataMetaRow(Base):
    __tablename__ = "derived_data_meta"
    __table_args__ = (CheckConstraint("id = 1", name="derived_data_meta_single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)


class DerivedSourceRunRow(Base):
    """今の`public`の派生の表を作った取込。ソースごとに1行。

    作り直しを始めた時点の、全ソースの成功した最新の取込を書く（鮮度台帳がソースごとに比べる）。派生の表と一緒に
    作業用のスキーマへ写して書き、表ごと入れ替える（`derive_cli.py`）——
    事故密度の分母がこの記録の事故の取込の年から読まれる（`road_graph_repository.py: get_accident_years`）ので、
    入れ替えの前に作業用のスキーマから作る道路網の配列も、入れ替えの後の読み手も、数と同じ取込の年を読む。段が読んだ
    生データがこの記録と一致するのは、取込と作り直しが同時に走らず、流さなかった段は読むソースの取込が前回と
    同じとき（段の指紋が同じとき）だけ飛ばされるためである。
    """

    __tablename__ = "derived_source_runs"

    source: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("source_runs.run_id"), nullable=False)


class DerivedColumnRow(Base):
    """今の`public`の派生の表を作ったときの、表ごとの列（ORMの宣言）。表と列ごとに1行。

    作り直しは作業用のスキーマで表ごと入れ替え、流さない段は入力（書く表の列を含む）が前回と同じ段だけなので、入れ替えた
    後の値のNULLは「計算した結果、値が無い」しかない。作り直しが要るのは、取込が変わったとき（`derived_source_runs`）と、最後の作り直しの後に
    派生の表の列を足した・消したとき（足した列は全行がNULLのまま）だけで、後者をこの記録と今の宣言の比べで出す
    （`derived_data_freshness.py`）。`derived_source_runs`と同じく作業用のスキーマへ写して書き、表ごと入れ替える。
    """

    __tablename__ = "derived_columns"

    table_name: Mapped[str] = mapped_column(String, primary_key=True)
    column_name: Mapped[str] = mapped_column(String, primary_key=True)


class DerivedStageRow(Base):
    """今の`public`の派生の表を作ったときの、段ごとの入力の指紋（`derive_cli.py: stage_fingerprints`）。段ごとに1行。

    次の作り直しは、指紋がこの記録と同じ段を流さず、写した前回の値を使う。読むのは作り直しだけ。
    `derived_source_runs`と同じく作業用のスキーマへ写して書き、表ごと入れ替える——段を流した作り直しが途中で
    落ちても、記録は前回の表の中身を指したまま残る。
    """

    __tablename__ = "derived_stages"

    stage: Mapped[str] = mapped_column(String, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String, nullable=False)


@dataclass(frozen=True)
class DataRevisions:
    """派生データの世代と生データの世代。"""

    #: 派生データの世代。行がまだ無ければNone。
    derived: int | None
    #: 生データの世代（`source_models.py: succeeded_run_count`）。取込だけを流したときは
    #: 派生の世代が動かないため、別に持つ。
    imported: int


async def get_revisions(session: AsyncSession) -> DataRevisions:
    """派生データの世代と生データの世代を1回の問い合わせで読む。"""
    derived = select(DerivedDataMetaRow.revision).scalar_subquery()
    row = (await session.execute(select(derived, succeeded_run_count()))).one()
    return DataRevisions(derived=row[0], imported=row[1])


async def bump_revision(conn: asyncpg.Connection) -> int:
    """世代を1つ進めて新しい値を返す。行が無ければ作って1にする。

    派生の表を入れ替えるトランザクションの中で呼ぶ——入れ替えと世代が別々にコミットされると、
    その間の読み手は新しい表を古い世代の鍵でキャッシュする。
    """
    revision: int = await conn.fetchval(
        "INSERT INTO derived_data_meta (id, revision) VALUES (1, 1)"
        " ON CONFLICT (id) DO UPDATE SET revision = derived_data_meta.revision + 1"
        " RETURNING revision")
    return revision


async def read_source_runs(conn: asyncpg.Connection) -> dict[str, int]:
    """今の派生の表を作った取込（ソース → `run_id`）。"""
    return {row["source"]: row["run_id"] for row in await conn.fetch(
        f"SELECT source, run_id FROM {DerivedSourceRunRow.__tablename__}")}


async def replace_source_runs(conn: asyncpg.Connection, runs: dict[str, int]) -> None:
    """派生の表を作った取込を`runs`へ置き換える。"""
    await conn.execute(f"DELETE FROM {DerivedSourceRunRow.__tablename__}")
    await conn.executemany(
        f"INSERT INTO {DerivedSourceRunRow.__tablename__} (source, run_id) VALUES ($1, $2)", runs.items())


async def read_columns(conn: asyncpg.Connection) -> dict[str, frozenset[str]]:
    """今の派生の表を作ったときの列（表の名前 → 列の名前）。"""
    columns: dict[str, set[str]] = {}
    for row in await conn.fetch(f"SELECT table_name, column_name FROM {DerivedColumnRow.__tablename__}"):
        columns.setdefault(row["table_name"], set()).add(row["column_name"])
    return {table: frozenset(names) for table, names in columns.items()}


async def replace_columns(conn: asyncpg.Connection, columns: Mapping[str, frozenset[str]]) -> None:
    """派生の表を作ったときの列を`columns`へ置き換える。"""
    await conn.execute(f"DELETE FROM {DerivedColumnRow.__tablename__}")
    await conn.executemany(
        f"INSERT INTO {DerivedColumnRow.__tablename__} (table_name, column_name) VALUES ($1, $2)",
        [(table, name) for table, names in columns.items() for name in sorted(names)])


async def read_stage_fingerprints(conn: asyncpg.Connection) -> dict[str, str]:
    """今の派生の表を作ったときの段ごとの指紋（段の名前 → 指紋）。"""
    return {row["stage"]: row["fingerprint"] for row in await conn.fetch(
        f"SELECT stage, fingerprint FROM {DerivedStageRow.__tablename__}")}


async def replace_stage_fingerprints(conn: asyncpg.Connection, fingerprints: Mapping[str, str]) -> None:
    """段ごとの指紋を`fingerprints`へ置き換える。"""
    await conn.execute(f"DELETE FROM {DerivedStageRow.__tablename__}")
    await conn.executemany(
        f"INSERT INTO {DerivedStageRow.__tablename__} (stage, fingerprint) VALUES ($1, $2)", fingerprints.items())
