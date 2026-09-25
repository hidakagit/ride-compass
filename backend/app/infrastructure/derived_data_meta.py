"""派生データの世代（1行のみ、id=1固定）。

`app/batch/`のバッチが派生データを書き直すたびにインクリメントする単調カウンタ。
道路網全体の配列の置き場の名前（`road_network_store.py`）と、配信する地図タイルの世代
（`tile_version_service.py`）が、中身が作り直されたかをこの値で見分ける。

**系譜（派生表の`source_run_id`）では代用できない。** 同じ取込runのままバッチをもう一度
回す（バッチ側のバグ修正後の再実行、`derive_cli.py`の再実行）と値は変わりうるのに、
系譜は変わらないためである。「中身を書き直した」という事実を
表せるのは書いた側が進めるカウンタだけである。

行はバッチが最初に世代を進めたときに作られる（`bump_revision`）。それまでは`get_revision()`が
Noneを返す。
"""

from sqlalchemy import Integer, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.orm_base import Base


class DerivedDataMetaRow(Base):
    __tablename__ = "derived_data_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)


async def get_revision(session: AsyncSession) -> int | None:
    return await session.scalar(select(DerivedDataMetaRow.revision).where(DerivedDataMetaRow.id == 1))


async def bump_revision(session: AsyncSession) -> int:
    """世代を1つ進めて新しい値を返す。行が無ければ作って1にする。

    派生データを書き換えたバッチが、書き込みをコミットしたあとに呼ぶ。読み手はこの値の
    変化だけを見るため、いくつ進んだかには意味が無い（同じバッチを2回回して2つ進んでも、
    キャッシュが1回余分に作り直されるだけで害は無い）。

    **行を作るのはここだけ**——スキーマはORMの宣言から作るため、行を入れる場所が他に無い。
    行が無いまま進めずにいると、バッチが派生を作り直しても世代が変わらず、読み手は
    作り直されたことに気づけない。
    """
    statement = pg_insert(DerivedDataMetaRow).values(id=1, revision=1)
    result = await session.execute(
        statement.on_conflict_do_update(
            index_elements=[DerivedDataMetaRow.id],
            set_={"revision": DerivedDataMetaRow.revision + 1},
        ).returning(DerivedDataMetaRow.revision)
    )
    revision: int = result.scalar_one()
    await session.commit()
    return revision
