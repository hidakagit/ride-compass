"""派生データの世代（1行のみ、id=1固定）。

派生の作り直し（`app/batch/derive_cli.py`）が作り直した表を入れ替えるたびにインクリメントする単調カウンタ。
道路網全体の配列の置き場の名前（`road_network_store.py`）と、配信する地図タイルの世代
（`tile_version_service.py`）が、中身が作り直されたかをこの値で見分ける。タイルは生データも
直接読むため、生データの世代と一緒に読む（`get_revisions`）。

**系譜（派生表の`source_run_id`）では代用できない。** 同じ取込runのままバッチをもう一度
回す（バッチ側のバグ修正後の再実行、`derive_cli.py`の再実行）と値は変わりうるのに、
系譜は変わらないためである。「中身を書き直した」という事実を
表せるのは書いた側が進めるカウンタだけである。

行は最初に世代を進めたときに作られる（`bump_revision`）。それまでは`get_revisions()`の
派生の世代がNoneになる。
"""

from dataclasses import dataclass

import asyncpg
from sqlalchemy import Integer, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.orm_base import Base
from app.infrastructure.source_models import succeeded_run_count


class DerivedDataMetaRow(Base):
    __tablename__ = "derived_data_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)


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
    derived = select(DerivedDataMetaRow.revision).where(DerivedDataMetaRow.id == 1).scalar_subquery()
    row = (await session.execute(select(derived, succeeded_run_count()))).one()
    return DataRevisions(derived=row[0], imported=row[1])


async def bump_revision(conn: asyncpg.Connection) -> int:
    """世代を1つ進めて新しい値を返す。行が無ければ作って1にする。

    派生の表を入れ替えるトランザクションの中で呼ぶ——入れ替えと世代が別々にコミットされると、
    その間の読み手は新しい表を古い世代の鍵でキャッシュする。

    **行を作るのはここだけ**——スキーマはORMの宣言から作るため、行を入れる場所が他に無い。
    """
    revision: int = await conn.fetchval(
        "INSERT INTO derived_data_meta (id, revision) VALUES (1, 1)"
        " ON CONFLICT (id) DO UPDATE SET revision = derived_data_meta.revision + 1"
        " RETURNING revision")
    return revision
