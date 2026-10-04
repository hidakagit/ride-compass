"""派生データの世代と、数えた事故の取込（1行のみ、id=1固定）。今の派生の表を作った取込（`derived_source_runs`）。

派生の作り直し（`app/batch/derive_cli.py`）が作り直した表を入れ替えるたびにインクリメントする単調カウンタ。
道路網全体の配列の置き場の名前（`road_network_store.py`）と、配信する地図タイルの世代
（`tile_version_service.py`）が、中身が作り直されたかをこの値で見分ける。タイルは生データも
直接読むため、生データの世代と一緒に読む（`get_revisions`）。

**作り直しに使った取込の記録（`derived_source_runs`）では代用できない。** 同じ取込runのままバッチをもう一度
回す（バッチ側のバグ修正後の再実行、`derive_cli.py`の再実行）と値は変わりうるのに、
記録は変わらないためである。「中身を書き直した」という事実を
表せるのは書いた側が進めるカウンタだけである。

**この表も派生の表と一緒に作業用のスキーマへ写して入れ替える**（`derive_cli.py`）。
`accident_run_id`は事故の数の分母（収録年数）を決めるので、数と同じ時点で変わらないと、
取り込み直してから作り直しが入れ替わるまでの間、分母だけが新しい取込の年数になる。

行は最初に世代を進めたとき（`bump_revision`）か、数の段が数えた事故の取込を記録したとき
（`record_accident_run`）に作られる。行が無い間は`get_revisions()`の
派生の世代がNoneになる。
"""

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

    #: 連番にしない——表ごと入れ替えるので、写しの既定値が元の表の連番を指すと元の表を消せない。
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    #: 今の事故の数（`accident_count`）を数えた事故の取込。事故密度の分母はこのrunの宣言の年から読む。
    #: NULLは事故の取込が無いまま数えたこと（事故の数はどれも0）。
    accident_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("source_runs.run_id"), nullable=True)


class DerivedSourceRunRow(Base):
    """今の`public`の派生の表を作った取込。ソースごとに1行。

    作り直しを始めた時点の、全ソースの成功した最新の取込を、表を入れ替えるのと同じトランザクションで
    書く（`derive_cli.py`）。段がどのソースを読むかは宣言していないので、全ソースを記録する。段が読んだ
    生データがこの記録と一致するのは、取込と作り直しが同時に走らず、`--from`が記録から生データの
    変わっていないときだけ流れるためである。
    """

    __tablename__ = "derived_source_runs"

    source: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("source_runs.run_id"), nullable=False)


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


async def record_accident_run(conn: asyncpg.Connection, run_id: int | None) -> None:
    """数えた事故の取込を記録する。行が無ければ世代0（まだ一度も入れ替えていない）で作る。

    数の段が作業用のスキーマの写しへ書き、入れ替えで数と一緒に読み手へ出る。
    """
    await conn.execute(
        "INSERT INTO derived_data_meta (id, revision, accident_run_id) VALUES (1, 0, $1)"
        " ON CONFLICT (id) DO UPDATE SET accident_run_id = EXCLUDED.accident_run_id",
        run_id)


async def read_source_runs(conn: asyncpg.Connection) -> dict[str, int]:
    """今の派生の表を作った取込（ソース → `run_id`）。"""
    return {row["source"]: row["run_id"] for row in await conn.fetch(
        f"SELECT source, run_id FROM {DerivedSourceRunRow.__tablename__}")}


async def replace_source_runs(conn: asyncpg.Connection, runs: dict[str, int]) -> None:
    """今の派生の表を作った取込を`runs`へ置き換える。派生の表を入れ替えるトランザクションの中で呼ぶ
    （`bump_revision`と同じ理由）。"""
    await conn.execute(f"DELETE FROM {DerivedSourceRunRow.__tablename__}")
    await conn.executemany(
        f"INSERT INTO {DerivedSourceRunRow.__tablename__} (source, run_id) VALUES ($1, $2)", runs.items())
