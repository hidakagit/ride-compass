import asyncio
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.infrastructure.debug_log import log_throttled_warning

# 標高（ルート沿いの点取得、Step5）はプロセス再起動やコンテナ再作成をまたいで使い回すため、
# メモリ内辞書ではなくファイルベースのSQLiteに永続化する（新規pip依存なし）。
# 路面の地域レイヤー（Step10）はベクタタイル（バイナリ）のため、こちらではなく
# infrastructure/tile_cache.py（基礎地図タイルと共通のファイルキャッシュ）を使う。
# 気象グリッド（風・降水延長予報、weather_client.py: get_forecast_many）も改善計画
# （「Renderのようなプロセス再起動でメモリキャッシュが消える環境では、まずDB永続化(④)を
# 先にやるべき」という判断）を受け、同じ理由・同じ仕組み（ファイルベースSQLite）で
# ここへ相乗りさせる。1プロセス内の高速な繰り返し参照はweather_client.py側の
# 既存のメモリ辞書（_wind_forecast_cache）がL1として引き続き担い、ここ（wind_forecast_cache
# テーブル）はプロセス再起動をまたいだ永続化専用のL2として使う。
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
    # fetched_atはelevation_cacheと異なりREAL（time.time()のepoch秒）で持つ。
    # weather_client.py側のTTL判定が既にepoch秒の引き算で書かれており、そのロジックを
    # そのまま流用するため（elevation_cacheのISO文字列はTTLを持たない恒久キャッシュゆえの
    # 人間可読性優先で、比較には使っていない）。
    conn.execute(
        """CREATE TABLE IF NOT EXISTS wind_forecast_cache (
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            data TEXT NOT NULL,
            fetched_at REAL NOT NULL,
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


def _get_wind_forecast_many_sync(
    keys: list[tuple[float, float]],
) -> dict[tuple[float, float], tuple[float, dict]]:
    # 数百件規模（風の格子点マップ、weather_client.py: WIND_GRID_VARIABLES参照）になりうるが、
    # 1回のasyncio.to_thread呼び出しの中でキーぶんだけ逐次SELECTする（IN句でのタプル一括
    # 照合はSQLiteの標準構文では素直に書けない上、スレッド接続の使い回し
    # （モジュール冒頭コメント参照）のおかげで1クエリはミリ秒未満のため、逐次でも実用上
    # 問題にならない。呼び出し側の非同期ディスパッチ回数を1回に抑えることが本来の狙い）。
    try:
        conn = _get_connection()
        result: dict[tuple[float, float], tuple[float, dict]] = {}
        for lat, lon in keys:
            row = conn.execute(
                "SELECT data, fetched_at FROM wind_forecast_cache WHERE lat = ? AND lon = ?", (lat, lon)
            ).fetchone()
            if row is not None:
                result[(lat, lon)] = (row[1], json.loads(row[0]))
        return result
    except (sqlite3.Error, ValueError) as exc:
        log_throttled_warning("cache:wind-forecast-sqlite", "[cache:wind-forecast-sqlite] read failed error=%r", exc)
        _discard_connection()
        return {}


def _set_wind_forecast_many_sync(entries: dict[tuple[float, float], tuple[float, dict]]) -> None:
    try:
        conn = _get_connection()
        conn.executemany(
            "INSERT OR REPLACE INTO wind_forecast_cache (lat, lon, data, fetched_at) VALUES (?, ?, ?, ?)",
            [
                (lat, lon, json.dumps(data), fetched_at)
                for (lat, lon), (fetched_at, data) in entries.items()
            ],
        )
        conn.commit()
    except sqlite3.Error as exc:
        log_throttled_warning("cache:wind-forecast-sqlite", "[cache:wind-forecast-sqlite] write failed error=%r", exc)
        _discard_connection()


async def get_wind_forecast_many(
    keys: list[tuple[float, float]],
) -> dict[tuple[float, float], tuple[float, dict]]:
    """気象グリッド（風・降水延長予報）のDB永続化キャッシュから、渡したキーのうち
    見つかった分だけを{(lat,lon): (fetched_at, data)}で返す（TTL判定は呼び出し側が行う。
    ここは「保存されているか・いつのものか」を返すだけの薄い層）。プロセス再起動をまたいだ
    永続化が目的のL2キャッシュで、1プロセス内の高速な繰り返し参照はweather_client.py側の
    メモリ辞書（L1）が別途担う。"""
    if not keys:
        return {}
    return await asyncio.to_thread(_get_wind_forecast_many_sync, keys)


async def set_wind_forecast_many(entries: dict[tuple[float, float], tuple[float, dict]]) -> None:
    """新規に取得できた気象グリッドの応答をDBへ書き戻す（キャッシュの最適化であり、
    書き込み失敗はレスポンス自体の成否には関与しない。失敗時は抑制付きWARNINGで記録する
    だけに留める、_set_elevation_syncと同じ方針）。"""
    if not entries:
        return
    await asyncio.to_thread(_set_wind_forecast_many_sync, entries)


async def set_elevation(lat: float, lon: float, elevation_m: float | None) -> None:
    await asyncio.to_thread(_set_elevation_sync, lat, lon, elevation_m)
