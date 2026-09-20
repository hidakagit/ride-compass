"""バッチ間共通ヘルパ。

複数のバッチが同じ形で必要とするもの——asyncpg用のDSN変換、SQLAlchemyセッション
ファクトリの生成と後始末、派生の世代を進める囲い、進捗の書式——をここへ集める。
特定のバッチだけが使うものは、そのバッチが持つ。
"""

import logging
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from typing import TypeVar

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.infrastructure import derived_data_meta

_T = TypeVar("_T")


@asynccontextmanager
async def batch_session_factory(database_url: str | None) -> AsyncIterator[async_sessionmaker]:
    """バッチ用のセッションファクトリを作り、終了時にエンジンを必ず破棄する。

    `precompute_*.py`・`presplit_road_graph.py`はいずれも「エンジンを作る→
    `async_sessionmaker`を作る→処理→`finally`で`engine.dispose()`」という同じ前後を持つ。
    バッチはリクエスト経路と違い自前でエンジンを持つ（`infrastructure/database.py`の
    共有セッションファクトリはアプリ稼働中の接続プールを前提にしており、単発実行の
    バッチが使うとプロセス終了時に破棄されない接続が残る）ため、この後始末を各バッチが
    書いていた。

    `expire_on_commit=False`はバッチ共通の前提——commit後もORMオブジェクトの属性へ
    触れる（件数集計・ログ出力）ため。
    """
    engine = create_async_engine(database_url or settings.database_url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def with_derived_data_revision_bump(
    coro: Awaitable[int], *, database_url: str | None, dry_run: bool
) -> int:
    """バッチ本体を実行し、成功したら派生データの世代（`derived_data_meta.revision`）を進める。

    進めないと、backendがディスクへ既にキャッシュ済みの材料を「作り直されていない」と
    判断して古いまま復元し続ける（未訪問のタイルだけが新しい値になるため気づきにくい）。
    **どのバッチが材料に効くかを個別に判断しない**——効かないバッチで余分に進めても
    キャッシュが1度作り直されるだけだが、効くバッチで進め忘れると静かに古い値が残る。

    dry-runと異常終了では進めない（DBを書いていない）。世代を進める書き込み自体が
    失敗してもバッチの終了コードは変えない——データは既に書けており、キャッシュの
    追随はTTLごとの次の確認でも回復するため、ここで失敗扱いにする方が害が大きい。
    """
    code = await coro
    if code != 0 or dry_run:
        return code
    try:
        async with batch_session_factory(database_url) as session_factory:
            async with session_factory() as session:
                revision = await derived_data_meta.bump_revision(session)
        logging.getLogger("ridecompass.batch").info("派生データ世代を進めました revision=%s", revision)
    except Exception:
        logging.getLogger("ridecompass.batch").warning(
            "派生データ世代の更新に失敗しました（キャッシュの追随が遅れます）", exc_info=True
        )
    return code


def asyncpg_dsn(sqlalchemy_url: str) -> str:
    """SQLAlchemy用URL（postgresql+asyncpg://...?ssl=require）を、asyncpg.connectが
    受け付けるDSNへ正規化する。`ssl=`クエリはSQLAlchemyのasyncpgダイアレクト固有の
    書き方のため、libpq互換の`sslmode=`へ読み替える（Supabase等のリモートDB用。
    ローカルのssl指定なしURLはドライバ指定の除去のみ）。"""
    dsn = sqlalchemy_url.replace("+asyncpg", "")
    return dsn.replace("?ssl=", "?sslmode=").replace("&ssl=", "&sslmode=")



#: 進捗を出す間隔（秒）。件数ごとに出すと、関東全域では行数が多すぎて読めない。
PROGRESS_INTERVAL_SECONDS = 15.0


def format_duration(seconds: float) -> str:
    minutes, second = divmod(int(seconds), 60)
    hour, minute = divmod(minutes, 60)
    return f"{hour}時間{minute:02d}分" if hour else f"{minute}分{second:02d}秒"


def format_progress(done: int, total: int | None, elapsed: float, unit: str = "件") -> str:
    """済んだ数・速さ・残りの見込み。**残りは実測の速さから出す**。

    `total`がNoneのとき（流しながら読むソースのように、全体数が終わるまで分からない
    とき）は残りを出さない——分からないものを推測で埋めると、読み手が当てにする。
    """
    rate = done / elapsed if elapsed > 0 else 0.0
    line = f"{done:,}{unit} / 経過 {format_duration(elapsed)} / {rate:.1f}{unit}/秒"
    if total:
        remaining = (total - done) / rate if rate > 0 else 0.0
        line = (f"{done:,}/{total:,}{unit}（{done / total * 100:.1f}%）"
                f" / 経過 {format_duration(elapsed)} / {rate:.1f}{unit}/秒"
                f" / 残り およそ {format_duration(remaining)}")
    return line
