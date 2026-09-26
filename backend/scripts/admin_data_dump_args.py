"""取り直せない管理データの表を書き出す`pg_dump`の引数を、1行に1つ出す。

対象は`orm_base.IRREPLACEABLE`の印を持つ表で、母集団はそこから導く（印を付けた表は次の書き出しから入る）。
DB名は`DATABASE_URL`から取り、接続先・利用者・パスワードは出さない——VMの上の`pg_dump`は
postgresユーザーのpeer認証で同じDBへつなぐ。読むのは`backend/ops/admin_data_backup.sh`。

実行方法（backendディレクトリから）:
    python scripts/admin_data_dump_args.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.engine import make_url  # noqa: E402

from app.config import settings  # noqa: E402
from app.infrastructure.orm_base import IRREPLACEABLE_KEY, declared_metadata  # noqa: E402


def dump_args(database_url: str) -> list[str]:
    tables = [table.name for table in declared_metadata().sorted_tables if table.info.get(IRREPLACEABLE_KEY)]
    return [f"--dbname={make_url(database_url).database}", *(f"--table={name}" for name in tables)]


if __name__ == "__main__":
    print("\n".join(dump_args(settings.database_url)))
