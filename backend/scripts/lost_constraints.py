r"""2つの版のORM宣言を突き合わせ、消えた制約を出す。

表を宣言し直す・別のファイルへ書き直す変更では、落ちた制約が差分に1行も出ない（古いファイルを
消し、新しいファイルを足す形になる）。ここでは両方の版の`backend/app`を取り出し、宣言された
表の制約を同じ形の文字列へ揃えて差を取る。消えたものは、1件ずつ処置（移した先・意図して
外した理由）を付けてから取り込む（docs/conventions/flow.md「作る担当」の5・「確かめる担当」の1）。

見るもの: 表・主キー・外部キー（ON DELETE込み）・一意（一意インデックスを含む）・CHECK・
NOT NULL・表に付けた生のDDL（`event.listen(..., DDL(...))`）。制約の名前は見ない——書き直しで
名前だけ変わったものを消えたと数えないため。

見ないもの: SQLの文の中の絞り込み（WHERE・JOINの条件）。SQLは断片をつないで組み立てる形が
多く、文字列から構文木を取れないものが残るため、期待値テストで守る。

表の宣言は、`backend/app`の下で`__tablename__`か`Table(`を含むモジュールを全部importして
集める。版によって全表を集める入口（`orm_base.declared_metadata`）が無いため。

実行方法（作業ツリーの根からでも`backend`からでも同じ結果になる）:
    backend\.venv\Scripts\python.exe backend\scripts\lost_constraints.py             # master との合流点 → HEAD
    backend\.venv\Scripts\python.exe backend\scripts\lost_constraints.py BASE HEAD   # 任意の2つの版

消えたものが1件でもあれば終了コード1。
"""

import argparse
import gc
import importlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path

Item = tuple[str, str, str]

TABLE = "表"


def constraint_items(metadatas) -> set[Item]:
    """宣言された表と制約を`(種類, 表, 中身)`へ揃える。"""
    from sqlalchemy import CheckConstraint, ForeignKeyConstraint, PrimaryKeyConstraint, UniqueConstraint
    from sqlalchemy.schema import DDL

    items: set[Item] = set()
    for metadata in metadatas:
        for table in metadata.tables.values():
            name = table.name
            items.add((TABLE, name, ""))
            items.update(("NOT NULL", name, c.name) for c in table.columns if not c.nullable)
            for con in table.constraints:
                cols = "(" + ",".join(c.name for c in con.columns) + ")"
                if isinstance(con, PrimaryKeyConstraint) and con.columns:
                    items.add(("主キー", name, cols))
                elif isinstance(con, ForeignKeyConstraint):
                    ref = ",".join(e.target_fullname for e in con.elements)
                    items.add(("外部キー", name, f"{cols} -> {ref} ON DELETE {con.ondelete or 'NO ACTION'}"))
                elif isinstance(con, UniqueConstraint):
                    items.add(("一意", name, cols))
                elif isinstance(con, CheckConstraint):
                    items.add(("CHECK", name, " ".join(str(con.sqltext).split())))
            for index in table.indexes:
                if index.unique:
                    items.add(("一意", name, "(" + ",".join(str(e) for e in index.expressions) + ")"))
            for listener in table.dispatch.after_create:
                ddl = getattr(listener, "__self__", listener)
                if isinstance(ddl, DDL):
                    items.add(("DDL", name, " ".join(ddl.statement.split())))
    return items


def lost(before: set[Item], after: set[Item]) -> list[Item]:
    """消えたもの。表ごと消えたときは、その表の制約を並べずに表の1行で示す。"""
    gone_tables = {name for kind, name, _ in before - after if kind == TABLE}
    return sorted(item for item in before - after if item[0] == TABLE or item[1] not in gone_tables)


def _dump(backend_dir: Path) -> None:
    """取り出した版の`backend`で表を宣言するモジュールを全部importし、制約をJSONで出す。"""
    from sqlalchemy import MetaData

    sys.path.insert(0, str(backend_dir))
    for path in sorted((backend_dir / "app").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "__tablename__" in source or "Table(" in source:
            importlib.import_module(".".join(path.relative_to(backend_dir).with_suffix("").parts))
    metadatas = [o for o in gc.get_objects() if isinstance(o, MetaData)]
    print(json.dumps(sorted(constraint_items(metadatas)), ensure_ascii=False))


def _items_at(rev: str) -> set[Item]:
    archive = subprocess.run(["git", "archive", rev, "backend/app"], cwd=_git("rev-parse", "--show-toplevel"),
                             capture_output=True, check=True).stdout
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(fileobj=BytesIO(archive)) as tar:
            tar.extractall(tmp, filter="data")
        backend = Path(tmp) / "backend"
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
        out = subprocess.run([sys.executable, __file__, "--dump", str(backend)], cwd=backend, env=env,
                             capture_output=True, text=True, encoding="utf-8")
    if out.returncode:
        raise SystemExit(f"{rev} の宣言を読めませんでした:\n{out.stderr}")
    return {tuple(item) for item in json.loads(out.stdout)}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


def main() -> int:
    if sys.argv[1:2] == ["--dump"]:
        _dump(Path(sys.argv[2]))
        return 0
    parser = argparse.ArgumentParser(description="2つの版のORM宣言から、消えた制約を出す")
    parser.add_argument("base", nargs="?", default=None, help="前の版（既定: origin/master との合流点）")
    parser.add_argument("head", nargs="?", default="HEAD", help="後の版（既定: HEAD）")
    args = parser.parse_args()
    base = args.base or _git("merge-base", "origin/master", args.head)
    if _git("rev-parse", f"{base}:backend/app") == _git("rev-parse", f"{args.head}:backend/app"):
        print(f"{base[:9]} と {args.head} で backend/app に差が無い（消えた制約なし）")
        return 0
    before, after = _items_at(base), _items_at(args.head)
    gone = lost(before, after)
    print(f"{base[:9]} → {args.head}: 消えた {len(gone)} 件・足された {len(after - before)} 件")
    for kind, table, detail in gone:
        print(f"  消えた {kind} {table} {detail}".rstrip())
    for kind, table, detail in sorted(after - before):
        print(f"  足された {kind} {table} {detail}".rstrip())
    return 1 if gone else 0


if __name__ == "__main__":
    from _stdio import use_utf8_stdio

    use_utf8_stdio()
    raise SystemExit(main())
