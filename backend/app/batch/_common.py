"""バッチ間共通ヘルパ。

asyncpg用DSN変換（import_pbf.py・import_accidents.py・match_designations.py・
import_designations.py）、ファイルダウンロードの骨格（import_accidents.py・
import_designations.py）、SQLAlchemyセッションファクトリの生成と後始末
（precompute_*.py・presplit_road_graph.py）、単純なCLI（--database-url/--dry-run）の
起動処理、対象IDのストリーミング取得・コマンドステータス件数パース
など、複数バッチが共通で必要とする処理をここへ集約する。
"""

import argparse
import asyncio
import logging
import math
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TypeVar

import asyncpg
import httpx
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings

_T = TypeVar("_T")

# *_import_runsのrunning行はプロセスクラッシュ（OOM-kill・強制終了・VM再起動等）で
# 永久にrunningのまま残留しうる（db_status診断エンドポイントがこの行を「今も実行中」と
# 誤認し続ける）。次回このバッチが起動した時点で、これより古いrunning行は「クラッシュで
# 取り残された」とみなしfailedへ遷移させる（自己修復）。実行中のバッチが本当にこの時間を
# 超えて走り続けるケース（全国規模のPBF取込等）を誤検知しないよう、通常の1回の実行時間
# より十分長い値にする。
_STALE_RUNNING_THRESHOLD = timedelta(hours=6)


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


def run_simple_batch_cli(
    argv: list[str] | None,
    *,
    description: str,
    run_fn: Callable[[str | None, bool], Awaitable[int]],
    dry_run_help: str = "件数のみログ出力しDBへ書き込まない",
) -> int:
    """`--database-url`と`--dry-run`だけを取るバッチの起動処理。

    引数の解析・ログ設定・`asyncio.run`まで行い、`run_fn`の戻り値をそのまま終了コード
    として返す。追加の引数を持つバッチ（`precompute_way_landcover.py`）は自前で
    `ArgumentParser`を組む。
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--database-url", default=None, help="対象DB（省略時はsettings.database_url）")
    parser.add_argument("--dry-run", action="store_true", help=dry_run_help)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return asyncio.run(run_fn(args.database_url, args.dry_run))


async def reap_stale_running_import_runs(conn: asyncpg.Connection, table: str) -> int:
    """`table`（*_import_runsのいずれか）のstatus='running'な行のうち、started_atが
    `_STALE_RUNNING_THRESHOLD`より古いものをfailedへ遷移させる。各バッチのrun()冒頭
    （新しいrunning行をINSERTする前）で呼ぶ想定。戻り値は遷移させた件数（呼び出し側の
    ログ用）。"""
    threshold = datetime.now(timezone.utc) - _STALE_RUNNING_THRESHOLD
    rows = await conn.fetch(
        f"UPDATE {table} SET status='failed', finished_at=now() "  # noqa: S608 tableは呼び出し側のハードコード文字列、外部入力なし
        "WHERE status='running' AND started_at < $1 RETURNING id",
        threshold,
    )
    return len(rows)


def status_count(status: str) -> int:
    """asyncpgのexecuteが返す"INSERT 0 123"のようなコマンドステータス文字列から
    件数部分を取り出す。パース失敗時は0。"""
    try:
        return int(status.split()[-1])
    except (ValueError, IndexError):
        return 0


async def count_targets(session_factory: async_sessionmaker, stmt: Select) -> int:
    """`stream_id_chunks`へ渡すのと同じselectの対象件数を数える。

    ストリーミングは事前に総数を知らないため、進捗ログの分母とdry-runの出力はこの
    1回のCOUNTから得る。`ORDER BY`は件数に影響せずソートのコストだけを足すので外す。
    """
    async with session_factory() as session:
        result = await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
        return int(result.scalar_one())


async def stream_id_chunks(
    session_factory: async_sessionmaker, stmt: Select, chunk_size: int
) -> AsyncIterator[list[_T]]:
    """selectの1列目を`chunk_size`件ずつ取り出す（対象IDをPython側へ全件は載せない）。

    サーバーサイドカーソル（`stream_results`）で読み進めるため、対象が数百万件でも
    プロセスのメモリ使用量は1チャンク分に留まる。`stmt`の`ORDER BY`はそのまま効く
    （地理的順序で読むバッチが、近接するEdge/wayを同じチャンクへ集めてタイル・ラスタの
    キャッシュを効かせるために使う）。

    カーソルを持つ読み取り専用セッションを開いたまま呼び出し元へ制御を戻すため、
    **チャンクの処理は必ず別セッションで行うこと**——同じセッションで書き込むと、
    カーソルの属するトランザクションが書き込みごと長時間開いたままになる。
    """
    async with session_factory() as session:
        result = await session.stream(stmt)
        async for partition in result.partitions(chunk_size):
            yield [row[0] for row in partition]


async def run_chunked_precompute(
    session_factory: async_sessionmaker,
    stmt: Select,
    chunk_size: int,
    handle_chunk: Callable[[list], Awaitable[int]],
    *,
    logger: logging.Logger,
    target_label: str,
    empty_warning: str,
    dry_run: bool,
    dry_run_note: str = "DB書き込みなし",
) -> int:
    """precompute系バッチのドライバ。対象件数のログ → dry-runの早期return → 0件の警告 →
    `stream_id_chunks`ループ → チャンクごとの進捗ログ、までを引き受ける。

    バッチごとに違うのは`handle_chunk`（1チャンクぶんの実処理、書き込んだ件数を返す）と
    ログの文言だけ。この骨格を各バッチへ写すと、進捗ログの体裁や0件時の扱いがバッチごとに
    ずれ、後から直すときに全部を追う必要が出る。

    ループの外側で資源を持ちたい場合（HTTPクライアント等）は、呼び出し側が`async with`で
    囲んでこの関数をawaitすればよい。**ループ内に固有の関心事（範囲外判定・部分被覆の
    集計等）を持つバッチは無理にこの器へ入れない**——`handle_chunk`が返す件数1つでは
    表せない進捗を持つため、そちらは自前のループのままでよい。

    戻り値はバッチの終了コード（常に0。失敗は例外で表す）。
    """
    started = time.perf_counter()
    target_count = await count_targets(session_factory, stmt)
    logger.info("%s: %d件（chunk_size=%d）", target_label, target_count, chunk_size)
    if dry_run:
        logger.info("dry-run完了: %s elapsed=%.1fs", dry_run_note, time.perf_counter() - started)
        return 0
    if target_count == 0:
        logger.warning("%s", empty_warning)
        return 0

    total_chunks = math.ceil(target_count / chunk_size)
    total_written = 0
    chunk_index = -1
    async for chunk in stream_id_chunks(session_factory, stmt, chunk_size):
        chunk_index += 1
        chunk_started = time.perf_counter()
        written = await handle_chunk(chunk)
        total_written += written
        logger.info(
            "chunk %d/%d 完了: %d件（累計%d件） elapsed=%.1fs",
            chunk_index + 1, total_chunks, written, total_written,
            time.perf_counter() - chunk_started,
        )
    logger.info("事前集計完了: total=%d件 elapsed=%.1fs", total_written, time.perf_counter() - started)
    return 0


def asyncpg_dsn(sqlalchemy_url: str) -> str:
    """SQLAlchemy用URL（postgresql+asyncpg://...?ssl=require）を、asyncpg.connectが
    受け付けるDSNへ正規化する。`ssl=`クエリはSQLAlchemyのasyncpgダイアレクト固有の
    書き方のため、libpq互換の`sslmode=`へ読み替える（Supabase等のリモートDB用。
    ローカルのssl指定なしURLはドライバ指定の除去のみ）。"""
    dsn = sqlalchemy_url.replace("+asyncpg", "")
    return dsn.replace("?ssl=", "?sslmode=").replace("&ssl=", "&sslmode=")


async def download_to_path(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    *,
    logger: logging.Logger,
    label: str,
    context: str,
    timeout_seconds: float = 60.0,
) -> Path | None:
    """`url`の内容を`dest`へ直接取得して保存する。

    dest存在チェック→`.part`一時ファイルへストリーム書き込み→`replace`→HTTPError時は
    WARNING＋`.part`削除、という骨格を全バッチ共通で提供する。既にダウンロード済み
    （同名ファイルが存在）ならHTTPアクセスを省略する（大容量ファイルを毎回再取得しない）。
    404等の取得失敗はWARNINGで常時出力しNoneを返す（docs/logging.mdのエラー常時WARNING
    方針。1件の取得失敗でバッチ全体を止めるかどうかは呼び出し元の設計に委ねる）。

    `label`はログの主語（例: "本票CSV"「指定路線データ」）、`context`は年・kind・都道府県
    コード等の識別情報（例: "year=2023"）で、既存2バッチのログ文言の構造をそのまま踏襲する。
    """
    if dest.exists():
        logger.info("%sは取得済みのためスキップ %s path=%s", label, context, dest)
        return dest

    started = time.perf_counter()
    tmp_dest = dest.with_suffix(dest.suffix + ".part")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with client.stream("GET", url, timeout=httpx.Timeout(timeout_seconds)) as response:
            response.raise_for_status()
            with open(tmp_dest, "wb") as f:
                async for chunk in response.aiter_bytes():
                    f.write(chunk)
        tmp_dest.replace(dest)
    except httpx.HTTPError as exc:
        logger.warning("%s取得に失敗しました %s url=%s error=%r", label, context, url, exc)
        tmp_dest.unlink(missing_ok=True)
        return None
    logger.info(
        "%s取得完了 %s size_mb=%.1f elapsed=%.1fs",
        label, context, dest.stat().st_size / 1_000_000, time.perf_counter() - started,
    )
    return dest
