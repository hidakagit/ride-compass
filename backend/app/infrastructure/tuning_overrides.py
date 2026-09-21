"""較正値の上書き（`app/domain/tuning.py`の宣言から動かしたぶんだけを持つ）。

既定値は宣言が持つ。このテーブルは差分だけを持つため、**行が1つも無くても宣言どおりに
動く**——`axis_definitions`のような「行そのものが定義」の形と違い、fresh bootstrap
（CI・新規環境・disaster recovery）でスナップショットの投入が要らない。

読み込みは**プロセス内の`TUNING_VALUES`を中身ごと差し替える**（`.clear()`+`.update()`。
束縛済みの参照先が古いままにならないようにする流儀は`services/axis_registry_service.py`が
`AXIS_DEFINITIONS`へ採っているのと同じ）。更新のタイミングもそちらと同じく、アプリ起動時と
管理APIの書き込み直後の2つだけで、ポーリングはしない（単一プロセス前提）。

**壊れた行の扱いは2通りに分ける。**

- 宣言から消えたidの行は**警告して無視する**。パラメータを1つ減らしただけで本番の起動が
  失敗するのは割に合わない（行は残るが何もしない）。
- 値が宣言の範囲の外・数値でない行は**落とす**。間違った値が静かに効く方が悪い。
"""

import logging
import math
from datetime import datetime

from sqlalchemy import DateTime, Float, String, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.tuning import TUNING_PARAMETERS, TUNING_PARAMETERS_BY_ID, TUNING_VALUES
from app.infrastructure.orm_base import Base

logger = logging.getLogger("ridecompass.tuning")

#: PostgreSQLの「その表は無い」（undefined_table）。`read_overrides`が受け止める唯一の失敗。
_UNDEFINED_TABLE = "42P01"


class TuningOverrideError(RuntimeError):
    """上書きの行が読めない（範囲の外・数値でない）。"""


class TuningOverrideRow(Base):
    __tablename__ = "tuning_overrides"

    param_id: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    #: いつこの値へ動かしたか。書き込み側は値を渡さずDB側の既定（`now()`）に任せる
    #: ——アプリのプロセスの時計ではなくDBの時計で揃える。
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())


def merge_overrides(overrides: dict[str, float]) -> dict[str, float]:
    """宣言の既定値へ上書きを重ねた、いま効くべき値。

    宣言に無いidは警告して捨てる。範囲の外・数値でない値は`TuningOverrideError`。
    """
    merged = {p.id: p.default for p in TUNING_PARAMETERS}
    for param_id, value in sorted(overrides.items()):
        parameter = TUNING_PARAMETERS_BY_ID.get(param_id)
        if parameter is None:
            logger.warning(
                "較正値の上書きに、宣言に無いidの行があります（無視します） param_id=%s", param_id
            )
            continue
        if not math.isfinite(value):
            raise TuningOverrideError(f"較正値の上書きが数値でない: {param_id}={value!r}")
        if not parameter.minimum <= value <= parameter.maximum:
            raise TuningOverrideError(
                f"較正値の上書きが宣言の範囲の外: {param_id}={value} "
                f"（{parameter.minimum}〜{parameter.maximum}）"
            )
        merged[param_id] = value
    return merged


async def read_overrides(session: AsyncSession) -> dict[str, float]:
    """テーブルの中身（id → 値）。行が無ければ空。

    **テーブルそのものが無い環境も「上書きが1件も無い」として扱う**。既定値の唯一の正本は
    宣言の側で、このテーブルは差分を持つだけのため、無い状態と空の状態は同じ意味になる。
    上書きを**書く**側は同じようには倒れない（テーブルが無ければ書き込みがそのまま失敗する）。

    **受け止めるのは「表が無い」だけ**（SQLSTATE 42P01）。列が足りない・型が合わない等も
    まとめて飲み込むと、**表はあるのに上書きが全件無視されて既定値へ戻る**——利用者からは
    較正した覚えの無い挙動に見え、ログを読むまで気づけない。
    """
    try:
        rows = (await session.execute(select(TuningOverrideRow))).scalars().all()
    except ProgrammingError as error:
        if getattr(getattr(error, "orig", None), "sqlstate", None) != _UNDEFINED_TABLE:
            raise
        await session.rollback()
        logger.warning("較正値の上書きのテーブルがありません（宣言の既定値で動きます）")
        return {}
    return {row.param_id: float(row.value) for row in rows}


async def refresh_tuning_values(session: AsyncSession) -> None:
    """DBの上書きを読み、プロセス内の`TUNING_VALUES`へ反映する。

    **中身だけを差し替える**（辞書そのものを作り直すと、import済みの参照が古い辞書を
    指したままになる）。
    """
    merged = merge_overrides(await read_overrides(session))
    TUNING_VALUES.clear()
    TUNING_VALUES.update(merged)
    changed = {k: v for k, v in merged.items() if v != TUNING_PARAMETERS_BY_ID[k].default}
    if changed:
        logger.info("較正値の上書きを読み込みました count=%d ids=%s", len(changed), sorted(changed))


async def set_override(session: AsyncSession, param_id: str, value: float) -> None:
    """1件を上書きする（既定値と同じなら行を消す——差分だけを持つ形を保つ）。

    範囲の検算は`merge_overrides`と同じ規則で、書く前に行う。**宣言に無いidは書く側では
    エラーにする**——読む側が警告で済ませるのは「宣言から消えた値の行が残っている」場合
    だけで、これから書く値が宣言に無いのは綴り間違いである。
    """
    if param_id not in TUNING_PARAMETERS_BY_ID:
        raise TuningOverrideError(f"較正値の宣言に無いid: {param_id}")
    merge_overrides({param_id: value})
    if value == TUNING_PARAMETERS_BY_ID[param_id].default:
        await clear_override(session, param_id)
        return
    await session.execute(
        pg_insert(TuningOverrideRow)
        .values(param_id=param_id, value=value)
        .on_conflict_do_update(index_elements=["param_id"], set_={"value": value})
    )


async def clear_override(session: AsyncSession, param_id: str) -> None:
    """1件の上書きを外す（既定値へ戻す）。"""
    await session.execute(delete(TuningOverrideRow).where(TuningOverrideRow.param_id == param_id))
