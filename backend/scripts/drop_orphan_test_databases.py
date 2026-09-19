"""作業ツリーが無くなったテストDBを落とす。

PostGIS統合テストのDBは作業ツリーごとに作られる（`tests/conftest.py`）。作業ツリーを
片付けてもDBは残るため、捨てる導線をここに置く（docs/caching.md「世代番号を使うなら、
旧世代を削除する導線をセットで用意する」と同じ形）。

**どのDBがどの作業ツリーのものかは、DB自身のコメントに書いてある**——名前から推測しない。
コメントが指すディレクトリが無ければ、そのDBは残骸である。

使い方（backend/から）:
    .venv/Scripts/python scripts/drop_orphan_test_databases.py          # 一覧するだけ
    .venv/Scripts/python scripts/drop_orphan_test_databases.py --drop   # 残骸を落とす
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.batch._common import asyncpg_dsn  # noqa: E402  sys.pathを通した後に読む

DEFAULT_SERVER = "postgresql+asyncpg://ridecompass:ridecompass@localhost:5432"
NAME_PREFIX = "ridecompass_test_"


def _is_worktree_record(comment: str | None) -> bool:
    return bool(comment) and os.path.isabs(comment)


async def collect(server: str) -> list[tuple[str, str | None, bool]]:
    """(DB名, 記録された作業ツリー, その作業ツリーが今もあるか) の一覧。"""
    conn = await asyncpg.connect(asyncpg_dsn(f"{server}/postgres"))
    try:
        rows = await conn.fetch(
            "SELECT datname, shobj_description(oid, 'pg_database') AS owner_path"
            " FROM pg_database WHERE datname LIKE $1 ORDER BY datname",
            f"{NAME_PREFIX}%",
        )
    finally:
        await conn.close()
    # **作業ツリーの記録と言えるのは、絶対パスが書かれているものだけ**。コメントが無いDB
    # （この仕組みより前に手で作られたもの）と、パスでないコメントを持つDB（複製元の
    # テンプレート等）は判定の対象から外す——材料が無いものを消さない。
    return [
        (r["datname"], r["owner_path"], _is_worktree_record(r["owner_path"]))
        for r in rows
    ]


async def drop(server: str, names: list[str]) -> None:
    conn = await asyncpg.connect(asyncpg_dsn(f"{server}/postgres"))
    try:
        for name in names:
            await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            print(f"落としました: {name}")
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=os.environ.get("TEST_DATABASE_SERVER", DEFAULT_SERVER),
                        help="テストDBが載っているサーバー（既定はローカル）")
    parser.add_argument("--drop", action="store_true", help="一覧するだけでなく実際に落とす")
    args = parser.parse_args()

    found = asyncio.run(collect(args.server))
    if not found:
        print(f"{NAME_PREFIX}* のDBはありません。")
        return 0

    orphans = []
    for name, comment, is_record in found:
        if not is_record:
            print(f"  {name}: 作業ツリーの記録なし（{comment or 'コメントなし'}。手で判断すること）")
        elif os.path.isdir(comment):
            print(f"  {name}: 使用中 <- {comment}")
        else:
            print(f"  {name}: 残骸（作業ツリーが無い） <- {comment}")
            orphans.append(name)

    if not orphans:
        print("落とすべき残骸はありません。")
        return 0
    if not args.drop:
        print(f"\n残骸 {len(orphans)}件。落とすには --drop を付けて実行してください。")
        return 0
    asyncio.run(drop(args.server, orphans))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
