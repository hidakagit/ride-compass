"""較正値の上書きの読み書き（管理APIのサービス層）。

**トランザクション境界はここが持つ**（[design-principles.md](../../../docs/design-principles.md)
構造仕様7）。ルーターが`commit()`/`rollback()`を直接呼ぶと、1リクエストで2つ以上の書き込みを
まとめたくなったときに「どこまでが1つの取引か」を決める場所が無くなる——ルーター側で
書き足すたびに境界が動き、途中まで書けた状態が残りうる。

書き込みの直後にプロセス内の`TUNING_VALUES`まで反映するのもここ。DBへ書いただけでは
次のリクエストが古い値を読むため、書き込みと反映を離さない（`axis_registry_service`が
軸定義で採っているのと同じ、同一プロセス内で完結させポーリングしない形）。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.tuning_overrides import (
    clear_override,
    read_overrides,
    refresh_tuning_values,
    set_override,
)


async def overridden_parameter_ids(session: AsyncSession) -> set[str]:
    """既定から動かしてある較正値のid。"""
    return set(await read_overrides(session))


async def save_override(session: AsyncSession, param_id: str, value: float | None) -> None:
    """1件を上書きする（`value`が`None`なら既定へ戻す）。

    値の検算は`infrastructure`側（宣言の範囲・数値であること）が行い、ここは**取引の
    区切りと、書いた値をプロセスへ反映するところまで**を持つ。失敗したら書き込みごと
    巻き戻す——半分だけ書けた状態で反映すると、DBと動いている値が食い違う。
    """
    try:
        if value is None:
            await clear_override(session, param_id)
        else:
            await set_override(session, param_id, value)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    await refresh_tuning_values(session)
