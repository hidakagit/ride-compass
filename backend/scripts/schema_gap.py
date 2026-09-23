"""実DBのスキーマと、ORMが宣言する形のGAPを出す。

**正本は実DBで、ORMの宣言は「あるべき姿」である。**一致は誰も保証していないので測る。

比べるのは表・列・NULL許容・外部キー。列名だけでは足りない——ずれるのは制約の側でもある。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\schema_gap.py                    # settings.database_url
    .venv\\Scripts\\python.exe scripts\\schema_gap.py --database-url ...
    .venv\\Scripts\\python.exe scripts\\run_probe.py scripts\\schema_gap.py   # 本番（読み取りのみ）

GAPが1件でもあれば終了コード1。
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

# Base.metadataへ全モデルを登録するためのimport（副作用が目的）。
from app.infrastructure import axis_definition_models  # noqa: F401,E402
from app.infrastructure import derived_data_meta  # noqa: F401,E402
from app.infrastructure import derived_models  # noqa: F401,E402
from app.infrastructure import source_models  # noqa: F401,E402
from app.infrastructure import tuning_overrides  # noqa: F401,E402
from app.infrastructure.orm_base import Base  # noqa: E402

#: PostGISが持ち込む表。アプリのスキーマではないので母集団から外す。
_NOT_OURS = frozenset({"spatial_ref_sys"})

_TABLES = """
SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
"""
_COLUMNS = """
SELECT table_name, column_name, is_nullable
FROM information_schema.columns WHERE table_schema = 'public'
"""
_FKS = """
SELECT conrelid::regclass::text AS tbl, pg_get_constraintdef(oid) AS cdef
FROM pg_constraint WHERE contype = 'f' AND connamespace = 'public'::regnamespace
"""


def _orm_fk_signatures(table) -> set[str]:
    """ORMが宣言する外部キーを、実DB側と突き合わせられる形（列→参照先.列）にする。"""
    return {
        f"{fk.parent.name}->{fk.column.table.name}.{fk.column.name}"
        for fk in table.foreign_keys
    }


def _db_fk_signatures(defs: list[str]) -> set[str]:
    """`FOREIGN KEY (a) REFERENCES t(b) ...` を同じ形へ直す。"""
    out: set[str] = set()
    for d in defs:
        try:
            cols = d.split("(", 1)[1].split(")", 1)[0]
            ref = d.split("REFERENCES", 1)[1].strip()
            ref_table = ref.split("(", 1)[0].strip()
            ref_cols = ref.split("(", 1)[1].split(")", 1)[0]
        except IndexError:
            continue
        for col, rcol in zip(cols.split(","), ref_cols.split(",")):
            out.add(f"{col.strip()}->{ref_table}.{rcol.strip()}")
    return out


async def _collect(url: str) -> list[str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            db_tables = {r[0] for r in (await conn.execute(text(_TABLES))).all()} - _NOT_OURS
            db_cols: dict[str, dict[str, bool]] = {}
            for table_name, column, nullable in (await conn.execute(text(_COLUMNS))).all():
                db_cols.setdefault(table_name, {})[column] = nullable == "YES"
            db_fks: dict[str, list[str]] = {}
            for table_name, cdef in (await conn.execute(text(_FKS))).all():
                db_fks.setdefault(table_name, []).append(cdef)
    finally:
        await engine.dispose()

    orm_tables = set(Base.metadata.tables)
    gaps: list[str] = []
    for name in sorted(db_tables - orm_tables):
        gaps.append(f"{name}: 実DBにあるがORMが宣言していない表")
    for name in sorted(orm_tables - db_tables):
        gaps.append(f"{name}: ORMが宣言しているが実DBに無い表")

    for name in sorted(orm_tables & db_tables):
        table = Base.metadata.tables[name]
        orm_c = {c.name: bool(c.nullable) for c in table.columns}
        db_c = db_cols.get(name, {})
        for col in sorted(set(orm_c) - set(db_c)):
            gaps.append(f"{name}.{col}: ORMが宣言しているが実DBに無い列")
        for col in sorted(set(db_c) - set(orm_c)):
            gaps.append(f"{name}.{col}: 実DBにあるがORMが宣言していない列")
        for col in sorted(set(orm_c) & set(db_c)):
            if orm_c[col] != db_c[col]:
                gaps.append(f"{name}.{col}: NULL許容が違う（ORM={orm_c[col]} 実DB={db_c[col]}）")
        orm_f = _orm_fk_signatures(table)
        db_f = _db_fk_signatures(db_fks.get(name, []))
        for sig in sorted(db_f - orm_f):
            gaps.append(f"{name}: 実DBにあるがORMが宣言していない外部キー {sig}")
        for sig in sorted(orm_f - db_f):
            gaps.append(f"{name}: ORMが宣言しているが実DBに無い外部キー {sig}")
    return gaps


def main() -> int:
    parser = argparse.ArgumentParser(description="実DBとORM宣言のGAPを出す")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()
    url = args.database_url or os.environ.get("PROBE_DATABASE_URL")
    if url is None:
        from app.config import settings

        url = settings.database_url
    gaps = asyncio.run(_collect(url))
    if not gaps:
        print("GAP なし（実DBとORMの宣言が一致している）")
        return 0
    print(f"GAP {len(gaps)} 件")
    for gap in gaps:
        print(f"  {gap}")
    return 1


if __name__ == "__main__":
    from _stdio import use_utf8_stdio

    use_utf8_stdio()
    raise SystemExit(main())
