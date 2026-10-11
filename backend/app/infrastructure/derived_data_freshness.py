"""派生データの鮮度を測る読み取り専用リポジトリ。

`GET /api/admin/derived-data/freshness`のデータ源。作り直しが要るかを2つの比べで見る。

- **ソース**: ソースごとに、今の派生の表を作った取込（`derived_source_runs`）が、そのソースの成功した
  最新の取込と同じか。違えば、生データを取り直したのに派生を作り直していない。取込が1度も成功して
  いないソースと、まだ作り直しに使っていないソースも、作り直し（か取込）が要る側に数える。
- **表**: 表ごとに、今の表を作ったときの列（`derived_columns`）が、今の宣言の列と同じか。違えば、最後の
  作り直しの後に列を足した・消した（足した列は全行がNULLのまま）。記録が無い表も作り直しが要る側に数える。

値のNULLは作り直しが要るかに使わない——作り直しは表ごと入れ替え、流さない段は入力（書く表の列を含む）が前回と
同じ段だけなので、入れ替えた後のNULLは「計算した結果、値が無い」しかない（区間に切れない道・標高の取れない区間・土地被覆のタイルが無い区間）。
列ごとのNULLの件数は参考として返す。

**対象は宣言から導く**——表の印（`orm_base.py: DERIVED`）を持つ表が派生データで、その表の主キー
以外の列が値である。ソースは取込の記録と作り直しの記録にあるものを全部並べる。表・列・ソースを
1つ足しても、ここは変わらない。
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.strict_model import StrictModel
from app.infrastructure import source_models
from app.infrastructure.derived_data_meta import DerivedColumnRow, DerivedSourceRunRow
from app.infrastructure.orm_base import DERIVED_KEY, declared_metadata


def derived_tables() -> list:
    """表の印（`orm_base.py: DERIVED`）を持つ表（＝派生データ）。"""
    return [table for table in declared_metadata().sorted_tables
            if table.info.get(DERIVED_KEY)]


def declared_columns() -> dict[str, frozenset[str]]:
    """派生の表ごとの、今の宣言の列（表の名前 → 列の名前）。作り直しが記録し、台帳が記録と比べる。"""
    return {table.name: frozenset(column.name for column in table.columns) for table in derived_tables()}


def value_columns(table) -> list[str]:
    """その表の「値」の列。鍵を除いたもの。"""
    keys = {column.name for column in table.primary_key.columns}
    return [column.name for column in table.columns if column.name not in keys]


class ColumnNulls(StrictModel, frozen=True):
    """値の列1本ぶんのNULLの件数。作り直しが要るかには使わない参考。"""

    column: str
    null_count: int


class ColumnsChange(StrictModel, frozen=True):
    """今の表を作ったときの列（記録）から、今の宣言の列への変化。"""

    #: 今の宣言にあって、今の表を作ったときに無かった列（全行がNULLのまま）。
    added: tuple[str, ...]
    #: 今の表を作ったときにあって、今の宣言に無い列。
    removed: tuple[str, ...]


class TableFreshness(StrictModel, frozen=True):
    table_name: str
    row_count: int
    columns: tuple[ColumnNulls, ...]
    #: 今の表を作ったときの列の記録が無ければ（列を記録する作り直しをまだしていない）None。
    columns_change: ColumnsChange | None


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
    """1表ぶんの集計（行数・列ごとのNULLの件数）を1回の走査で求める。

    列名は宣言からのみ組み立てる（外部入力を連結しない）。
    """
    counts = [f"count(*) FILTER (WHERE {name} IS NULL) AS nulls_{name}" for name in value_columns(table)]
    return f"SELECT {', '.join(['count(*) AS row_count', *counts])} FROM {table.name}"  # 宣言のみ


#: 取込か作り直しの記録にあるソースごとに、作り直しに使った取込と成功した最新の取込。
_SOURCES_SQL = text(f"""
SELECT s.source, d.run_id AS derived_run_id, l.run_id AS latest_run_id
FROM (SELECT source FROM {source_models.SourceRunRow.__tablename__}
      UNION SELECT source FROM {DerivedSourceRunRow.__tablename__}) s
LEFT JOIN {DerivedSourceRunRow.__tablename__} d ON d.source = s.source
LEFT JOIN ({source_models.LATEST_SUCCEEDED_RUNS_SQL}) l ON l.source = s.source
ORDER BY s.source
""")

_COLUMNS_SQL = text(f"SELECT table_name, column_name FROM {DerivedColumnRow.__tablename__}")


class DerivedDataFreshnessQuery:
    """読み取り専用。全表走査を伴うため管理API専用。"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_freshness(self) -> DerivedDataFreshness:
        sources = tuple(
            SourceFreshness(source=row.source, derived_run_id=row.derived_run_id, latest_run_id=row.latest_run_id)
            for row in await self._session.execute(_SOURCES_SQL))
        recorded: dict[str, set[str]] = {}
        for column in await self._session.execute(_COLUMNS_SQL):
            recorded.setdefault(column.table_name, set()).add(column.column_name)
        declared = declared_columns()
        tables: list[TableFreshness] = []
        for table in derived_tables():
            row = (await self._session.execute(text(build_table_sql(table)))).mappings().one()
            built = recorded.get(table.name)
            tables.append(TableFreshness(
                table_name=table.name,
                row_count=int(row["row_count"]),
                columns=tuple(ColumnNulls(column=name, null_count=int(row[f"nulls_{name}"]))
                              for name in value_columns(table)),
                columns_change=None if built is None else ColumnsChange(
                    added=tuple(sorted(declared[table.name] - built)),
                    removed=tuple(sorted(built - declared[table.name]))),
            ))
        return DerivedDataFreshness(sources=sources, tables=tuple(tables))
