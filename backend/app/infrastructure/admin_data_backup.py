"""取り直せない管理データの表（`info`に`orm_base.IRREPLACEABLE`の印を持つ表）の書き出しと戻し。

母集団は印から導く。印の付いた表を1つ足せば、書き出しにも戻しにも入る。

行は列名→値の辞書で、日時はISO 8601の文字列にする（JSONへそのまま書けるように）。戻すときは
ORMの列の型を見て日時へ戻す。**書き込みはcommitしない**——呼び出し側がアプリの読み込みで
検算してから確定する（`scripts/admin_data_backup.py`）。
"""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Table, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.orm_base import IRREPLACEABLE_KEY, declared_metadata

logger = logging.getLogger("ridecompass.admin_data_backup")


class AdminDataRestoreError(RuntimeError):
    """戻す内容が宣言と合わない、または戻し先に行が残っている。"""


def irreplaceable_tables() -> list[Table]:
    """印の付いた表（外部キーの依存順）。"""
    return [table for table in declared_metadata().sorted_tables if table.info.get(IRREPLACEABLE_KEY)]


def _to_json(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


async def dump_tables(session: AsyncSession) -> dict[str, list[dict[str, Any]]]:
    """印の付いた表の全行。行は主キーの順に並べる（同じ中身なら同じ出力になるように）。"""
    dumped: dict[str, list[dict[str, Any]]] = {}
    for table in irreplaceable_tables():
        rows = (await session.execute(select(table).order_by(*table.primary_key.columns))).mappings().all()
        dumped[table.name] = [{key: _to_json(value) for key, value in row.items()} for row in rows]
    return dumped


def _from_json(table: Table, row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: datetime.fromisoformat(value)
        if isinstance(table.c[key].type, DateTime) and isinstance(value, str) else value
        for key, value in row.items()
    }


async def restore_tables(
    session: AsyncSession, tables: dict[str, list[dict[str, Any]]], *, replace: bool
) -> dict[str, int]:
    """`dump_tables`の出力を戻し、表ごとの行数を返す。

    **戻し先に行があれば、`replace`を指定しない限り何も書かずに止める**——まっさらなDBへ戻すのが
    既定で、残っている行と混ぜると、どちらの行が効いているのか分からない状態ができる。
    `replace`は同じトランザクションの中で消してから入れる。

    バックアップに無い表（書き出した後で印を付けた表）は空のまま進む。宣言に無い表・列は止める
    ——捨てると、戻したつもりの値が黙って欠ける。
    """
    declared = irreplaceable_tables()
    unknown_tables = sorted(set(tables) - {table.name for table in declared})
    if unknown_tables:
        raise AdminDataRestoreError(f"宣言に無い表がバックアップにあります: {unknown_tables}")
    for table in declared:
        unknown_columns = sorted({key for row in tables.get(table.name, []) for key in row} - set(table.c.keys()))
        if unknown_columns:
            raise AdminDataRestoreError(f"{table.name}の宣言に無い列がバックアップにあります: {unknown_columns}")

    existing = {
        table.name: (await session.execute(select(func.count()).select_from(table))).scalar_one()
        for table in declared
    }
    occupied = {name: count for name, count in existing.items() if count}
    if occupied and not replace:
        raise AdminDataRestoreError(f"戻し先に行があります（入れ替えるなら --replace）: {occupied}")
    if replace:
        for table in reversed(declared):
            await session.execute(table.delete())

    counts: dict[str, int] = {}
    for table in declared:
        rows = tables.get(table.name)
        if rows is None:
            logger.warning("バックアップにこの表がありません（空のまま進みます） table=%s", table.name)
            rows = []
        if rows:
            await session.execute(insert(table), [_from_json(table, row) for row in rows])
        counts[table.name] = len(rows)
    return counts
