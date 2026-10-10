"""複数のバッチが同じ形で必要とするものを集める。

特定のバッチだけが使うものは、そのバッチが持つ。
"""

import argparse
import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable, Coroutine, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, TypeVar

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings

_T = TypeVar("_T")


@asynccontextmanager
async def batch_session_factory(
    database_url: str | None, *, schema: str | None = None,
) -> AsyncIterator[async_sessionmaker]:
    """バッチ用のセッションファクトリを作り、終了時にエンジンを必ず破棄する。

    バッチはリクエスト経路と違い自前でエンジンを持つ。`infrastructure/database.py`の
    共有セッションファクトリはアプリ稼働中の接続プールを前提にしており、単発実行の
    バッチが使うとプロセス終了時に破棄されない接続が残る。

    `expire_on_commit=False`はバッチ共通の前提——commit後もORMオブジェクトの属性へ
    触れる（件数集計・ログ出力）ため。

    `schema`を渡すと、表の名前をそのスキーマから先に探す（無ければ`public`）。
    """
    connect_args = {"server_settings": {"search_path": f"{schema}, public"}} if schema else {}
    engine = create_async_engine(database_url or settings.database_url, connect_args=connect_args)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


def run_batch_cli(
    parser: argparse.ArgumentParser,
    start: Callable[[argparse.Namespace, str], Coroutine[Any, Any, int]],
) -> int:
    """DBを書くバッチの入口の骨格。ログを整え、引数を読み、本体を流す。

    `--database-url`はここで足す（省けば設定値）。`start`は読んだ引数とDBのURLを受けて
    本体のコルーチンを返す。イベントループの外で呼ぶので、引数の検査（`parser.error`）は
    `start`の中に置いてよい。
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()
    return asyncio.run(start(args, args.database_url or settings.database_url))


def affected_rows(status: str) -> int:
    """asyncpgの`execute`が返す状態の文字列（`INSERT 0 123`・`UPDATE 45`等）から、書いた行の数を読む。"""
    return int(status.split()[-1])


def reused_edges_sql(previous: str | None, source: str = "road_edges", condition: str = "") -> str:
    """区間ごとに写す段が、前回の値を写す区間を一時の表`_reused`に置く。

    同じ形とみなすのは、鍵が同じで座標とその並びも同じ区間だけ（`=`。`ST_Equals`のように形を幾何として
    比べる計算をしない）。`source`は今回の区間（別名`s`。`geom`を持つ）、`condition`は段が足す
    結合と条件。`previous`がNone（写せない）なら空の表を置く。
    """
    if previous is None:
        return f"CREATE TEMP TABLE _reused ON COMMIT DROP AS SELECT osm_way_id, segment_index FROM {source} WHERE false"
    return f"""
CREATE TEMP TABLE _reused ON COMMIT DROP AS
SELECT s.osm_way_id, s.segment_index
FROM {source} s JOIN {previous}.road_edges p
  ON p.osm_way_id = s.osm_way_id AND p.segment_index = s.segment_index AND p.geom = s.geom
{condition}
"""


def copy_reused_sql(table: str, columns: Sequence[str], previous: str) -> str:
    """`_reused`の区間へ、前回の表`table`の値を写す。前回に値の無かった区間は前回の表に行が無く、今回も行を持たない。"""
    return f"""
INSERT INTO {table} (osm_way_id, segment_index, {", ".join(columns)})
SELECT p.osm_way_id, p.segment_index, {", ".join(f"p.{column}" for column in columns)}
FROM _reused r JOIN {previous}.{table} p
  ON p.osm_way_id = r.osm_way_id AND p.segment_index = r.segment_index
"""


def asyncpg_dsn(sqlalchemy_url: str) -> str:
    """SQLAlchemy用URLを、asyncpg.connectが受け付けるDSNへ正規化する。

    `ssl=`クエリはSQLAlchemyのasyncpgダイアレクト固有の書き方で、asyncpgは解さない。
    libpq互換の`sslmode=`へ読み替える。
    """
    dsn = sqlalchemy_url.replace("+asyncpg", "")
    return dsn.replace("?ssl=", "?sslmode=").replace("&ssl=", "&sslmode=")



#: 取込と派生の作り直しが取るadvisory lockの名前（`hashtext`で鍵にする）。作り直しは排他で、取込は共有で
#: 取る——取込どうしは並んで走れ、取込と作り直しはどちらかが止まる。作り直しの段と段の間に取込が
#: 終わると、段ごとに違う取込を読み、記録した取込（`derived_source_runs`）とも食い違うため。
SOURCE_DATA_LOCK = "source_data"


#: 進捗を出す間隔（秒）。件数ごとに出すと、関東全域では行数が多すぎて読めない。
PROGRESS_INTERVAL_SECONDS = 15.0


def format_duration(seconds: float) -> str:
    minutes, second = divmod(int(seconds), 60)
    hour, minute = divmod(minutes, 60)
    return f"{hour}時間{minute:02d}分" if hour else f"{minute}分{second:02d}秒"


def format_progress(done: int, total: int | None, elapsed: float, unit: str = "件") -> str:
    """済んだ数・速さ・残りの見込み。

    `total`がNoneのとき（流しながら読むソースのように、全体数が終わるまで分からない
    とき）は残りを出さない——分からないものを推測で埋めると、読み手が当てにする。
    """
    rate = done / elapsed if elapsed > 0 else 0.0
    if total:
        remaining = (total - done) / rate if rate > 0 else 0.0
        return (f"{done:,}/{total:,}{unit}（{done / total * 100:.1f}%）"
                f" / 経過 {format_duration(elapsed)} / {rate:.1f}{unit}/秒"
                f" / 残り およそ {format_duration(remaining)}")
    return f"{done:,}{unit} / 経過 {format_duration(elapsed)} / {rate:.1f}{unit}/秒"


#: 取得途中の一時ファイルの印。所定の名前と紛れないもの。
FETCH_PART_SUFFIX = ".part"

#: 落としたが開けなかったものを退ける先。消さないのは、開けない理由が壊れていることとは
#: 限らず、消すと落とし直しにまた時間を払うため。
FETCH_BROKEN_SUFFIX = ".broken"


def fetch_verified(
    url: str,
    destination: Path,
    readable: Callable[[Path], bool],
    *,
    timeout: httpx.Timeout | float,
    logger: logging.Logger,
) -> bool:
    """配布元のファイルを手元の所定の名前へ写す。何度実行しても安全で、終わる。

    - 手元にあって読めるファイルは落とし直さない
    - 一時ファイルへ書いてから所定の名前へ移す。途中で落ちた半端なものを「取得済み」に
      見せない
    - 落とし終えたら`readable`で実際に開いてみる。開けなければ退けてFalseを返す——読めない
      ファイルを置いたまま成功を報告すると、次に落ちるのはそれを読む取込の途中になる

    大きさだけでは半端なファイルも配布元が200で返すエラー本文も弾けないため、`readable`は
    中身を開いて確かめるものを渡す。通信の失敗は例外のまま呼び出し側へ出す。
    """
    if destination.exists() and readable(destination):
        logger.info("既にある %s", destination)
        return True
    logger.info("取りに行く %s", url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + FETCH_PART_SUFFIX)
    started = time.perf_counter()
    last_report = started
    written = 0
    with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length") or 0) or None
        with temporary.open("wb") as sink:
            for chunk in response.iter_bytes():
                sink.write(chunk)
                written += len(chunk)
                now = time.perf_counter()
                if now - last_report < PROGRESS_INTERVAL_SECONDS:
                    continue
                last_report = now
                logger.info("取得中 %s", format_progress(
                    written // (1024 * 1024),
                    total // (1024 * 1024) if total else None,
                    now - started, "MB"))
    temporary.replace(destination)
    logger.info("取得した %s（%.1f MB / %s）", destination.name,
                written / (1024 * 1024), format_duration(time.perf_counter() - started))
    if readable(destination):
        return True
    broken = destination.with_name(destination.name + FETCH_BROKEN_SUFFIX)
    destination.replace(broken)
    logger.error("落としたが開けない: %s（%s へ退けた。もう一度実行すると取り直す）",
                 destination.name, broken.name)
    return False
