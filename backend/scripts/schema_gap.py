"""実DBのスキーマと、ORMが宣言する形のGAPを出す。

**正本は実DBで、ORMの宣言は「あるべき姿」である。**一致は誰も保証していないので測る。

宣言の側も実DBに作らせてから比べる。同じ接続の一時スキーマ（`pg_temp`）へ宣言どおりの表を作り、
`public`の表とカタログを突き合わせて、最後に巻き戻す。制約・既定値・索引の式はPostgreSQLが
正規化した文字列（`pg_get_constraintdef`等）で比べるので、ORMの書き方と実DBの表記の違い
（括弧・型の付け方）では差が出ず、CHECKの式・主キー・一意・外部キーの中身の違いは差として出る。
名前は比べない——作った経路によって名前だけが違うものを差と数えないため。

比べるもの: 表・パーティションの切り方・列（型・NULL許容・既定値・格納の仕方）・制約（主キー・
一意・外部キー・CHECK・排他）・索引（制約が持つものを除く）。

母集団から外すのは、アプリのスキーマではない表——拡張が持ち込む表（PostGISの`spatial_ref_sys`等）と、
取込が作る子パーティション（ORMは親の表だけを宣言する）。どちらも名前ではなく実DBのカタログから引く。

一時スキーマは接続ごとのもので、作った表はトランザクションの巻き戻しで消える。`public`の表には
書かない。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\schema_gap.py                    # settings.database_url
    .venv\\Scripts\\python.exe scripts\\schema_gap.py --database-url ...
    .venv\\Scripts\\python.exe scripts\\run_probe.py scripts\\schema_gap.py   # 本番

GAPが1件でもあれば終了コード1。
"""

import argparse
import asyncio
import os
import re
import sys
from collections.abc import Iterable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import Connection, text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.infrastructure.orm_base import declared_metadata  # noqa: E402

_TABLES = """
SELECT c.relname AS table, coalesce(pg_get_partkeydef(c.oid), '') AS partition
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = :schema AND c.relkind IN ('r', 'p') AND NOT c.relispartition
  AND NOT EXISTS (SELECT 1 FROM pg_depend d
                  WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e')
"""

_COLUMNS = """
SELECT c.relname AS table, a.attname AS column,
       format_type(a.atttypid, a.atttypmod) AS type,
       CASE WHEN a.attnotnull THEN 'NOT NULL' ELSE 'NULL' END AS nullable,
       coalesce(pg_get_expr(d.adbin, d.adrelid), '') AS default,
       a.attstorage::text AS storage
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE n.nspname = :schema AND c.relkind IN ('r', 'p') AND a.attnum > 0 AND NOT a.attisdropped
"""

#: NOT NULLは列の側で比べる（PostgreSQL 18からは制約の表にも載る）。
_CONSTRAINTS = """
SELECT c.relname AS table, con.contype::text AS kind, pg_get_constraintdef(con.oid) AS definition
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = :schema AND con.contype <> 'n'
"""

#: 制約（主キー・一意・排他）が持つ索引は制約の側で比べる。
_INDEXES = """
SELECT c.relname AS table, pg_get_indexdef(ix.indexrelid) AS definition
FROM pg_index ix
JOIN pg_class c ON c.oid = ix.indrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = :schema
  AND NOT EXISTS (SELECT 1 FROM pg_constraint con
                  WHERE con.conrelid = ix.indrelid AND con.conindid = ix.indexrelid
                    AND con.contype IN ('p', 'u', 'x'))
"""

_KIND = {"p": "主キー", "u": "一意", "f": "外部キー", "c": "CHECK", "x": "排他"}
_COLUMN_FIELDS = {"type": "型", "nullable": "NULL許容", "default": "既定値", "storage": "格納の仕方"}

#: どちらのスキーマの名前で修飾されたかは比べない。一時スキーマの表が同じ名前の`public`の表を
#: 隠すため、式の中の名前は片側だけ修飾されて出る。
_SCHEMA_PREFIX = re.compile(r"\b(?:public|pg_temp_\d+)\.")
_INDEX_HEAD = re.compile(r"^CREATE (UNIQUE )?INDEX \S+ ON (?:ONLY )?\S+ ")


def _plain(sql: str) -> str:
    return _SCHEMA_PREFIX.sub("", sql)


class _Catalog:
    """1つのスキーマの表・列・制約・索引を、名前を除いた比べられる形で持つ。"""

    def __init__(self, conn: Connection, schema: str):
        def rows(sql: str) -> Iterable:
            return conn.execute(text(sql), {"schema": schema}).mappings()

        self.tables = {r["table"]: r["partition"] for r in rows(_TABLES)}
        self.columns = {(r["table"], r["column"]): {f: _plain(r[f]) for f in _COLUMN_FIELDS}
                        for r in rows(_COLUMNS) if r["table"] in self.tables}
        self.constraints = {(r["table"], _KIND.get(r["kind"], r["kind"]), _plain(r["definition"]))
                            for r in rows(_CONSTRAINTS) if r["table"] in self.tables}
        self.indexes = {(r["table"], "索引", _INDEX_HEAD.sub(r"\1", _plain(r["definition"])))
                        for r in rows(_INDEXES) if r["table"] in self.tables}


def _differences(actual: _Catalog, declared: _Catalog) -> list[str]:
    lines = [f"{t}: ORMが宣言しているが実DBに無い表" for t in declared.tables.keys() - actual.tables.keys()]
    lines += [f"{t}: 実DBにあるがORMが宣言していない表" for t in actual.tables.keys() - declared.tables.keys()]
    both = declared.tables.keys() & actual.tables.keys()
    lines += [f"{t}: パーティションの切り方が違う（実DB={actual.tables[t] or 'なし'} ORM={declared.tables[t] or 'なし'}）"
              for t in both if actual.tables[t] != declared.tables[t]]

    for key in declared.columns.keys() | actual.columns.keys():
        if key[0] not in both:
            continue
        name = ".".join(key)
        if key not in actual.columns:
            lines.append(f"{name}: ORMが宣言しているが実DBに無い列")
        elif key not in declared.columns:
            lines.append(f"{name}: 実DBにあるがORMが宣言していない列")
        else:
            lines += [f"{name}: {label}が違う（実DB={actual.columns[key][f] or 'なし'} "
                      f"ORM={declared.columns[key][f] or 'なし'}）"
                      for f, label in _COLUMN_FIELDS.items() if actual.columns[key][f] != declared.columns[key][f]]

    for side, only in (("ORMが宣言しているが実DBに無い", declared.constraints - actual.constraints),
                       ("実DBにあるがORMが宣言していない", actual.constraints - declared.constraints),
                       ("ORMが宣言しているが実DBに無い", declared.indexes - actual.indexes),
                       ("実DBにあるがORMが宣言していない", actual.indexes - declared.indexes)):
        lines += [f"{table}: {side}{kind} {definition}" for table, kind, definition in only if table in both]
    return sorted(lines)


def collect_gaps(conn: Connection) -> list[str]:
    """`conn`のDBの`public`と、ORMの宣言を一時スキーマへ作ったものとの差。何も残さない。"""
    transaction = conn.begin_nested() if conn.in_transaction() else conn.begin()
    try:
        # 一時スキーマへ作るだけで`public`の表を待つことは無いが、万一のロック待ちで本番を止めない。
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        declared_metadata().create_all(
            conn.execution_options(schema_translate_map={None: "pg_temp"}), checkfirst=False)
        temp = conn.execute(text("SELECT nspname FROM pg_namespace WHERE oid = pg_my_temp_schema()")).scalar_one()
        return _differences(_Catalog(conn, "public"), _Catalog(conn, temp))
    finally:
        transaction.rollback()


async def _collect(url: str) -> list[str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(collect_gaps)
    finally:
        await engine.dispose()


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
