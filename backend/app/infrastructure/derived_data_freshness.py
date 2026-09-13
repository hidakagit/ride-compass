"""派生データ（precomputeバッチの出力）の鮮度台帳を求める読み取り専用リポジトリ。

`GET /api/admin/derived-data/freshness`（`api/routers/derived_data_freshness.py`）の
データ源。`material_coverage.py`（材料ごとの欠損割合）が「値がNULL/未取得か」という
完成度を見るのに対し、本モジュールは「行は存在するが、参照している生データの世代が
最新の取込より古いままではないか」という鮮度を見る——別の切り口のため判定ロジックは
独立している。

`edge_attribute_counts`・`way_attribute_counts`・`designation_attributes`は
`source_*_import_run_id`列（高水位マーク方式——行単位の厳密な系譜ではなく「このバッチが
どのデータ世代までを見ていたか」を表す）を持つため、対応する`*_import_runs`テーブルの
最新成功run idと突き合わせて鮮度不整合を判定できる。`elevation_attributes`はこの列を
持たない（road_edgesのgeometryにのみ依存しOSMタグを参照しないため）。`road_edges`との
行数差分による完成度チェックのみを行い、鮮度ではなく完成度である点を呼び出し側
（サービス層・API）で明示する。
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.derived_data_versions import (
    EDGE_ATTRIBUTE_COUNTS_ALGORITHM_VERSION as _EDGE_ALGORITHM_VERSION,
    WAY_ATTRIBUTE_COUNTS_ALGORITHM_VERSION as _WAY_ALGORITHM_VERSION,
    WAY_CURVATURE_ALGORITHM_VERSION as _CURVATURE_ALGORITHM_VERSION,
    WAY_LANDCOVER_ALGORITHM_VERSION as _LANDCOVER_ALGORITHM_VERSION,
)


@dataclass(frozen=True)
class SourceRunSpec:
    """派生テーブルの1列が参照する生データ取込runの情報源。"""

    label: str
    run_table: str
    source_column: str


@dataclass(frozen=True)
class GenerationFreshnessSpec:
    """世代比較が可能な派生テーブル1件の宣言。`algorithm_version_current`が
    Noneの材料（designation_attributes）はalgorithm_version比較の対象外。"""

    table_name: str
    sources: tuple[SourceRunSpec, ...]
    algorithm_version_current: str | None
    algorithm_version_owner: str | None


# 版数は`domain/derived_data_versions.py`が単一の情報源（値を複製しない。batchからimportすると
# 本番webイメージに無い依存を連鎖で引き込む——モジュールのdocstring参照）。
GENERATION_FRESHNESS_SPECS: tuple[GenerationFreshnessSpec, ...] = (
    GenerationFreshnessSpec(
        table_name="edge_attribute_counts",
        sources=(
            SourceRunSpec("事故取込", "accident_import_runs", "source_accident_import_run_id"),
            SourceRunSpec("OSM取込", "osm_import_runs", "source_osm_import_run_id"),
        ),
        algorithm_version_current=_EDGE_ALGORITHM_VERSION,
        algorithm_version_owner="precompute_edge_attribute_counts.ALGORITHM_VERSION",
    ),
    GenerationFreshnessSpec(
        table_name="way_attribute_counts",
        sources=(
            SourceRunSpec("事故取込", "accident_import_runs", "source_accident_import_run_id"),
            SourceRunSpec("OSM取込", "osm_import_runs", "source_osm_import_run_id"),
        ),
        algorithm_version_current=_WAY_ALGORITHM_VERSION,
        algorithm_version_owner="precompute_way_attribute_counts.ALGORITHM_VERSION",
    ),
    GenerationFreshnessSpec(
        table_name="designation_attributes",
        sources=(SourceRunSpec("OSM取込", "osm_import_runs", "source_osm_import_run_id"),),
        algorithm_version_current=None,
        algorithm_version_owner=None,
    ),
    GenerationFreshnessSpec(
        table_name="way_landcover",
        sources=(SourceRunSpec("OSM取込", "osm_import_runs", "source_osm_import_run_id"),),
        algorithm_version_current=_LANDCOVER_ALGORITHM_VERSION,
        algorithm_version_owner="precompute_way_landcover.ALGORITHM_VERSION",
    ),
    GenerationFreshnessSpec(
        table_name="way_geometry",
        sources=(SourceRunSpec("OSM取込", "osm_import_runs", "source_osm_import_run_id"),),
        algorithm_version_current=_CURVATURE_ALGORITHM_VERSION,
        algorithm_version_owner="precompute_way_curvature.ALGORITHM_VERSION",
    ),
)

# 世代台帳（`GENERATION_FRESHNESS_SPECS`）へ載せない事前計算バッチと、その理由。
# `tests/test_derived_data_freshness.py`が`app/batch/precompute_*.py`側から母集団を引いて
# 突き合わせるため、新しいバッチはここか台帳のどちらかへ必ず現れる——どちらにも無いまま
# 増えると、その派生テーブルの陳腐化が管理画面から見えないまま残る。
# **理由を書けば消えるのは検査であって実害ではない**。ここに並ぶバッチの出力は、再実行を
# 忘れても管理画面のどこにも現れない。
PRECOMPUTE_NOT_IN_LEDGER: dict[str, str] = {
    "precompute_elevation_attributes": (
        "世代比較ではなく完成度（road_edgesとの行数差分）で別枠に載せている。"
        "source_*_import_run_id列を持たないため他と同じ判定ができない"
    ),
    "precompute_edge_curvature": (
        "書き込み先road_edges.curvature_deg_per_kmに系譜列が無く、載せる手段が無い。"
        "PBF再取込後にこのバッチだけ実行を忘れると、新規splitされたEdgeはNULLのまま残り"
        "蛇行軸が無警告で評価から抜ける（[T832](docs/tasks/T832.md)で扱う）"
    ),
    "precompute_road_node_degrees": (
        "書き込み先road_nodes.degreeに系譜列が無く、載せる手段が無い（同上、[T832](docs/tasks/T832.md)）"
    ),
}


def build_generation_freshness_sql(spec: GenerationFreshnessSpec):
    """1テーブルぶんの集計SELECT文（MIN・NULL件数を1回の走査でまとめる）。
    列名はspecの内部定数のみから生成する（外部入力を連結しない）。"""
    columns = []
    for source in spec.sources:
        columns.append(f"MIN({source.source_column}) AS {source.source_column}_min")
        columns.append(
            f"count(*) FILTER (WHERE {source.source_column} IS NULL) AS {source.source_column}_null_count"
        )
    if spec.algorithm_version_current is not None:
        columns.append("MIN(algorithm_version) AS algorithm_version_min")
        columns.append("count(*) FILTER (WHERE algorithm_version IS NULL) AS algorithm_version_null_count")
    columns_sql = ", ".join(columns)
    sql = f"SELECT count(*) AS row_count, {columns_sql} FROM {spec.table_name}"  # noqa: S608 固定の内部辞書のみ使用
    return text(sql)


_LATEST_SUCCEEDED_RUN_ID_SQL_TEMPLATE = "SELECT MAX(id) FROM {run_table} WHERE status = 'succeeded'"


@dataclass(frozen=True)
class GenerationFreshnessCounts:
    """1テーブルぶんの集計結果の生値。"""

    table_name: str
    row_count: int
    source_min: dict[str, int | None]
    source_null_count: dict[str, int]
    algorithm_version_min: str | None
    algorithm_version_null_count: int


@dataclass(frozen=True)
class DerivedDataFreshnessCounts:
    generations: tuple[GenerationFreshnessCounts, ...]
    latest_succeeded_run_id: dict[str, int | None]
    road_edges_total: int
    elevation_uncalculated_count: int


class DerivedDataFreshnessQuery:
    """読み取り専用でcommit対象の書き込みは無い。全表走査を伴うため管理API専用
    （`api/dependencies.py: get_derived_data_freshness_service`が長い
    command_timeoutのセッションを渡す）。"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_freshness_counts(self) -> DerivedDataFreshnessCounts:
        latest_succeeded_run_id: dict[str, int | None] = {}
        generations: list[GenerationFreshnessCounts] = []

        for spec in GENERATION_FRESHNESS_SPECS:
            for source in spec.sources:
                if source.run_table not in latest_succeeded_run_id:
                    sql = text(_LATEST_SUCCEEDED_RUN_ID_SQL_TEMPLATE.format(run_table=source.run_table))
                    latest_succeeded_run_id[source.run_table] = (await self._session.execute(sql)).scalar_one()

            row = (await self._session.execute(build_generation_freshness_sql(spec))).mappings().one()
            source_min = {source.source_column: row[f"{source.source_column}_min"] for source in spec.sources}
            source_null_count = {
                source.source_column: int(row[f"{source.source_column}_null_count"]) for source in spec.sources
            }
            has_algorithm_version = spec.algorithm_version_current is not None
            generations.append(
                GenerationFreshnessCounts(
                    table_name=spec.table_name,
                    row_count=int(row["row_count"]),
                    source_min=source_min,
                    source_null_count=source_null_count,
                    algorithm_version_min=row["algorithm_version_min"] if has_algorithm_version else None,
                    algorithm_version_null_count=(
                        int(row["algorithm_version_null_count"]) if has_algorithm_version else 0
                    ),
                )
            )

        road_edges_total = int((await self._session.execute(text("SELECT count(*) FROM road_edges"))).scalar_one())
        elevation_uncalculated_count = int(
            (
                await self._session.execute(
                    text(
                        "SELECT count(*) FROM road_edges "
                        "LEFT JOIN elevation_attributes ON elevation_attributes.edge_id = road_edges.edge_id "
                        "WHERE elevation_attributes.edge_id IS NULL"
                    )
                )
            ).scalar_one()
        )

        return DerivedDataFreshnessCounts(
            generations=tuple(generations),
            latest_succeeded_run_id=latest_succeeded_run_id,
            road_edges_total=road_edges_total,
            elevation_uncalculated_count=elevation_uncalculated_count,
        )
