"""派生データ鮮度台帳（infrastructure/derived_data_freshness.py・
services/derived_data_freshness_service.py）のDB非依存テスト。
実DBでの集計はtest_derived_data_freshness_repository.py（postgis）が担う。"""

from datetime import datetime, timezone

from app.infrastructure.derived_data_freshness import (
    GENERATION_FRESHNESS_SPECS,
    DerivedDataFreshnessCounts,
    GenerationFreshnessCounts,
    build_generation_freshness_sql,
)
from app.services.derived_data_freshness_service import build_freshness_report

COMPUTED_AT = datetime(2026, 9, 4, tzinfo=timezone.utc)


def _edge_counts(
    *,
    accident_min: int | None = 10,
    accident_null: int = 0,
    osm_min: int | None = 10,
    osm_null: int = 0,
    algorithm_version_min: str | None = "v1",
    algorithm_version_null: int = 0,
    row_count: int = 5,
) -> GenerationFreshnessCounts:
    return GenerationFreshnessCounts(
        table_name="edge_attribute_counts",
        row_count=row_count,
        source_min={
            "source_accident_import_run_id": accident_min,
            "source_osm_import_run_id": osm_min,
        },
        source_null_count={
            "source_accident_import_run_id": accident_null,
            "source_osm_import_run_id": osm_null,
        },
        algorithm_version_min=algorithm_version_min,
        algorithm_version_null_count=algorithm_version_null,
    )


def _way_counts(**kwargs) -> GenerationFreshnessCounts:
    counts = _edge_counts(**kwargs)
    return GenerationFreshnessCounts(
        table_name="way_attribute_counts",
        row_count=counts.row_count,
        source_min=counts.source_min,
        source_null_count=counts.source_null_count,
        algorithm_version_min=counts.algorithm_version_min,
        algorithm_version_null_count=counts.algorithm_version_null_count,
    )


def _designation_counts(
    *, osm_min: int | None = 10, osm_null: int = 0, row_count: int = 5
) -> GenerationFreshnessCounts:
    return GenerationFreshnessCounts(
        table_name="designation_attributes",
        row_count=row_count,
        source_min={"source_osm_import_run_id": osm_min},
        source_null_count={"source_osm_import_run_id": osm_null},
        algorithm_version_min=None,
        algorithm_version_null_count=0,
    )


def _counts(
    *,
    edge=None,
    way=None,
    designation=None,
    latest_accident: int | None = 10,
    latest_osm: int | None = 10,
    road_edges_total: int = 5,
    elevation_uncalculated_count: int = 0,
) -> DerivedDataFreshnessCounts:
    return DerivedDataFreshnessCounts(
        generations=(edge or _edge_counts(), way or _way_counts(), designation or _designation_counts()),
        latest_succeeded_run_id={"accident_import_runs": latest_accident, "osm_import_runs": latest_osm},
        road_edges_total=road_edges_total,
        elevation_uncalculated_count=elevation_uncalculated_count,
    )


# --- 宣言テーブルの構造 ---


def test_generation_freshness_specs_cover_exactly_the_three_tables():
    assert [spec.table_name for spec in GENERATION_FRESHNESS_SPECS] == [
        "edge_attribute_counts",
        "way_attribute_counts",
        "designation_attributes",
    ]


def test_only_edge_and_way_specs_have_algorithm_version():
    by_table = {spec.table_name: spec for spec in GENERATION_FRESHNESS_SPECS}
    assert by_table["edge_attribute_counts"].algorithm_version_current is not None
    assert by_table["way_attribute_counts"].algorithm_version_current is not None
    assert by_table["designation_attributes"].algorithm_version_current is None


def test_build_generation_freshness_sql_has_one_column_pair_per_source():
    spec = GENERATION_FRESHNESS_SPECS[0]  # edge_attribute_counts
    sql = build_generation_freshness_sql(spec).text

    assert sql.startswith("SELECT count(*) AS row_count")
    assert "FROM edge_attribute_counts" in sql
    for source in spec.sources:
        assert f"MIN({source.source_column}) AS {source.source_column}_min" in sql
        assert f"{source.source_column}_null_count" in sql
    assert "algorithm_version_min" in sql


def test_build_generation_freshness_sql_omits_algorithm_version_when_unsupported():
    spec = GENERATION_FRESHNESS_SPECS[2]  # designation_attributes
    sql = build_generation_freshness_sql(spec).text

    assert "algorithm_version" not in sql


# --- is_stale判定（純関数） ---


def test_report_is_fresh_when_earliest_reflected_matches_latest_available():
    report = build_freshness_report(_counts(), COMPUTED_AT)

    for entry in report.generations:
        assert entry.is_stale is False
        for source in entry.sources:
            assert source.is_stale is False
        if entry.algorithm_version is not None:
            assert entry.algorithm_version.is_stale is False


def test_source_is_stale_when_earliest_reflected_is_older_than_latest_available():
    report = build_freshness_report(_counts(edge=_edge_counts(osm_min=8), latest_osm=10), COMPUTED_AT)
    edge_entry = next(e for e in report.generations if e.table_name == "edge_attribute_counts")
    osm_source = next(s for s in edge_entry.sources if s.run_table == "osm_import_runs")

    assert osm_source.is_stale is True
    assert edge_entry.is_stale is True


def test_source_is_stale_when_all_rows_have_null_source_run_id():
    report = build_freshness_report(
        _counts(edge=_edge_counts(osm_min=None, osm_null=5), latest_osm=10), COMPUTED_AT
    )
    edge_entry = next(e for e in report.generations if e.table_name == "edge_attribute_counts")
    osm_source = next(s for s in edge_entry.sources if s.run_table == "osm_import_runs")

    assert osm_source.is_stale is True
    assert osm_source.null_count == 5


def test_source_is_not_stale_when_no_succeeded_run_exists_yet():
    # 対応するimport_runsに成功run自体が無い（latest_available=None）環境では、
    # 比較対象が無いためstale判定はしない。
    report = build_freshness_report(_counts(latest_accident=None, latest_osm=None), COMPUTED_AT)

    for entry in report.generations:
        for source in entry.sources:
            assert source.is_stale is False


def test_algorithm_version_is_stale_when_oldest_recorded_differs_from_current():
    report = build_freshness_report(_counts(edge=_edge_counts(algorithm_version_min="v0")), COMPUTED_AT)
    edge_entry = next(e for e in report.generations if e.table_name == "edge_attribute_counts")

    assert edge_entry.algorithm_version.is_stale is True
    assert edge_entry.is_stale is True


def test_algorithm_version_is_not_stale_when_table_is_empty():
    # 行が1件も無いテーブルでalgorithm_version_minがNoneになるのは「データ自体が無い」
    # だけであり、アルゴリズム版数の不一致とは別問題（sourceチェック側で既にstale扱いになる）。
    report = build_freshness_report(
        _counts(edge=_edge_counts(row_count=0, algorithm_version_min=None, accident_min=None, osm_min=None)),
        COMPUTED_AT,
    )
    edge_entry = next(e for e in report.generations if e.table_name == "edge_attribute_counts")

    assert edge_entry.algorithm_version.is_stale is False


def test_designation_entry_has_no_algorithm_version():
    report = build_freshness_report(_counts(), COMPUTED_AT)
    designation_entry = next(e for e in report.generations if e.table_name == "designation_attributes")

    assert designation_entry.algorithm_version is None
    assert len(designation_entry.sources) == 1
    assert designation_entry.sources[0].run_table == "osm_import_runs"


def test_report_carries_elevation_completeness_separately_from_generation_entries():
    report = build_freshness_report(
        _counts(road_edges_total=100, elevation_uncalculated_count=7), COMPUTED_AT
    )

    assert report.elevation.road_edges_total == 100
    assert report.elevation.uncalculated_count == 7
    assert report.computed_at == COMPUTED_AT
    assert len(report.generations) == 3
