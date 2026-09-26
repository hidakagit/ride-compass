r"""取り直せない管理データ（軸の定義・較正値の上書き等）を書き出す・戻す。

対象は`orm_base.IRREPLACEABLE`の印を持つ表で、母集団はそこから導く。

**書き出しも戻しも、アプリが起動時に行うのと同じ読み込みを通す**（軸の検算・較正値の範囲の検算）。
書き出しで通らなければ何も出さずに失敗する——戻せない中身で手元の最新のバックアップを上書きする前に
止まるため。戻しで通らなければ何も書かずに失敗する。

戻しは既定で空の表にだけ入れる（`--replace`で入れ替える）。稼働中のbackendは戻した行を読み直さない
ので、戻したら再起動する。手順は`docs/conventions/deployment-sync.md`「本番DBを失ったとき」。

実行方法（backendディレクトリから）:
    python scripts/admin_data_backup.py dump > admin-data.json
    python scripts/admin_data_backup.py restore admin-data.json
    python scripts/admin_data_backup.py --database-url ... restore admin-data.json --replace
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from app.config import settings  # noqa: E402
from app.infrastructure.admin_data_backup import AdminDataRestoreError, dump_tables, restore_tables  # noqa: E402
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository  # noqa: E402
from app.infrastructure.tuning_overrides import TuningOverrideError, load_tuning_values  # noqa: E402
from app.services.axis_registry_service import AxisDefinitionSyncError, load_axis_definitions  # noqa: E402

logger = logging.getLogger("ridecompass.admin_data_backup")

#: 利用者が直せる失敗（中身・戻し先の状態）。これ以外の例外はそのまま上げる。
_EXPECTED_ERRORS = (AdminDataRestoreError, AxisDefinitionSyncError, TuningOverrideError)


async def _check_loadable(session: AsyncSession) -> None:
    await load_axis_definitions(AxisDefinitionRepository(session))
    await load_tuning_values(session)


def _summary(counts: dict[str, int]) -> str:
    return ",".join(f"{name}:{count}" for name, count in counts.items())


async def dump(database_url: str) -> str:
    """管理データのJSON。アプリが読み込めない中身なら例外で止まり、何も返さない。"""
    engine = create_async_engine(database_url)
    try:
        async with AsyncSession(engine) as session:
            await _check_loadable(session)
            tables = await dump_tables(session)
    finally:
        await engine.dispose()
    document = {
        "dumped_at": datetime.now(UTC).isoformat(),
        "git_commit": settings.git_commit,
        "tables": tables,
    }
    text = json.dumps(document, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    logger.info("管理データを書き出しました tables=%s bytes=%d",
                _summary({name: len(rows) for name, rows in tables.items()}), len(text.encode("utf-8")))
    return text


async def restore(database_url: str, text: str, *, replace: bool) -> dict[str, int]:
    """`dump`の出力を戻す。検算に通ってから確定する（通らなければロールバックして例外）。"""
    document = json.loads(text)
    if not isinstance(document, dict) or not isinstance(document.get("tables"), dict):
        raise AdminDataRestoreError("管理データのバックアップの形ではありません（tablesがありません）")
    engine = create_async_engine(database_url)
    try:
        async with AsyncSession(engine) as session:
            counts = await restore_tables(session, document["tables"], replace=replace)
            await _check_loadable(session)
            await session.commit()
    finally:
        await engine.dispose()
    logger.info("管理データを戻しました tables=%s dumped_at=%s git_commit=%s replace=%s",
                _summary(counts), document.get("dumped_at"), document.get("git_commit"), replace)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="取り直せない管理データを書き出す・戻す")
    parser.add_argument("--database-url", default=None)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("dump", help="標準出力へJSONで書き出す")
    restore_parser = commands.add_parser("restore", help="書き出したJSONを戻す")
    restore_parser.add_argument("file", type=Path)
    restore_parser.add_argument("--replace", action="store_true",
                                help="戻し先に行があれば消してから入れる（同じトランザクションの中で）")
    args = parser.parse_args(argv)
    # 標準出力はJSONだけにする（定期ジョブがそのままファイルへ受ける）。ログは標準エラーへ。
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s", stream=sys.stderr)
    database_url = args.database_url or settings.database_url
    try:
        if args.command == "dump":
            sys.stdout.write(asyncio.run(dump(database_url)))
        else:
            asyncio.run(restore(database_url, args.file.read_text(encoding="utf-8"), replace=args.replace))
    except _EXPECTED_ERRORS as error:
        logger.error("%s", error)
        return 1
    return 0


if __name__ == "__main__":
    from _stdio import use_utf8_stdio

    use_utf8_stdio()
    raise SystemExit(main())
