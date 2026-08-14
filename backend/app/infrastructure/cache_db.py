import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# 標高（ルート沿いの点取得、Step5）はプロセス再起動やコンテナ再作成をまたいで使い回すため、
# メモリ内辞書ではなくファイルベースのSQLiteに永続化する（新規pip依存なし）。
# 路面の地域レイヤー（Step10）はベクタタイル（バイナリ）のため、こちらではなく
# infrastructure/tile_cache.py（基礎地図タイルと共通のファイルキャッシュ）を使う。
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_PATH = DATA_DIR / "ridecompass_cache.db"

# 「未キャッシュ」と「キャッシュ済みだが値がNone（取得失敗）」を区別するための番兵。
MISSING = object()


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS elevation_cache (
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            elevation_m REAL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (lat, lon)
        )"""
    )
    conn.commit()
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_elevation_sync(lat: float, lon: float):
    # キャッシュは高速化のための最適化であり、標高取得そのものの成否には関与しない
    # （GSI APIへのフォールバックが常に効く）。DBロック競合等でSQLiteが失敗しても
    # ルート生成全体を巻き添えにせず、「未キャッシュ」として扱ってフォールバックさせる。
    try:
        conn = _connect()
    except sqlite3.Error:
        return MISSING
    try:
        row = conn.execute("SELECT elevation_m FROM elevation_cache WHERE lat = ? AND lon = ?", (lat, lon)).fetchone()
        return MISSING if row is None else row[0]
    except sqlite3.Error:
        return MISSING
    finally:
        conn.close()


def _set_elevation_sync(lat: float, lon: float, elevation_m: float | None) -> None:
    try:
        conn = _connect()
    except sqlite3.Error:
        return
    try:
        conn.execute(
            "INSERT OR REPLACE INTO elevation_cache (lat, lon, elevation_m, fetched_at) VALUES (?, ?, ?, ?)",
            (lat, lon, elevation_m, _now_iso()),
        )
        conn.commit()
    except sqlite3.Error:
        pass
    finally:
        conn.close()


async def get_elevation(lat: float, lon: float):
    """キャッシュ済みなら標高(m)またはNone（取得失敗を記録済み）、未キャッシュならMISSINGを返す。"""
    return await asyncio.to_thread(_get_elevation_sync, lat, lon)


async def set_elevation(lat: float, lon: float, elevation_m: float | None) -> None:
    await asyncio.to_thread(_set_elevation_sync, lat, lon, elevation_m)
