import asyncio
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.infrastructure.debug_log import log_throttled_warning

# 標高（ルート沿いの点取得、Step5）はプロセス再起動やコンテナ再作成をまたいで使い回すため、
# メモリ内辞書ではなくファイルベースのSQLiteに永続化する（新規pip依存なし）。
# 路面の地域レイヤー（Step10）はベクタタイル（バイナリ）のため、こちらではなく
# infrastructure/tile_cache.py（基礎地図タイルと共通のファイルキャッシュ）を使う。
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_PATH = DATA_DIR / "ridecompass_cache.db"

# 「未キャッシュ」と「キャッシュ済みだが値がNone（取得失敗）」を区別するための番兵。
MISSING = object()

# スレッドごとに接続を1本だけ張って使い回す（呼び出しのたびに新規接続 + PRAGMA +
# CREATE TABLE IF NOT EXISTSを実行し直すと大幅に遅くなることが実測で判明したため。
# 800回連続呼び出しで約140倍の差、backend/benchmarks/bench_elevation_cache.py・
# README.md参照）。get/set は`asyncio.to_thread`経由で呼ばれ、既定のThreadPoolExecutorは
# ワーカースレッドを使い捨てず再利用するため、スレッドローカルに接続をキャッシュすれば
# 実質的に「接続の使い回し」が成立する。sqlite3.Connectionは複数スレッドから同時に
# 使う設計にはしていない（既定のcheck_same_thread=Trueのまま）ため、1接続=1スレッド
# 専有という制約とも矛盾しない。
_thread_local = threading.local()


def _connect(path: Path) -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
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


def _get_connection() -> sqlite3.Connection:
    """呼び出しスレッドのキャッシュ済み接続を返す。無い場合、またはDB_PATHが
    キャッシュ時点から変わっている場合（テストのmonkeypatch等）は張り直す。"""
    cached_conn = getattr(_thread_local, "conn", None)
    cached_path = getattr(_thread_local, "db_path", None)
    if cached_conn is not None and cached_path == DB_PATH:
        return cached_conn

    if cached_conn is not None:
        cached_conn.close()

    conn = _connect(DB_PATH)
    _thread_local.conn = conn
    _thread_local.db_path = DB_PATH
    return conn


def _discard_connection() -> None:
    """キャッシュ済み接続を破棄する（クエリ失敗時、壊れた接続を次回張り直させるため）。"""
    conn = getattr(_thread_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except sqlite3.Error:
            pass
    _thread_local.conn = None
    _thread_local.db_path = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_elevation_sync(lat: float, lon: float):
    # キャッシュは高速化のための最適化であり、標高取得そのものの成否には関与しない
    # （GSI APIへのフォールバックが常に効く）。DBロック競合等でSQLiteが失敗しても
    # ルート生成全体を巻き添えにせず、「未キャッシュ」として扱ってフォールバックさせる。
    # ただしフォールバックで隠れたままにならないよう、失敗自体は抑制付きWARNINGで
    # 常時記録する（キャッシュが継続的に壊れている＝GSIへの問い合わせが減らず遅い、
    # という状態に運用側が気づけるようにする。docs/logging.md参照）。
    try:
        conn = _get_connection()
        row = conn.execute("SELECT elevation_m FROM elevation_cache WHERE lat = ? AND lon = ?", (lat, lon)).fetchone()
        return MISSING if row is None else row[0]
    except sqlite3.Error as exc:
        log_throttled_warning("cache:elevation-sqlite", "[cache:elevation-sqlite] read failed error=%r", exc)
        _discard_connection()
        return MISSING


def _set_elevation_sync(lat: float, lon: float, elevation_m: float | None) -> None:
    try:
        conn = _get_connection()
        conn.execute(
            "INSERT OR REPLACE INTO elevation_cache (lat, lon, elevation_m, fetched_at) VALUES (?, ?, ?, ?)",
            (lat, lon, elevation_m, _now_iso()),
        )
        conn.commit()
    except sqlite3.Error as exc:
        log_throttled_warning("cache:elevation-sqlite", "[cache:elevation-sqlite] write failed error=%r", exc)
        _discard_connection()


async def get_elevation(lat: float, lon: float):
    """キャッシュ済みなら標高(m)またはNone（取得失敗を記録済み）、未キャッシュならMISSINGを返す。"""
    return await asyncio.to_thread(_get_elevation_sync, lat, lon)


async def set_elevation(lat: float, lon: float, elevation_m: float | None) -> None:
    await asyncio.to_thread(_set_elevation_sync, lat, lon, elevation_m)
