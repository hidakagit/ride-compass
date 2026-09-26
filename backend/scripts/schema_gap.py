"""実DBのスキーマと、ORMが宣言する形のGAPを出す。

**正本は実DBで、ORMの宣言は「あるべき姿」である。**一致は誰も保証していないので測る。

比較はalembicの`compare_metadata`が行う（表・列・型・NULL許容・既定値・インデックス・一意制約・
外部キー）。migrationのファイルは作らず、比較の部品としてだけ使う。

母集団から外すのは、アプリのスキーマではない表——拡張が持ち込む表（PostGISの`spatial_ref_sys`等）と、
取込が作る子パーティション（ORMは親の表だけを宣言する）。どちらも名前ではなく実DBのカタログから引く。

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

from alembic.autogenerate import compare_metadata  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.infrastructure.orm_base import declared_metadata  # noqa: E402

_NOT_OURS = """
SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND (c.relispartition OR EXISTS (
    SELECT 1 FROM pg_depend d
    WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e'))
"""

_SIDE = {"add": "ORMが宣言しているが実DBに無い", "remove": "実DBにあるがORMが宣言していない"}
_WHAT = {
    "table": "表", "column": "列", "index": "インデックス", "fk": "外部キー", "constraint": "制約",
    "type": "型", "nullable": "NULL許容", "default": "既定値",
}


def _label(obj) -> str:
    """表・インデックス・制約を「表(列) 名前」の形で示す。"""
    table = getattr(obj, "table", None)
    if table is None:
        return obj.name
    cols = ",".join(c.name for c in obj.columns)
    refs = getattr(obj, "elements", None)
    target = f" -> {refs[0].target_fullname.rsplit('.', 1)[0]}" if refs else ""
    return f"{table.name}({cols}){target} {obj.name or ''}".rstrip()


def _show(value) -> str:
    """既定値（`DefaultClause`）は中の式を、型はそのままの表記で出す。"""
    arg = getattr(value, "arg", value)
    return str(getattr(arg, "text", arg))


def _describe(diff) -> list[str]:
    if isinstance(diff, list):
        return [line for d in diff for line in _describe(d)]
    op, *rest = diff
    verb, _, what = op.partition("_")
    label = _WHAT.get(what, what)
    if verb == "modify":
        table, column, _existing, db_value, orm_value = rest[1:]
        return [f"{table}.{column}: {label}が違う（実DB={_show(db_value)} ORM={_show(orm_value)}）"]
    if verb not in _SIDE:
        return [repr(diff)]
    obj = rest[-1]
    name = f"{rest[1]}.{obj.name}" if what == "column" else _label(obj)
    return [f"{name}: {_SIDE[verb]}{label}"]


async def _collect(url: str) -> list[str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            not_ours = set((await conn.execute(text(_NOT_OURS))).scalars())

            def include_name(name, type_, parent_names) -> bool:
                return not (type_ == "table" and name in not_ours)

            def compare(sync_conn):
                context = MigrationContext.configure(sync_conn, opts={
                    "include_name": include_name,
                    "compare_server_default": True,
                })
                return compare_metadata(context, declared_metadata())

            diffs = await conn.run_sync(compare)
    finally:
        await engine.dispose()
    # 片側にしか無い表について、alembicはその表のインデックスも1件ずつ出す。表の1行で足りる。
    whole = {d[1].name for d in diffs if isinstance(d, tuple) and d[0] in ("add_table", "remove_table")}
    diffs = [d for d in diffs if not (isinstance(d, tuple) and d[0] in ("add_index", "remove_index")
                                      and d[1].table.name in whole)]
    return sorted(line for diff in diffs for line in _describe(diff))


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
