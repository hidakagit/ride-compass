"""派生データの世代（1行のみ、id=1固定）。

`app/batch/`のバッチが派生データを書き直すたびにインクリメントする単調カウンタ。
材料キャッシュ（`graph_material_cache.py`）が「ディスクへ書いた時点から中身が
作り直されたか」を判定するのに使う。

**系譜（`source_*_import_run_id`・`algorithm_version`）では代用できない。** 同じ取込run・
同じ版数のままバッチをもう一度回す（バッチ側のバグ修正後の再実行、`refresh_derived.py`の
再実行）と値は変わりうるのに、系譜は変わらないためである。「中身を書き直した」という事実を
表せるのは書いた側が進めるカウンタだけである。

行が無い環境（`Base.metadata.create_all`のみのテストDB等）では`get_revision()`がNoneを
返し、呼び出し側は安全側（キャッシュを消す）へ倒れる。
"""

from sqlalchemy import Integer, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.orm_base import Base


class DerivedDataMetaRow(Base):
    __tablename__ = "derived_data_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)


async def get_revision(session: AsyncSession) -> int | None:
    return await session.scalar(select(DerivedDataMetaRow.revision).where(DerivedDataMetaRow.id == 1))


async def bump_revision(session: AsyncSession) -> int | None:
    """世代を1つ進めて新しい値を返す（行が無ければ何もせずNone）。

    派生データを書き換えたバッチが、書き込みをコミットしたあとに呼ぶ。読み手はこの値の
    変化だけを見るため、いくつ進んだかには意味が無い（同じバッチを2回回して2つ進んでも、
    キャッシュが1回余分に作り直されるだけで害は無い）。
    """
    revision = await session.scalar(
        update(DerivedDataMetaRow)
        .where(DerivedDataMetaRow.id == 1)
        .values(revision=DerivedDataMetaRow.revision + 1)
        .returning(DerivedDataMetaRow.revision)
    )
    await session.commit()
    return revision
