"""本番DBの状態を読み取る専用リポジトリ（読み取りのみ、書き込みは一切しない）。

`GET /api/admin/db-status`（`api/routers/db_status.py`）のデータ源。
`derived_data_freshness.py`が「派生データが生データの世代に追いついているか」を見るのに対し、
本モジュールは**その判定の土台が健全か**を見る——取込runそのものが失敗していないか、行が
本当に入っているか、プランナが使う統計が取れているか、トランザクションが放置されていないか。

全テーブルの行数は統計値（`n_live_tup`）ではなく**実数**を数える。統計は
ANALYZEされていないテーブルでは桁が変わるほどずれるため、「取り込んだつもりが入っていない」の
検出には使えない。1クエリで全テーブルぶんを数えるために
`query_to_xml`を使う（テーブル名は`pg_stat_user_tables`由来で、`format('%I')`が識別子として
引用するため外部入力の連結にはならない）。DB全体の走査を伴うので、呼び出しは管理APIの
ボタン押下時のみ。
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ImportRunSpec:
    """生データ取込の記録テーブル1件の宣言。

    テーブルごとに「何件取り込んだか」の列名と、runを識別する列が違う（PBF名・対象年・
    種別）。読み手が見たいのは「いつ・何を・どこまで」なので、列名の違いは宣言で吸収する。
    """

    label: str
    table: str
    count_column: str
    #: runを識別する列（画面へそのまま出す）。テーブルごとに意味が違うため宣言で持つ。
    identity_columns: tuple[str, ...]


IMPORT_RUN_SPECS: tuple[ImportRunSpec, ...] = (
    ImportRunSpec("OSM取込", "osm_import_runs", "way_count", ("pbf_name", "bbox")),
    ImportRunSpec("事故取込", "accident_import_runs", "accident_count", ("occurred_year", "file_name")),
    ImportRunSpec("指定路線取込", "designation_import_runs", "designation_count", ("kind", "source")),
)

# PostGISが作る付属テーブル。アプリのデータではないため一覧から外す。
_EXCLUDED_TABLES = ("spatial_ref_sys",)

_TABLE_STATS_SQL = """
SELECT s.relname AS table_name,
       (xpath('/row/cnt/text()',
              query_to_xml(format('SELECT count(*) AS cnt FROM %I.%I', s.schemaname, s.relname),
                           false, true, '')))[1]::text::bigint AS row_count,
       pg_total_relation_size(s.relid) AS total_bytes,
       s.n_dead_tup,
       greatest(s.last_analyze, s.last_autoanalyze) AS analyzed_at,
       greatest(s.last_vacuum, s.last_autovacuum) AS vacuumed_at
FROM pg_stat_user_tables s
WHERE s.schemaname = 'public' AND s.relname <> ALL(:excluded)
ORDER BY pg_total_relation_size(s.relid) DESC
"""

# 自分自身（この問い合わせ）を数えると、実行中のクエリが常に1件ある状態に見える。
_CONNECTION_SQL = """
SELECT count(*) AS total,
       count(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_transaction,
       coalesce(max(EXTRACT(EPOCH FROM (now() - xact_start)))
                FILTER (WHERE state = 'idle in transaction'), 0)::float AS longest_idle_transaction_seconds,
       coalesce(max(EXTRACT(EPOCH FROM (now() - query_start)))
                FILTER (WHERE state = 'active'), 0)::float AS longest_query_seconds
FROM pg_stat_activity
WHERE datname = current_database() AND pid <> pg_backend_pid()
"""


@dataclass(frozen=True)
class ImportRunCounts:
    """取込1種別ぶんの生値。`latest`は成否を問わない最新、`latest_succeeded`は成功した最新。"""

    label: str
    latest_id: int | None
    latest_status: str | None
    latest_finished_at: datetime | None
    latest_identity: dict[str, str]
    latest_item_count: int | None
    latest_succeeded_id: int | None
    latest_succeeded_finished_at: datetime | None


@dataclass(frozen=True)
class TableCounts:
    table_name: str
    row_count: int
    total_bytes: int
    dead_tuples: int
    analyzed_at: datetime | None
    vacuumed_at: datetime | None


@dataclass(frozen=True)
class ConnectionCounts:
    total: int
    max_connections: int
    idle_in_transaction: int
    longest_idle_transaction_seconds: float
    longest_query_seconds: float


@dataclass(frozen=True)
class RoadGraphTile:
    """split済みタイル1件（`domain/region.py: ROAD_GRAPH_TILE_ZOOM`のXYZ座標）。
    ここに無い範囲は、初回のルート生成でsplitが走る＝冷パスになる。"""

    zoom: int
    x: int
    y: int
    fetched_at: datetime


@dataclass(frozen=True)
class DbStatusCounts:
    imports: tuple[ImportRunCounts, ...]
    tables: tuple[TableCounts, ...]
    connections: ConnectionCounts
    database_bytes: int


def build_latest_import_run_sql(spec: ImportRunSpec):
    """1種別ぶんの「最新run」と「成功した最新run」を1回で引く。
    テーブル名・列名はspecの内部宣言のみから組み立てる（外部入力を連結しない）。"""
    identity = ", ".join(f"latest.{column}::text AS {column}" for column in spec.identity_columns)
    return text(  # noqa: S608 固定の内部宣言のみ使用
        f"""
        WITH latest AS (
            SELECT * FROM {spec.table} ORDER BY id DESC LIMIT 1
        ), latest_succeeded AS (
            SELECT id, finished_at FROM {spec.table} WHERE status = 'succeeded' ORDER BY id DESC LIMIT 1
        )
        SELECT latest.id AS latest_id,
               latest.status AS latest_status,
               latest.finished_at AS latest_finished_at,
               latest.{spec.count_column} AS latest_item_count,
               {identity},
               (SELECT id FROM latest_succeeded) AS latest_succeeded_id,
               (SELECT finished_at FROM latest_succeeded) AS latest_succeeded_finished_at
        FROM latest
        """
    )


_ROAD_GRAPH_TILES_SQL = """
SELECT zoom, x, y, fetched_at FROM road_graph_tiles ORDER BY zoom, x, y
"""


class DbStatusQuery:
    """読み取り専用。全表走査を伴うため管理API専用（`api/dependencies.py`が長い
    command_timeoutのセッションを渡す）。"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def fetch_road_graph_tiles(self) -> tuple[RoadGraphTile, ...]:
        """split済みタイルの全件。鮮度の集計（`fetch_counts`）とは分けて呼ぶ——地図を開いた
        ときだけ要る一方、本番では全域ぶんの件数になるため毎回運ぶと無駄になる。"""
        rows = (await self._session.execute(text(_ROAD_GRAPH_TILES_SQL))).mappings().all()
        return tuple(
            RoadGraphTile(zoom=int(row["zoom"]), x=int(row["x"]), y=int(row["y"]), fetched_at=row["fetched_at"])
            for row in rows
        )

    async def fetch_counts(self) -> DbStatusCounts:
        imports: list[ImportRunCounts] = []
        for spec in IMPORT_RUN_SPECS:
            row = (await self._session.execute(build_latest_import_run_sql(spec))).mappings().one_or_none()
            if row is None:
                imports.append(
                    ImportRunCounts(
                        label=spec.label,
                        latest_id=None,
                        latest_status=None,
                        latest_finished_at=None,
                        latest_identity={},
                        latest_item_count=None,
                        latest_succeeded_id=None,
                        latest_succeeded_finished_at=None,
                    )
                )
                continue
            imports.append(
                ImportRunCounts(
                    label=spec.label,
                    latest_id=int(row["latest_id"]),
                    latest_status=str(row["latest_status"]),
                    latest_finished_at=row["latest_finished_at"],
                    latest_identity={
                        column: str(row[column]) for column in spec.identity_columns if row[column] is not None
                    },
                    latest_item_count=None if row["latest_item_count"] is None else int(row["latest_item_count"]),
                    latest_succeeded_id=(
                        None if row["latest_succeeded_id"] is None else int(row["latest_succeeded_id"])
                    ),
                    latest_succeeded_finished_at=row["latest_succeeded_finished_at"],
                )
            )

        table_rows = (
            await self._session.execute(text(_TABLE_STATS_SQL), {"excluded": list(_EXCLUDED_TABLES)})
        ).mappings().all()
        tables = tuple(
            TableCounts(
                table_name=row["table_name"],
                row_count=int(row["row_count"]),
                total_bytes=int(row["total_bytes"]),
                dead_tuples=int(row["n_dead_tup"]),
                analyzed_at=row["analyzed_at"],
                vacuumed_at=row["vacuumed_at"],
            )
            for row in table_rows
        )

        connection_row = (await self._session.execute(text(_CONNECTION_SQL))).mappings().one()
        max_connections = int(
            (await self._session.execute(text("SELECT current_setting('max_connections')::int"))).scalar_one()
        )
        database_bytes = int(
            (await self._session.execute(text("SELECT pg_database_size(current_database())"))).scalar_one()
        )

        return DbStatusCounts(
            imports=tuple(imports),
            tables=tables,
            connections=ConnectionCounts(
                total=int(connection_row["total"]),
                max_connections=max_connections,
                idle_in_transaction=int(connection_row["idle_in_transaction"]),
                longest_idle_transaction_seconds=float(connection_row["longest_idle_transaction_seconds"]),
                longest_query_seconds=float(connection_row["longest_query_seconds"]),
            ),
            database_bytes=database_bytes,
        )
