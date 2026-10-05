"""派生データの鮮度と完成度を測る読み取り専用リポジトリ。

`GET /api/admin/derived-data/freshness`のデータ源。別々の問いを分けて見る。

- **鮮度**: ソースごとに、今の派生の表を作った取込（`derived_source_runs`）が、そのソースの成功した
  最新の取込と同じか。違えば、生データを取り直したのに派生を作り直していない。取込が1度も成功して
  いないソースと、まだ作り直しに使っていないソースも、作り直し（か取込）が要る側に数える。
- **完成度**: 値の列がNULLの行が何件あるか。NULLは「まだ計算していない」で、値が0で
  あることとは別の状態。
- **被覆**: 親（生データ、または親の派生表）に対して行そのものが無い件数。**鮮度と
  完成度はこれを見つけられない**——行が無ければ古くもなければNULLでもない。外部キーは
  向きが逆（子から親を縛る）ため制約では表せず、ここが引き受ける。

**対象は宣言から導く**——表の印（`orm_base.py: DERIVED`）を持つ表が派生データで、その表の主キー
以外の列が値である。ソースは取込の記録と作り直しの記録にあるものを全部並べる。表・列・ソースを
1つ足しても、ここは変わらない。
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.strict_model import StrictModel
from app.infrastructure import derived_models
from app.infrastructure import source_models
from app.infrastructure.derived_data_meta import DerivedSourceRunRow
from app.infrastructure.orm_base import DERIVED_KEY, Base

#: 被覆の期待を書いた印（`derived_models.covers`）。
COVERS_SOURCE_KEY = "covers_source"


def derived_tables() -> list:
    """表の印（`orm_base.py: DERIVED`）を持つ表（＝派生データ）。"""
    return [table for table in Base.metadata.sorted_tables
            if table.info.get(DERIVED_KEY)]


def value_columns(table) -> list[str]:
    """その表の「値」の列。鍵を除いたもの。"""
    keys = {column.name for column in table.primary_key.columns}
    return [column.name for column in table.columns if column.name not in keys]


def covered_source(table) -> tuple[source_models.Source, str] | None:
    """`covers`を宣言した列があれば `(ソース名, 列名)`。無ければNone。"""
    for column in table.columns:
        source = column.info.get(COVERS_SOURCE_KEY)
        if source is not None:
            return source, column.name
    return None


def parent_derived_table(table) -> tuple[str, list[tuple[str, str]]] | None:
    """他の派生表を親に持つなら `(親の表名, [(親の列, 自分の列), ...])`。

    外部キーの宣言から導く——親子の対応を別に書き足さない。**自分の主キーがまるごと
    指している先だけ**を親とする。主キー以外の列のFK（`road_edges`の端点→
    `node_materials`）は「1行につき1件」の関係ではないため、母数にすると覆っていない側を
    欠けとして数えてしまう。
    """
    derived = {t.name for t in derived_tables()}
    primary_key = [column.name for column in table.primary_key.columns]
    pairs: dict[str, list[tuple[str, str]]] = {}
    for name in primary_key:
        for key in table.c[name].foreign_keys:
            if key.column.table.name in derived:
                pairs.setdefault(key.column.table.name, []).append((key.column.name, name))
    for name, columns in pairs.items():
        if [child for _, child in columns] == primary_key:
            return name, columns
    return None


def build_coverage_sql(table) -> str | None:
    """親にあって自分に無い行を数えるSQL。対象外の表はNone。

    列名・表名は宣言からのみ組み立てる（外部入力を連結しない）。
    """
    source = covered_source(table)
    if source is not None:
        name, key = source
        return (  # noqa: S608 宣言のみ
            "SELECT count(*) AS parent_row_count,"
            f" count(*) FILTER (WHERE d.{key} IS NULL) AS missing_rows"
            f" FROM {source_models.source_keys_sql(name)} f"
            f" LEFT JOIN (SELECT DISTINCT {key} FROM {table.name}) d"
            f" ON d.{key} = f.natural_key::bigint"
        )
    parent = parent_derived_table(table)
    if parent is None:
        return None
    parent_name, columns = parent
    on = " AND ".join(f"d.{child} = p.{parent_column}" for parent_column, child in columns)
    first_child = columns[0][1]
    return (  # noqa: S608 宣言のみ
        "SELECT count(*) AS parent_row_count,"
        f" count(*) FILTER (WHERE d.{first_child} IS NULL) AS missing_rows"
        f" FROM {parent_name} p LEFT JOIN {table.name} d ON {on}"
    )


def coverage_parent(table) -> str | None:
    """被覆の母数の呼び名（ソース名か親の表名）。対象外はNone。"""
    source = covered_source(table)
    if source is not None:
        return source[0]
    parent = parent_derived_table(table)
    return parent[0] if parent else None


def absent_condition(table, name: str) -> str:
    """その列のNULLが「確定して値が無い」を意味する行の条件（SQL）。それ以外の行のNULLは未計算。

    NULLが「確定して値が無い」を意味する列（橋の勾配・指定のない道・POIでないノード）は
    いつも、土地被覆の割合は有効画素の列に値があるときだけ、そう読む。印は列の宣言
    （`ABSENT_OK`・`ABSENT_WHEN_SET_KEY`）が持つ——印の無い列は未計算として数える側へ
    倒れるので、付け忘れは鳴りすぎる方向にしか外れない。
    """
    info = table.c[name].info
    if info.get("null_means_absent", False):
        return "TRUE"
    when_set = info.get(derived_models.ABSENT_WHEN_SET_KEY)
    if when_set is not None:
        return f"{table.c[when_set].name} IS NOT NULL"
    return "FALSE"


class ColumnCompleteness(StrictModel, frozen=True):
    """値の列1本ぶんの完成度。

    NULLには「まだ計算していない」と「確定して値が無い」がある。どちらの件数も持ち、
    作り直しが要る側に数えるのは前者だけ。
    """

    column: str
    #: NULLのうち、まだ計算していない行の数。
    uncalculated_count: int
    #: NULLのうち、確定して値が無い行の数（`absent_condition`）。
    absent_count: int


class Coverage(StrictModel, frozen=True):
    """親に対して行が欠けていないか。"""

    #: 母数の呼び名（生データのソース名、または親の表名）。
    parent: str
    parent_row_count: int
    #: 親にあって、この表に対応する行が無い件数。覆うはずの表で1件でもあれば作り直しが要る。鮮度・完成度は
    #: これを見つけられない（行が無ければ古くもなければNULLでもない）。
    missing_rows: int


class TableFreshness(StrictModel, frozen=True):
    table_name: str
    row_count: int
    columns: tuple[ColumnCompleteness, ...]
    #: 覆うことを宣言していない表（`node_materials`）はNone。
    coverage: Coverage | None

    @property
    def has_missing_rows(self) -> bool:
        return self.coverage is not None and self.coverage.missing_rows > 0


class SourceFreshness(StrictModel, frozen=True):
    source: str
    #: 今の派生の表を作った取込。まだ作り直しに使っていなければNone。
    derived_run_id: int | None
    #: そのソースの成功した最新の取込。1度も成功していなければNone。
    latest_run_id: int | None


@dataclass(frozen=True)
class DerivedDataFreshness:
    sources: tuple[SourceFreshness, ...]
    tables: tuple[TableFreshness, ...]


def build_table_sql(table) -> str:
    """1表ぶんの集計（行数・列ごとの未計算と確定した値なしの件数）を1回の走査で求める。

    列名は宣言からのみ組み立てる（外部入力を連結しない）。
    """
    counts = []
    for name in value_columns(table):
        absent = absent_condition(table, name)
        counts.append(f"count(*) FILTER (WHERE {name} IS NULL AND NOT ({absent})) AS uncalculated_{name}")
        counts.append(f"count(*) FILTER (WHERE {name} IS NULL AND ({absent})) AS absent_{name}")
    return f"SELECT {', '.join(['count(*) AS row_count', *counts])} FROM {table.name}"  # noqa: S608 宣言のみ


#: 取込か作り直しの記録にあるソースごとに、作り直しに使った取込と成功した最新の取込。
_SOURCES_SQL = text(f"""
SELECT s.source, d.run_id AS derived_run_id, l.run_id AS latest_run_id
FROM (SELECT source FROM {source_models.SourceRunRow.__tablename__}
      UNION SELECT source FROM {DerivedSourceRunRow.__tablename__}) s
LEFT JOIN {DerivedSourceRunRow.__tablename__} d ON d.source = s.source
LEFT JOIN ({source_models.LATEST_SUCCEEDED_RUNS_SQL}) l ON l.source = s.source
ORDER BY s.source
""")


class DerivedDataFreshnessQuery:
    """読み取り専用。全表走査を伴うため管理API専用。"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_freshness(self) -> DerivedDataFreshness:
        sources = tuple(
            SourceFreshness(source=row.source, derived_run_id=row.derived_run_id, latest_run_id=row.latest_run_id)
            for row in await self._session.execute(_SOURCES_SQL))
        tables: list[TableFreshness] = []
        for table in derived_tables():
            row = (await self._session.execute(text(build_table_sql(table)))).mappings().one()
            coverage = None
            coverage_sql = build_coverage_sql(table)
            parent = coverage_parent(table)
            if coverage_sql is not None and parent is not None:
                counts = (await self._session.execute(text(coverage_sql))).mappings().one()
                coverage = Coverage(
                    parent=parent,
                    parent_row_count=int(counts["parent_row_count"]),
                    missing_rows=int(counts["missing_rows"]),
                )
            tables.append(TableFreshness(
                table_name=table.name,
                row_count=int(row["row_count"]),
                columns=tuple(
                    ColumnCompleteness(
                        column=name, uncalculated_count=int(row[f"uncalculated_{name}"]),
                        absent_count=int(row[f"absent_{name}"]))
                    for name in value_columns(table)),
                coverage=coverage,
            ))
        return DerivedDataFreshness(sources=sources, tables=tuple(tables))
