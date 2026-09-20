"""派生データの鮮度と完成度を測る読み取り専用リポジトリ。

`GET /api/admin/derived-data/freshness`のデータ源。2つの問いを分けて見る。

- **鮮度**: その行はどの取込世代から作られたか（`source_run_id`）。同じソースの最新の
  成功runより古ければ、生データを取り直したのに派生を流し直していない。
- **完成度**: 値の列がNULLの行が何件あるか。NULLは「まだ計算していない」で、値が0で
  あることとは別の状態。

**対象は宣言から導く**——`source_run_id`を持つ表が派生データで、その表の主キーと
`source_run_id`以外の列が値である。表を1つ足しても、列を1つ足しても、ここは変わらない。
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure import derived_models  # noqa: F401  Base.metadataへの登録が目的
from app.infrastructure import source_models  # noqa: F401  同上（外部キーの解決に要る）
from app.infrastructure.orm_base import Base

#: 系譜の列。これを持つ表が派生データ。
SOURCE_RUN_COLUMN = "source_run_id"


def derived_tables() -> list:
    """`source_run_id`を持つ表（＝派生データ）。"""
    return [table for table in Base.metadata.sorted_tables
            if SOURCE_RUN_COLUMN in table.c]


def value_columns(table) -> list[str]:
    """その表の「値」の列。鍵と系譜を除いたもの。"""
    keys = {column.name for column in table.primary_key.columns} | {SOURCE_RUN_COLUMN}
    return [column.name for column in table.columns if column.name not in keys]


def counts_as_uncalculated(table, name: str) -> bool:
    """その列のNULLを「未計算」として数えてよいか。

    NULLが「確定して値が無い」を意味する列（橋の勾配・指定のない道・POIでないノード）は
    数えない。印は列の宣言（`ABSENT_OK`）が持つ——印の無い列は未計算として数える側へ
    倒れるので、付け忘れは鳴りすぎる方向にしか外れない。
    """
    return not table.c[name].info.get("null_means_absent", False)


@dataclass(frozen=True)
class ColumnCompleteness:
    column: str
    null_count: int
    #: NULLを未計算として数えてよい列か（`counts_as_uncalculated`）。
    counts_as_uncalculated: bool


@dataclass(frozen=True)
class TableFreshness:
    table_name: str
    row_count: int
    #: その表の行が指すいちばん古い取込run。行が無ければNone。
    oldest_run_id: int | None
    #: その取込runのソース名（`source_runs.source`）。
    source: str | None
    #: 同じソースの最新の成功run。
    latest_run_id: int | None
    columns: tuple[ColumnCompleteness, ...]

    @property
    def is_stale(self) -> bool:
        return (self.oldest_run_id is not None and self.latest_run_id is not None
                and self.oldest_run_id < self.latest_run_id)


@dataclass(frozen=True)
class DerivedDataFreshness:
    tables: tuple[TableFreshness, ...]


def build_table_sql(table) -> str:
    """1表ぶんの集計（行数・最古の世代・列ごとの未計算件数）を1回の走査で求める。

    列名は宣言からのみ組み立てる（外部入力を連結しない）。
    """
    nulls = ", ".join(
        f"count(*) FILTER (WHERE {name} IS NULL) AS null_{name}" for name in value_columns(table))
    columns = f"count(*) AS row_count, min({SOURCE_RUN_COLUMN}) AS oldest_run_id"
    if nulls:
        columns = f"{columns}, {nulls}"
    return f"SELECT {columns} FROM {table.name}"  # noqa: S608 宣言のみ


#: その取込runのソースと、同じソースの最新の成功run。
_RUN_SOURCE_SQL = text("""
SELECT r.source,
       (SELECT max(run_id) FROM source_runs l
         WHERE l.source = r.source AND l.status = 'succeeded') AS latest_run_id
FROM source_runs r WHERE r.run_id = :run_id
""")


class DerivedDataFreshnessQuery:
    """読み取り専用。全表走査を伴うため管理API専用。"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_freshness(self) -> DerivedDataFreshness:
        tables: list[TableFreshness] = []
        for table in derived_tables():
            row = (await self._session.execute(text(build_table_sql(table)))).mappings().one()
            oldest = row["oldest_run_id"]
            source = latest = None
            if oldest is not None:
                run = (await self._session.execute(_RUN_SOURCE_SQL, {"run_id": oldest})).first()
                if run is not None:
                    source, latest = run.source, run.latest_run_id
            tables.append(TableFreshness(
                table_name=table.name,
                row_count=int(row["row_count"]),
                oldest_run_id=oldest,
                source=source,
                latest_run_id=latest,
                columns=tuple(
                    ColumnCompleteness(
                        column=name, null_count=int(row[f"null_{name}"]),
                        counts_as_uncalculated=counts_as_uncalculated(table, name))
                    for name in value_columns(table)),
            ))
        return DerivedDataFreshness(tables=tuple(tables))
