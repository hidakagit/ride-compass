"""派生データ鮮度台帳（infrastructure/derived_data_freshness.py・
services/derived_data_freshness_service.py）のDB非依存テスト。
実DBでの集計はtest_derived_data_freshness_repository.py（postgis）が担う。"""

from datetime import datetime, timezone

from app.batch.precompute_edge_attribute_counts import ALGORITHM_VERSION as EDGE_ALGORITHM_VERSION
from app.batch.precompute_way_attribute_counts import ALGORITHM_VERSION as WAY_ALGORITHM_VERSION
from app.batch.precompute_way_landcover import ALGORITHM_VERSION as LANDCOVER_ALGORITHM_VERSION
from app.infrastructure import derived_data_freshness
from app.infrastructure.derived_data_freshness import (
    COMPLETENESS_SPECS,
    PRECOMPUTE_NOT_IN_LEDGER,
    GENERATION_FRESHNESS_SPECS,
    CompletenessCounts,
    DerivedDataFreshnessCounts,
    GenerationFreshnessCounts,
    build_completeness_sql,
    completeness_spec,
    build_generation_freshness_sql,
)
from app.services.derived_data_freshness_service import build_freshness_report

COMPUTED_AT = datetime(2026, 9, 4, tzinfo=timezone.utc)


def _batches_in_ledger() -> set[str]:
    """台帳のどちらかの枠に載っているバッチ。世代比較（系譜列を持つ）と完成度（持たない）で
    枠は違うが、「陳腐化が管理画面に現れる」という点では同じ扱いでよい。"""
    return {
        spec.algorithm_version_owner.split(".", 1)[0]
        for spec in GENERATION_FRESHNESS_SPECS
        if spec.algorithm_version_owner is not None
    } | {spec.owner for spec in COMPLETENESS_SPECS}


def _edge_counts(
    *,
    accident_min: int | None = 10,
    accident_null: int = 0,
    osm_min: int | None = 10,
    osm_null: int = 0,
    algorithm_version_min: str | None = EDGE_ALGORITHM_VERSION,
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
    kwargs.setdefault("algorithm_version_min", WAY_ALGORITHM_VERSION)
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


def _landcover_counts(
    *,
    osm_min: int | None = 10,
    osm_null: int = 0,
    algorithm_version_min: str | None = LANDCOVER_ALGORITHM_VERSION,
    algorithm_version_null: int = 0,
    row_count: int = 5,
) -> GenerationFreshnessCounts:
    return GenerationFreshnessCounts(
        table_name="way_landcover",
        row_count=row_count,
        source_min={"source_osm_import_run_id": osm_min},
        source_null_count={"source_osm_import_run_id": osm_null},
        algorithm_version_min=algorithm_version_min,
        algorithm_version_null_count=algorithm_version_null,
    )


def _default_counts(spec, *, latest: int = 10) -> GenerationFreshnessCounts:
    """specの宣言どおりの「鮮度に問題が無い」状態。

    テーブルごとの固定値を書き並べず、`GENERATION_FRESHNESS_SPECS`から組み立てる——
    書き並べると、台帳へ1件足したときにこのヘルパだけが取り残され、
    `build_freshness_report`のzip(strict=True)が落ちるまで気づけない。
    """
    return GenerationFreshnessCounts(
        table_name=spec.table_name,
        row_count=5,
        source_min={source.source_column: latest for source in spec.sources},
        source_null_count={source.source_column: 0 for source in spec.sources},
        algorithm_version_min=spec.algorithm_version_current,
        algorithm_version_null_count=0,
    )


def _counts(
    *,
    edge=None,
    way=None,
    designation=None,
    landcover=None,
    latest_accident: int | None = 10,
    latest_osm: int | None = 10,
    population: int = 5,
    uncalculated: int = 0,
) -> DerivedDataFreshnessCounts:
    overrides = {
        counts.table_name: counts
        for counts in (edge, way, designation, landcover)
        if counts is not None
    }
    return DerivedDataFreshnessCounts(
        generations=tuple(
            overrides.get(spec.table_name) or _default_counts(spec)
            for spec in GENERATION_FRESHNESS_SPECS
        ),
        latest_succeeded_run_id={"accident_import_runs": latest_accident, "osm_import_runs": latest_osm},
        completeness=tuple(
            CompletenessCounts(label=spec.label, population=population, uncalculated=uncalculated)
            for spec in COMPLETENESS_SPECS
        ),
    )


# --- 宣言テーブルの構造 ---


def test_every_precompute_batch_is_in_the_ledger_or_has_a_reason():
    """事前計算バッチが、世代台帳に載っているか載せない理由が書かれているか。

    母集団は`app/batch/precompute_*.py`の**すべて**。台帳に並ぶテーブル名を書き写す形だと、
    新しいバッチが台帳へ載らなくても「今あるものが今あるものと一致する」で通ってしまう。
    母集団を「`ALGORITHM_VERSION`を宣言しているもの」に絞る形にも同じ穴がある——版数を
    宣言しなければ台帳に載らなくても検査を通り抜けられる（実際に`precompute_edge_curvature`が
    そうなっていた）。
    """
    import pathlib

    batch_dir = pathlib.Path(derived_data_freshness.__file__).resolve().parents[1] / "batch"
    batches = {path.stem for path in sorted(batch_dir.glob("precompute_*.py"))}

    unregistered = batches - _batches_in_ledger() - set(PRECOMPUTE_NOT_IN_LEDGER)

    assert not unregistered, (
        f"{sorted(unregistered)}が台帳に無い。世代比較ができるならGENERATION_FRESHNESS_SPECSへ、"
        "系譜列を持たないならCOMPLETENESS_SPECSへ追加するか、どちらにも載せない理由を"
        "PRECOMPUTE_NOT_IN_LEDGERへ書くこと。"
    )


def test_the_exclusion_list_does_not_name_batches_that_are_gone():
    # 除外の理由だけが残り続けるのを防ぐ（母集団側から消えたら、台帳へ載ったら、除外も要らない）。
    import pathlib

    batch_dir = pathlib.Path(derived_data_freshness.__file__).resolve().parents[1] / "batch"
    batches = {path.stem for path in sorted(batch_dir.glob("precompute_*.py"))}

    assert not (set(PRECOMPUTE_NOT_IN_LEDGER) & _batches_in_ledger())
    assert set(PRECOMPUTE_NOT_IN_LEDGER) <= batches, "消えたバッチの除外理由が残っている"


def test_algorithm_version_value_and_owner_are_declared_together():
    # 片方だけ埋まっていると、集計SQLはalgorithm_version列を読むのに画面がどのバッチの
    # 責任かを示せない（またはその逆）。どちらが欠けても鮮度の読み手が迷子になる。
    for spec in GENERATION_FRESHNESS_SPECS:
        assert (spec.algorithm_version_current is None) == (spec.algorithm_version_owner is None), spec.table_name


def test_build_completeness_sql_counts_the_population_and_the_uncalculated_rows():
    # 述語は宣言のものをそのまま使う（列名・条件を書き写すと宣言と実際の集計がずれる）。
    for spec in COMPLETENESS_SPECS:
        sql = str(build_completeness_sql(spec))
        assert f"FROM {spec.population_table}" in sql
        assert f"FILTER (WHERE ({spec.in_scope}) AND ({spec.uncalculated}))" in sql
        assert "count(*) AS population" in sql


def test_completeness_specs_declare_the_batch_that_fills_them():
    # 未計算が残っていることだけ分かっても、回すバッチが分からなければ動けない。
    for spec in COMPLETENESS_SPECS:
        assert spec.owner.startswith("precompute_")


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


def test_report_carries_completeness_separately_from_generation_entries():
    report = build_freshness_report(_counts(population=100, uncalculated=7), COMPUTED_AT)

    assert [entry.label for entry in report.completeness] == [spec.label for spec in COMPLETENESS_SPECS]
    for entry in report.completeness:
        assert entry.population == 100
        assert entry.uncalculated_count == 7
        assert entry.is_incomplete is True
    assert report.computed_at == COMPUTED_AT
    assert len(report.generations) == len(GENERATION_FRESHNESS_SPECS)


def test_completeness_is_not_incomplete_when_nothing_is_uncalculated():
    report = build_freshness_report(_counts(population=100, uncalculated=0), COMPUTED_AT)

    assert all(entry.is_incomplete is False for entry in report.completeness)


def test_completeness_entries_carry_the_batch_to_rerun_and_its_caveat():
    # 未計算が残っていると分かっても、どのバッチを回せばよいか画面から分からなければ動けない。
    report = build_freshness_report(_counts(population=100, uncalculated=3), COMPUTED_AT)

    by_label = {entry.label: entry for entry in report.completeness}
    for spec in COMPLETENESS_SPECS:
        assert by_label[spec.label].owner == spec.owner
        assert by_label[spec.label].note == spec.note

    # 未計算を厳密に表せない列は但し書きを持つ（road_nodes.degreeはNOT NULL DEFAULT 0）。
    assert any(entry.note for entry in report.completeness)


def test_owner_batches_select_their_targets_from_the_declared_scope():
    """バッチの対象条件と台帳の未計算判定が、同じ宣言から出ていること。

    別々に持つと、バッチが永久に計算しない行を台帳が未計算として数え続ける。台帳は
    「すべて最新」へ到達できなくなり、常に出続ける警告は読まれなくなる（実際に蛇行で
    起きていた）。ここが通らなくなったら、条件をバッチ側へ書き写したということ。
    """
    import importlib

    for spec in COMPLETENESS_SPECS:
        module = importlib.import_module(f"app.batch.{spec.owner}")
        target_stmt = getattr(module, "target_stmt", None)
        if spec.in_scope == "TRUE":
            # 全行が対象のバッチは揃えるものが無い（対象を選ぶselectを持たない実装もある）。
            continue
        assert target_stmt is not None, f"{spec.owner}: 対象条件を持つなら target_stmt を公開すること"
        assert spec.in_scope in " ".join(str(target_stmt()).split()), (
            f"{spec.owner}: 対象を選ぶselectが宣言の in_scope を使っていない"
        )


def test_completeness_sql_excludes_rows_the_batch_cannot_process():
    """未計算の集計が`in_scope`で絞られていること（母集団は絞らない）。"""
    spec = completeness_spec("road_edges.curvature_deg_per_km")
    sql = " ".join(str(build_completeness_sql(spec)).split())

    assert f"FILTER (WHERE ({spec.in_scope}) AND ({spec.uncalculated}))" in sql
    assert "count(*) AS population," in sql  # 母集団は全件のまま
