"""派生データの世代（1行のみ、id=1固定）。

派生の作り直し（`app/batch/derive_cli.py`）が作り直した表を入れ替えるたびにインクリメントする単調カウンタ。
道路網全体の配列の置き場の名前（`road_network_store.py`）と、配信する地図タイルの世代
（`tile_version_service.py`）が、中身が作り直されたかをこの値で見分ける。

**系譜（派生表の`source_run_id`）では代用できない。** 同じ取込runのままバッチをもう一度
回す（バッチ側のバグ修正後の再実行、`derive_cli.py`の再実行）と値は変わりうるのに、
系譜は変わらないためである。「中身を書き直した」という事実を
表せるのは書いた側が進めるカウンタだけである。

行は最初に世代を進めたときに作られる（`bump_revision`）。それまでは`get_revision()`が
Noneを返す。
"""

import asyncpg
from sqlalchemy import Integer, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.orm_base import Base


class DerivedDataMetaRow(Base):
    __tablename__ = "derived_data_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)


async def get_revision(session: AsyncSession) -> int | None:
    return await session.scalar(select(DerivedDataMetaRow.revision).where(DerivedDataMetaRow.id == 1))


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
