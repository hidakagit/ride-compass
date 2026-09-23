"""派生データの鮮度と完成度を測る読み取り専用リポジトリ。

`GET /api/admin/derived-data/freshness`のデータ源。別々の問いを分けて見る。

- **鮮度**: その行はどの取込世代から作られたか（`source_run_id`）。同じソースの最新の
  成功runより古ければ、生データを取り直したのに派生を流し直していない。
- **完成度**: 値の列がNULLの行が何件あるか。NULLは「まだ計算していない」で、値が0で
  あることとは別の状態。
- **被覆**: 親（生データ、または親の派生表）に対して行そのものが無い件数。**鮮度と
  完成度はこれを見つけられない**——行が無ければ古くもなければNULLでもない。外部キーは
  向きが逆（子から親を縛る）ため制約では表せず、ここが引き受ける。

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

#: 被覆の期待を書いた印（`derived_models.covers`）。
COVERS_SOURCE_KEY = "covers_source"


def derived_tables() -> list:
    """`source_run_id`を持つ表（＝派生データ）。"""
    return [table for table in Base.metadata.sorted_tables
            if SOURCE_RUN_COLUMN in table.c]


def value_columns(table) -> list[str]:
    """その表の「値」の列。鍵と系譜を除いたもの。"""
    keys = {column.name for column in table.primary_key.columns} | {SOURCE_RUN_COLUMN}
    return [column.name for column in table.columns if column.name not in keys]


def covered_source(table) -> tuple[str, str] | None:
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
            " FROM source_features f"
            f" LEFT JOIN (SELECT DISTINCT {key} FROM {table.name}) d"
            f" ON d.{key} = f.natural_key::bigint"
            " WHERE f.source = :source"
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
class Coverage:
    """親に対して行が欠けていないか。"""

    #: 母数の呼び名（生データのソース名、または親の表名）。
    parent: str
    parent_row_count: int
    #: 親にあって、この表に対応する行が無い件数。
    missing_rows: int


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
    #: 覆うことを宣言していない表（`node_materials`）はNone。
    coverage: Coverage | None = None

    @property
    def is_stale(self) -> bool:
        return (self.oldest_run_id is not None and self.latest_run_id is not None
                and self.oldest_run_id < self.latest_run_id)

    @property
    def has_missing_rows(self) -> bool:
        return self.coverage is not None and self.coverage.missing_rows > 0


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
            coverage = None
            coverage_sql = build_coverage_sql(table)
            parent = coverage_parent(table)
            if coverage_sql is not None and parent is not None:
                covered = covered_source(table)
                params = {"source": covered[0]} if covered is not None else {}
                counts = (await self._session.execute(text(coverage_sql), params)).mappings().one()
                coverage = Coverage(
                    parent=parent,
                    parent_row_count=int(counts["parent_row_count"]),
                    missing_rows=int(counts["missing_rows"]),
                )
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
                coverage=coverage,
            ))
        return DerivedDataFreshness(tables=tuple(tables))
