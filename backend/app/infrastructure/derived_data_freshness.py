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

from app.domain.traffic import HIGHWAY_RANK
from app.domain.derived_data_versions import (
    EDGE_ATTRIBUTE_COUNTS_ALGORITHM_VERSION as _EDGE_ALGORITHM_VERSION,
    WAY_ATTRIBUTE_COUNTS_ALGORITHM_VERSION as _WAY_ALGORITHM_VERSION,
    WAY_CURVATURE_ALGORITHM_VERSION as _CURVATURE_ALGORITHM_VERSION,
    WAY_DIVIDED_CARRIAGEWAY_ALGORITHM_VERSION as _DIVIDED_CARRIAGEWAY_ALGORITHM_VERSION,
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
        table_name="way_divided_carriageway",
        sources=(SourceRunSpec("OSM取込", "osm_import_runs", "source_osm_import_run_id"),),
        algorithm_version_current=_DIVIDED_CARRIAGEWAY_ALGORITHM_VERSION,
        algorithm_version_owner="precompute_way_divided_carriageway.ALGORITHM_VERSION",
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
PRECOMPUTE_NOT_IN_LEDGER: dict[str, str] = {}


@dataclass(frozen=True)
class CompletenessSpec:
    """世代比較ができない派生データ1件の宣言。

    `road_edges`・`road_nodes`の列へ直接書くバッチは、その列に系譜
    （`source_*_import_run_id`・`algorithm_version`）を持たないため世代比較の台帳に載せられない。
    代わりに「母集団のうち、まだ計算されていない行が何件あるか」を数える。**取込で母集団が
    増えたのにバッチを再実行していない状態**は、この件数が0でないこととして現れる。

    `uncalculated`は母集団テーブルに対する述語で、specの内部定数のみから組み立てる
    （外部入力を連結しない）。未計算を厳密に表せない列があるため`note`で但し書きを添える
    ——`road_nodes.degree`は`NOT NULL DEFAULT 0`で、未計算と本当に次数0の行を区別できない。

    `in_scope`は**担当バッチが処理できる行**の条件で、この宣言が唯一の情報源である。バッチは
    対象を選ぶselectをここから組み立て、台帳は未計算の判定へANDで掛ける。両者が別々にこの
    条件を持つと、バッチが永久に計算しない行を台帳が未計算と数え続け、台帳は「すべて最新」へ
    到達できなくなる——常に出続ける警告は読まれなくなる。
    """

    label: str
    population_table: str
    uncalculated: str
    owner: str
    note: str = ""
    #: 担当バッチが処理できる行（母集団に対する述語）。全行が対象なら既定のまま。
    in_scope: str = "TRUE"


COMPLETENESS_SPECS: tuple[CompletenessSpec, ...] = (
    CompletenessSpec(
        label="elevation_attributes",
        population_table="road_edges",
        uncalculated=(
            "NOT EXISTS (SELECT 1 FROM elevation_attributes ea WHERE ea.edge_id = road_edges.edge_id)"
        ),
        owner="precompute_elevation_attributes",
    ),
    CompletenessSpec(
        label="road_edges.curvature_deg_per_km",
        population_table="road_edges",
        uncalculated="curvature_deg_per_km IS NULL",
        owner="precompute_edge_curvature",
        note=(
            "ルート評価が読む列。未計算のままだと蛇行軸が重みの再正規化で薄まり、警告なく評価から抜ける。"
            "長さ0のEdgeは度/kmを定義できないため対象外（母集団には含むが未計算には数えない）"
        ),
        # 度/kmは距離で割るため、長さ0のEdgeでは値が定義できない。
        in_scope="distance_m > 0",
    ),
    CompletenessSpec(
        label="road_nodes.degree",
        population_table="road_nodes",
        uncalculated="degree = 0",
        owner="precompute_road_node_degrees",
        note="この列はNOT NULL DEFAULT 0のため、未計算と本当に次数0の行を区別できない（0件が正常とは限らない）",
    ),
    CompletenessSpec(
        label="road_nodes.max_highway_rank",
        population_table="road_nodes",
        # この列もNOT NULL DEFAULT 0で、未計算と「順位表に無い道しか集まらない」を値だけでは
        # 区別できない。**順位の付く道が接しているのに0**なら未計算だと言い切れるため、そこへ
        # 絞る（自転車道・歩道だけのノードは常に0が正しく、そのままでは0件へ到達できない）。
        # 信号の列も同じバッチが同時に書くため、片方が計算済みならもう片方も計算済み。
        uncalculated=(
            "max_highway_rank = 0 AND EXISTS ("
            "SELECT 1 FROM road_edges e"
            " WHERE (e.from_node_id = road_nodes.node_id OR e.to_node_id = road_nodes.node_id)"
            f" AND e.highway IN ({', '.join(repr(h) for h in sorted(HIGHWAY_RANK))}))"
        ),
        owner="precompute_road_node_intersections",
        note="has_traffic_signalsも同じバッチが同時に書くため、この件数が0なら両方が計算済み",
    ),
)


def build_completeness_sql(spec: CompletenessSpec):
    """1件ぶんの母集団件数と未計算件数（1回の走査でまとめる）。
    テーブル名・述語はspecの内部定数のみから生成する（外部入力を連結しない）。

    未計算は**担当バッチが処理できる行に限る**（`in_scope`）。対象外の行まで数えると、
    作り直しても減らない件数が残り続ける。母集団は対象外の行も含めた全件のままにする
    ——「全体のうち何件か」を読むための数だから。"""
    return text(
        f"SELECT count(*) AS population, "  # noqa: S608 固定の内部宣言のみ使用
        f"count(*) FILTER (WHERE ({spec.in_scope}) AND ({spec.uncalculated})) AS uncalculated "
        f"FROM {spec.population_table}"
    )


def completeness_spec(label: str) -> CompletenessSpec:
    """ラベルで宣言を引く。担当バッチが自分の対象条件をここから取るために使う
    （バッチ側に同じ述語を書かない）。"""
    return next(spec for spec in COMPLETENESS_SPECS if spec.label == label)


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
class CompletenessCounts:
    """完成度1件ぶんの集計結果の生値。"""

    label: str
    population: int
    uncalculated: int


@dataclass(frozen=True)
class DerivedDataFreshnessCounts:
    generations: tuple[GenerationFreshnessCounts, ...]
    latest_succeeded_run_id: dict[str, int | None]
    completeness: tuple[CompletenessCounts, ...]


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

        completeness: list[CompletenessCounts] = []
        for spec in COMPLETENESS_SPECS:
            row = (await self._session.execute(build_completeness_sql(spec))).mappings().one()
            completeness.append(
                CompletenessCounts(
                    label=spec.label,
                    population=int(row["population"]),
                    uncalculated=int(row["uncalculated"]),
                )
            )

        return DerivedDataFreshnessCounts(
            generations=tuple(generations),
            latest_succeeded_run_id=latest_succeeded_run_id,
            completeness=tuple(completeness),
        )
