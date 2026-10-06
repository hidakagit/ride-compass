"""較正値の上書きの読み書き（管理APIのサービス層）。

**トランザクション境界はここが持つ**（[design-principles.md](../../../docs/architecture/design-principles.md)
構造仕様7）。ルーターが`commit()`/`rollback()`を直接呼ぶと、1リクエストで2つ以上の書き込みを
まとめたくなったときに「どこまでが1つの取引か」を決める場所が無くなる——ルーター側で
書き足すたびに境界が動き、途中まで書けた状態が残りうる。

**プロセス内の`TUNING_VALUES`へ書くのはここだけ**（起動時の読み込みと、管理APIの書き込みの直後）。
DBへ書いただけでは次のリクエストが古い値を読むため、書き込みと反映を離さない（`axis_registry_service`が
軸定義で採っているのと同じ、同一プロセス内で完結させポーリングしない形）。
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.tuning import TUNING_PARAMETERS_BY_ID, TUNING_VALUES
from app.infrastructure.tuning_overrides import (
    clear_override,
    load_tuning_values,
    read_overrides,
    set_override,
)

logger = logging.getLogger("ridecompass.tuning")


def _apply_tuning_values(values: dict[str, float]) -> None:
    """`load_tuning_values`が作った値を、プロセス内の`TUNING_VALUES`へ反映する。

    **中身だけを差し替える**（辞書そのものを作り直すと、import済みの参照が古い辞書を
    指したままになる）。読み出しも検算も済んだ値を受け取るだけなので失敗しない。

    `clear()`を挟まない——探索は別スレッドから読むため、消してから足すまでの間に読むと
    宣言にあるidでも`KeyError`になる。`values`は宣言の全idを持つので、`update`だけで鍵が揃う。
    """
    TUNING_VALUES.update(values)
    changed = {k: v for k, v in values.items() if v != TUNING_PARAMETERS_BY_ID[k].default}
    if changed:
        logger.info("較正値の上書きを読み込みました count=%d ids=%s", len(changed), sorted(changed))


async def refresh_tuning_values(session: AsyncSession) -> None:
    """DBの上書きを読み、プロセス内の`TUNING_VALUES`へ反映する（起動時の読み込み）。"""
    _apply_tuning_values(await load_tuning_values(session))


async def overridden_parameter_ids(session: AsyncSession) -> set[str]:
    """既定から動かしてある較正値のid。"""
    return set(await read_overrides(session))


async def save_override(session: AsyncSession, param_id: str, value: float | None) -> set[str]:
    """1件を上書きし（`value`が`None`なら既定へ戻す）、書いた後に既定から動かしてある較正値のidを返す。

    値の検算は`infrastructure`側（宣言の範囲・数値であること）が行い、ここは**取引の
    区切りと、書いた値をプロセスへ反映するところまで**を持つ。失敗したら書き込みごと
    巻き戻す——半分だけ書けた状態で反映すると、DBと動いている値が食い違う。

    反映する値は**確定の前に**作り、確定の後は差し替えだけにする（理由は
    docs/modules/backend/routing-engine.md「較正値」）。
    """
    try:
        if value is None:
            await clear_override(session, param_id)
        else:
            await set_override(session, param_id, value)
        values = await load_tuning_values(session)
        overridden = set(await read_overrides(session))
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    _apply_tuning_values(values)
    return overridden
