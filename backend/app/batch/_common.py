"""バッチ間共通ヘルパ（改善計画T80）。

asyncpg用DSN変換が4バッチ（import_pbf.py・import_accidents.py・match_designations.py・
import_designations.py）に、ファイルダウンロードの骨格が2バッチ（import_accidents.py・
import_designations.py）にそれぞれ独立実装として増殖していた
（import_accidents.pyのdocstring「2箇所だけのため共通化しない」の前提が崩れた）。
改善計画T467: `_status_count`（import_accidents.py・import_pbf.py）・`_chunked`
（precompute_edge_attribute_counts.py・precompute_elevation_attributes.py・
precompute_way_attribute_counts.py）も、本ファイル新設後に独立実装のまま残っていた
同種の重複だったためここへ統合した。
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TypeVar

import asyncpg
import httpx

_T = TypeVar("_T")

# 改善計画T467: *_import_runsのrunning行がプロセスクラッシュ（OOM-kill・強制終了・VM再起動等）
# で永久にrunningのまま残留する問題（zero-base-review-2026-08-30.md指摘、db_status診断
# エンドポイントがこの行を「今も実行中」と誤認し続ける）への対応。次回このバッチが起動した
# 時点で、これより古いrunning行は「クラッシュで取り残された」とみなしfailedへ遷移させる
# （自己修復）。実行中のバッチが本当にこの時間を超えて走り続けるケース（全国規模のPBF取込等）
# を誤検知しないよう、通常の1回の実行時間より十分長い値にする。
_STALE_RUNNING_THRESHOLD = timedelta(hours=6)


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


def chunked(items: list[_T], size: int) -> list[list[_T]]:
    """itemsをsize件ずつのチャンクへ分割する。"""
    return [items[i : i + size] for i in range(0, len(items), size)]


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
